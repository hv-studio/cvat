# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from segment_anything import SamPredictor, sam_model_registry


class ModelHandler:
    """Load the configured SAM image encoder and produce image embeddings."""

    def __init__(self) -> None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        ckpt_dir = Path("/opt/weights/sam")
        config = json.loads((ckpt_dir / "cvat.json").read_text(encoding="utf-8"))
        checkpoint = str(ckpt_dir / config["checkpoint"])
        self.model_type = config["type"]
        sam_model = sam_model_registry[self.model_type](checkpoint=checkpoint)
        sam_model.to(device=device)
        self.predictor = SamPredictor(sam_model)

    def handle(self, image: Image.Image) -> torch.Tensor:
        """Encode an RGB image as float32 embeddings shaped [1, 256, 64, 64]."""
        self.predictor.set_image(np.array(image))
        return self.predictor.get_image_embedding()
