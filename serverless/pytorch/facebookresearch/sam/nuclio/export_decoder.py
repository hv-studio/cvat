# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Export a SAM decoder for CVAT's browser interactor, named by model type.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from segment_anything import SamPredictor, sam_model_registry
from segment_anything.modeling import Sam
from segment_anything.utils.onnx import SamOnnxModel


INPUT_NAMES = [
    "image_embeddings",
    "point_coords",
    "point_labels",
    "mask_input",
    "has_mask_input",
    "orig_im_size",
]
OUTPUT_NAMES = ["masks", "iou_predictions", "low_res_masks", "xtl", "ytl", "xbr", "ybr"]


class CropMask(torch.nn.Module):
    """Return a binary crop and inclusive bounds; empty masks use a zero 1x1 crop."""

    def forward(self, masks: torch.Tensor) -> tuple[torch.Tensor, ...]:
        mask = masks[0, 0]
        rows = mask.any(dim=1)
        cols = mask.any(dim=0)
        ys = torch.arange(mask.shape[0], device=mask.device)
        xs = torch.arange(mask.shape[1], device=mask.device)
        present = rows.any()
        xtl = torch.where(present, torch.where(cols, xs, mask.shape[1]).min(), 0)
        ytl = torch.where(present, torch.where(rows, ys, mask.shape[0]).min(), 0)
        xbr = torch.where(cols, xs, 0).max()
        ybr = torch.where(rows, ys, 0).max()
        cropped = masks[:, :, ytl : ybr + 1, xtl : xbr + 1].to(torch.uint8)
        return cropped, xtl, ytl, xbr, ybr


class CVATDecoder(SamOnnxModel):
    """SAM prompt/mask decoder with dynamic resizing and CVAT mask postprocessing."""

    def __init__(self, sam: Sam) -> None:
        super().__init__(sam, return_single_mask=True)
        self.crop = CropMask()
        self.threshold = sam.mask_threshold

    def mask_postprocessing(self, masks: torch.Tensor, orig_im_size: torch.Tensor) -> torch.Tensor:
        # Keep crop sizes as tensors so exporting does not freeze the image aspect ratio.
        masks = torch.nn.functional.interpolate(
            masks,
            size=(self.img_size, self.img_size),
            mode="bilinear",
            align_corners=False,
        )
        size = self.resize_longest_image_size(orig_im_size, self.img_size)
        masks = masks[..., : size[0], : size[1]]
        size = orig_im_size.to(torch.int64)
        return torch.nn.functional.interpolate(
            masks,
            size=(size[0], size[1]),
            mode="bilinear",
            align_corners=False,
        )

    def forward(
        self,
        image_embeddings: torch.Tensor,
        point_coords: torch.Tensor,
        point_labels: torch.Tensor,
        mask_input: torch.Tensor,
        has_mask_input: torch.Tensor,
        orig_im_size: torch.Tensor,
    ) -> tuple[torch.Tensor, ...]:
        masks, scores, low_res_masks = super().forward(
            image_embeddings,
            point_coords,
            point_labels,
            mask_input,
            has_mask_input,
            orig_im_size,
        )
        crop, xtl, ytl, xbr, ybr = self.crop(masks > self.threshold)
        return crop, scores, low_res_masks, xtl, ytl, xbr, ybr


def verify_decoder(path: Path, model: CVATDecoder, sam: Sam) -> list[dict[str, object]]:
    """Compare CPU ONNX and PyTorch on dynamic image sizes and iterative prompts."""
    options = ort.SessionOptions()
    options.intra_op_num_threads = torch.get_num_threads()
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    predictor = SamPredictor(sam)
    results: list[dict[str, object]] = []
    for height, width in [(240, 320), (320, 192)]:
        ys, xs = np.mgrid[:height, :width]
        image = np.stack((xs * 255 // width, ys * 255 // height, (xs + ys) % 256), axis=-1)
        predictor.set_image(image.astype(np.uint8))
        embeddings = predictor.get_image_embedding()
        previous = torch.zeros(1, 1, 256, 256)
        for labels in ([1], [1, 0], [2, 3, 1]):
            coords = np.array(
                [
                    [width * 0.3, height * 0.3],
                    [width * 0.8, height * 0.8],
                    [width * 0.5, height * 0.5],
                ],
                dtype=np.float32,
            )[: len(labels)]
            coords = predictor.transform.apply_coords(coords, (height, width)).astype(np.float32)
            inputs = (
                embeddings,
                torch.from_numpy(coords[None]),
                torch.tensor([labels], dtype=torch.float32),
                previous,
                torch.tensor([float(len(labels) == 2)]),
                torch.tensor([height, width], dtype=torch.float32),
            )
            with torch.no_grad():
                expected = [value.numpy() for value in model(*inputs)]
            actual = session.run(
                None, dict(zip(INPUT_NAMES, [value.numpy() for value in inputs], strict=True))
            )
            assert actual[0].dtype == np.uint8
            for index in (1, 2):
                np.testing.assert_allclose(actual[index], expected[index], rtol=2e-3, atol=2e-3)
            np.testing.assert_array_equal(actual[3:], expected[3:])
            agreement = float(np.mean(actual[0] == expected[0]))
            assert agreement > 0.999, f"Mask disagreement: {agreement}"
            previous = torch.from_numpy(actual[2])
            results.append({"size": [height, width], "labels": labels, "mask_agreement": agreement})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--model-type", required=True, help="SAM type: vit_b, vit_l, or vit_h")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"decoder-{args.model_type}.onnx"
    print(f"Loading {args.model_type}: {args.checkpoint}", flush=True)
    sam = sam_model_registry[args.model_type](checkpoint=str(args.checkpoint)).eval()
    model = CVATDecoder(sam).eval()
    inputs = (
        torch.zeros(1, 256, 64, 64),
        torch.tensor([[[100.0, 100.0], [200.0, 200.0]]]),
        torch.tensor([[1.0, 0.0]]),
        torch.zeros(1, 1, 256, 256),
        torch.zeros(1),
        torch.tensor([480.0, 640.0]),
    )
    print(f"Exporting {output.name}", flush=True)
    with torch.no_grad():
        torch.onnx.export(
            model,
            inputs,
            str(output),
            input_names=INPUT_NAMES,
            output_names=OUTPUT_NAMES,
            opset_version=17,
            dynamo=False,
            external_data=False,
            dynamic_axes={"point_coords": {1: "num_points"}, "point_labels": {1: "num_points"}},
        )
    onnx.checker.check_model(str(output))
    verification = verify_decoder(output, model, sam) if args.verify else []
    report = {"type": args.model_type, "decoder": output.name, "verification": verification}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
