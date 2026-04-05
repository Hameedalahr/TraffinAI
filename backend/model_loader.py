from __future__ import annotations

from functools import wraps

import torch
from ultralytics import YOLO


def _torch_load_with_legacy_default():
    original_load = torch.load

    @wraps(original_load)
    def patched_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    return original_load, patched_load


def load_yolo_model(model_path: str) -> YOLO:
    """
    Load a trusted local Ultralytics checkpoint with compatibility for newer
    PyTorch versions where torch.load() defaults to weights_only=True.
    """
    original_load, patched_load = _torch_load_with_legacy_default()
    torch.load = patched_load
    try:
        return YOLO(model_path)
    finally:
        torch.load = original_load
