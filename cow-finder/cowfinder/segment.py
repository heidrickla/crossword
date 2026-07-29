"""Binarize a page photo and segment letter glyphs."""
from __future__ import annotations

import cv2
import numpy as np


def binarize(gray: np.ndarray, block: int = 51, c: int = 15) -> np.ndarray:
    """Adaptive threshold (ink=255). Adaptive, not global: paper photos have
    illumination gradients that break Otsu."""
    th = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, c
    )
    return cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def find_glyphs(th: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Connected components filtered to plausible glyph boxes (x, y, w, h).

    Size bounds are derived from the median component size rather than
    hardcoded, so the same code works across photo resolutions.
    """
    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(th)
    raw = [
        (x, y, w, h, a)
        for x, y, w, h, a in (stats[i] for i in range(1, n))
        if a > 50 and w > 8 and h > 8
    ]
    if not raw:
        return []
    med_w = float(np.median([r[2] for r in raw]))
    med_h = float(np.median([r[3] for r in raw]))
    boxes = [
        (x, y, w, h)
        for x, y, w, h, a in raw
        if 0.35 * med_w < w < 2.2 * med_w
        and 0.35 * med_h < h < 2.2 * med_h
        and a > 0.04 * med_w * med_h
    ]
    return boxes
