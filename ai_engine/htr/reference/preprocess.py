"""Image preprocessing shared by training and inference (PIL + numpy only).

A line image becomes a float32 array of shape (height, width) with ink ~1 and
background ~0, so zero-padding on the right is "blank paper".
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

DEFAULT_HEIGHT = 64
DOWNSAMPLE = 4  # horizontal stride of the CNN: one output frame per 4 input columns


def preprocess(img: Image.Image, height: int = DEFAULT_HEIGHT, max_width: int | None = 2048,
               rtl: bool = False) -> np.ndarray:
    """rtl=True mirrors the line so the CNN reads right-to-left scripts in reading order."""
    img = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    w, h = img.size
    new_w = max(DOWNSAMPLE * 4, round(w * height / h))
    if max_width is not None:
        new_w = min(new_w, max_width)
    img = img.resize((new_w, height), Image.Resampling.BILINEAR)
    arr = 1.0 - np.asarray(img, dtype=np.float32) / 255.0
    return np.ascontiguousarray(arr[:, ::-1]) if rtl else arr


def pad_width(arr: np.ndarray, multiple: int = DOWNSAMPLE) -> np.ndarray:
    """Right-pad (H, W) with zeros so W is a multiple of the CNN stride."""
    w = arr.shape[1]
    target = -(-w // multiple) * multiple
    if target == w:
        return arr
    return np.pad(arr, ((0, 0), (0, target - w)))
