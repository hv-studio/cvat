# SAM interactive segmentation

The backend encodes images with a Meta SAM checkpoint. The browser runs the matching
ONNX prompt/mask decoder using ONNX Runtime Web (WASM). Supported types are `vit_b`,
`vit_l`, and `vit_h`; the Nuclio function ID remains `pth-facebookresearch-sam-vit-h`
for compatibility with the CVAT interactor plugin.

## Model configuration

Copy `weights.env.example` to `.env.sam` in the repository root. Set
`SAM_WEIGHTS_DIR` to an absolute directory containing the checkpoints and `cvat.json`:

```json
{
  "checkpoint": "sam-b.pth",
  "type": "vit_b"
}
```

`checkpoint` is relative to that directory. `.env.sam`, checkpoints, and generated
ONNX files are local assets; do not commit personal paths or model binaries.
The directory is mounted read-only at `/opt/weights/sam` in the function container.
A non-empty exported `SAM_WEIGHTS_DIR` or `SAM_RESTART_POLICY` overrides `.env.sam`.
Set `SAM_RESTART_POLICY=no` for manual startup; the default is `always`.

## Export matching decoders

Export each model type once using `nuclio/export_decoder.py`. It adds the CVAT
contract: a cropped `uint8` binary mask, inclusive `xtl/ytl/xbr/ybr` bounds,
`iou_predictions`, and float32 `low_res_masks`. Empty masks use a zero 1x1 crop.
Image dimensions and the number of points remain dynamic.

With Python 3.10+, PyTorch 2.6+, `torchvision`, `segment-anything`, `onnx`, and
`onnxruntime` installed:

```bash
python3 serverless/pytorch/facebookresearch/sam/nuclio/export_decoder.py \
  --checkpoint weights/sam/sam-b.pth --model-type vit_b \
  --output-dir weights/sam/onnx --verify
```

Use the actual checkpoint directory if different. `--verify` compares ONNX and
PyTorch with landscape/portrait images, positive/negative points, box prompts,
and iterative mask input. The exporter uses CPU and does not require a GPU.

If no SAM runtime image or Python environment is available, prepare an isolated
environment first (Ubuntu/Kubuntu):

```bash
sudo apt-get install -y python3-venv
python3 -m venv "$HOME/.cache/cvat-sam-export"
source "$HOME/.cache/cvat-sam-export/bin/activate"
python3 -m pip install --index-url https://mirrors.nju.edu.cn/pypi/web/simple \
  'torch>=2.6' torchvision segment-anything onnx onnxruntime
```

An existing SAM runtime image can provide these dependencies without rebuilding
or changing a running service. From the repository root, export all three variants:

```bash
(
  set -euo pipefail
  source .env.sam
  mkdir -p "$SAM_WEIGHTS_DIR/onnx"
  for variant in b l h; do
    docker run --rm --pull=never --network none \
      --user "$(id -u):$(id -g)" \
      --env PYTHONDONTWRITEBYTECODE=1 \
      --mount "type=bind,src=$PWD/serverless/pytorch/facebookresearch/sam/nuclio,dst=/source,readonly" \
      --mount "type=bind,src=$SAM_WEIGHTS_DIR,dst=/weights,readonly" \
      --mount "type=bind,src=$SAM_WEIGHTS_DIR/onnx,dst=/output" \
      --entrypoint python3 cvat.pth.facebookresearch.sam.vit_h:latest-gpu \
      /source/export_decoder.py --checkpoint "/weights/sam-$variant.pth" \
      --model-type "vit_$variant" --output-dir /output --verify
  done
)
```

The example assumes checkpoints named `sam-b.pth`, `sam-l.pth`, and `sam-h.pth`.
Export only the variants you have. PyTorch's legacy ONNX exporter is selected
explicitly (`dynamo=False`, opset 17).

Outputs are `decoder-vit_b.onnx`, `decoder-vit_l.onnx`, or `decoder-vit_h.onnx`,
plus a JSON verification report. Checkpoints of the same type share one decoder;
selection assumes they are compatible and does not compare checkpoint contents.

## Serve decoders and deploy

Include the SAM static-assets override when starting CVAT. It mounts only the
`onnx/` subdirectory into the UI container at `/assets/sam/`:

```bash
docker compose --env-file .env.sam \
  -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml \
  -f components/serverless/docker-compose.sam.yml \
  -f docker-compose.override.yml \
  up -d
```

Prepare the decoder directory before running this command. If additional Compose
variables live in `.env`, load both files with `--env-file .env --env-file .env.sam`.
For the frontend development server, export `SAM_WEIGHTS_DIR` before starting it;
its default decoder directory is `weights/sam/onnx` under the repository root.

Deploy the updated backend from the repository root with the script for your hardware:

```bash
# CPU
./serverless/deploy_cpu.sh serverless/pytorch/facebookresearch/sam/nuclio

# GPU
./serverless/deploy_gpu.sh serverless/pytorch/facebookresearch/sam/nuclio
```

Both scripts load `.env.sam`, mount the configured weights directory read-only, and
apply `SAM_RESTART_POLICY`. CPU deployments also require `cvat.json` and the matching
ONNX decoder; the CPU image no longer downloads a fixed ViT-H checkpoint during its build.

Alternatively, deploy an updated prebuilt GPU image as described in
[INSTALL.md](../../../../INSTALL.md). Backend and UI must both contain the
model-selection changes. Older image archives contain the fixed-model
implementation and need a code update; importing them alone does not enable this protocol.

Once the updated services and mounts are in place, switch models by:

1. Selecting an exported checkpoint and its type in `cvat.json`.
2. Restarting the SAM function container.
3. Refreshing the CVAT page before continuing annotation.

```bash
docker restart nuclio-nuclio-pth-facebookresearch-sam-vit-h
```

Configuration is read at function initialization. The response includes `model_type`
and image embeddings; the UI loads `/assets/sam/decoder-<type>.onnx` and reuses
cached embeddings for subsequent clicks. A changed type clears image/mask caches
and replaces the ONNX session. Refresh the page after switching models. If an ONNX
file is replaced under the same name, force-reload the page to clear the browser cache.

## Dependency sources

The GPU build uses NJU's Ubuntu and PyPI mirrors. The minimal base image installs
CA certificates from the signed HTTP Ubuntu repository before switching to HTTPS.
SAM is installed as `segment-anything` from PyPI. Nuclio SDK wheels are installed
locally with `--no-index`; container registries are configured separately.
