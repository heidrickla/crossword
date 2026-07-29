"""Independent re-verification of hits + human-checkable crop strips.

Re-classifies every glyph of every hit directly from raw pixels, independent
of grid bookkeeping. This catches coordinate-transform bugs (180-deg mapping,
row reversal, column mirroring are all easy to get off-by-one). Require 100%
or fail loudly.
"""
from __future__ import annotations

import cv2
import numpy as np

from .classify import classify
from .search import Hit


def reverify(
    th: np.ndarray,
    boxes: dict[tuple[int, int], tuple[int, int, int, int]],
    hits: list[Hit],
    word: str = "COW",
) -> list[tuple[Hit, str]]:
    """Return list of (hit, observed_string) mismatches. Empty = all verified."""
    bad = []
    for hit in hits:
        cells, _sym = hit
        s = "".join(classify(th, boxes[p]) for p in cells)
        if s != word:
            bad.append((hit, s))
    return bad


def crop_strips(
    img: np.ndarray,
    boxes: dict[tuple[int, int], tuple[int, int, int, int]],
    hits: list[Hit],
    tile: int = 80,
    pad: int = 10,
) -> np.ndarray:
    """One row per hit, letters in reading order — eyeball every hit fast."""
    rows = []
    for k, (cells, sym) in enumerate(hits):
        tiles = []
        for p in cells:
            x, y, w, h = boxes[p]
            roi = img[max(0, y - pad) : y + h + pad, max(0, x - pad) : x + w + pad]
            tiles.append(cv2.resize(roi, (tile, tile)))
        strip = cv2.hconcat(tiles)
        cv2.putText(strip, f"{k}{sym}", (2, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        rows.append(strip)
    return cv2.vconcat(rows) if rows else np.zeros((1, 1, 3), np.uint8)


COLORS = {
    "\u2192": (0, 0, 255), "\u2190": (0, 140, 255),
    "\u2193": (255, 0, 0), "\u2191": (255, 128, 0),
    "\u2198": (0, 160, 0), "\u2199": (180, 0, 180),
    "\u2197": (0, 200, 200), "\u2196": (128, 128, 0),
}


def annotate(
    img: np.ndarray,
    boxes: dict[tuple[int, int], tuple[int, int, int, int]],
    hits: list[Hit],
) -> np.ndarray:
    out = img.copy()
    for cells, sym in hits:
        col = COLORS.get(sym, (0, 0, 255))
        bs = [boxes[p] for p in cells]
        p1 = (bs[0][0] + bs[0][2] // 2, bs[0][1] + bs[0][3] // 2)
        p2 = (bs[-1][0] + bs[-1][2] // 2, bs[-1][1] + bs[-1][3] // 2)
        cv2.line(out, p1, p2, col, 10)
        for x, y, w, h in bs:
            cv2.rectangle(out, (x - 8, y - 8), (x + w + 8, y + h + 8), col, 5)
    return out
