"""Auto-detect page orientation.

The tell (observed in practice): the intended orientation contains genuine
C and W glyphs. A grid that classifies as ONLY D and M with zero C/W is
exactly 180 deg off (every C reads as D, every W as M). We classify a sample
at each of the four rotations and pick the one with the healthiest C+W count.
"""
from __future__ import annotations

import cv2
import numpy as np

from .classify import classify
from .segment import binarize, find_glyphs

_ROT = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def best_rotation(gray: np.ndarray, sample: int = 60) -> int:
    scores: dict[int, float] = {}
    for deg, code in _ROT.items():
        g = gray if code is None else cv2.rotate(gray, code)
        th = binarize(g)
        boxes = find_glyphs(th)
        if not boxes:
            scores[deg] = -1
            continue
        idx = np.linspace(0, len(boxes) - 1, min(sample, len(boxes))).astype(int)
        chars = [classify(th, boxes[i]) for i in idx]
        n = len(chars)
        cw = sum(ch in "CW" for ch in chars)
        dm = sum(ch in "DM" for ch in chars)
        # favor C/W presence; penalize the all-decoy signature
        scores[deg] = (cw - 0.5 * dm) / n
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def apply_rotation(img: np.ndarray, deg: int) -> np.ndarray:
    code = _ROT[deg]
    return img if code is None else cv2.rotate(img, code)
