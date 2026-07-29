"""5-class geometric glyph classifier: C, D (=backwards C), O, W, M, ? .

Order matters:
  1. hole test        -> O
  2. radial variance  -> ring (C/D) vs zigzag (W/M)
  3. gap direction    -> C vs D
  4. contact runs     -> W vs M (tie -> '?')

Empirical constants from a 4000px handheld photo: ring rel_std < 0.30,
zigzag rel_std ~ 0.38-0.40. '?' is a first-class result; never guess.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

RING_REL_STD = 0.30
HOLE_AREA_FRAC = 0.05

#: Every letter this classifier can emit. '?' is the explicit unknown and is
#: never part of a searchable word. Callers validate requested words against
#: LETTERS -- a word containing anything else cannot match by construction, and
#: silently returning "0 found" reads as "not present" rather than "impossible".
LETTERS = frozenset("CDOWM")
CLASSES = frozenset(LETTERS | {"?"})


def classify(th: np.ndarray, box: tuple[int, int, int, int]) -> str:
    x, y, w, h = box
    roi = th[y : y + h, x : x + w]
    if roi.size == 0 or roi.max() == 0:
        return "?"

    # 1. O: closed loop -> child contour with meaningful area
    cnts, hier = cv2.findContours(roi, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is not None:
        for i, hh in enumerate(hier[0]):
            if hh[3] != -1 and cv2.contourArea(cnts[i]) > w * h * HOLE_AREA_FRAC:
                return "O"

    ys, xs = np.nonzero(roi)
    cx, cy = xs.mean(), ys.mean()
    r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)

    if r.std() / r.mean() < RING_REL_STD:
        # 2/3. open ring: find the angular gap direction
        ang = np.degrees(np.arctan2(ys - cy, xs - cx))
        hist, _ = np.histogram(ang, bins=36, range=(-180, 180))
        centers = np.arange(-175, 180, 10)
        empty = centers[hist == 0]
        if len(empty) == 0:
            return "O"
        rad = np.radians(empty)
        gap = math.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean()))
        return "C" if -90 < gap < 90 else "D"

    # 4. zigzag: W touches top edge 3x / bottom 2x; M the reverse
    strip = max(2, h // 10)
    top_runs = _runs(roi[:strip, :].sum(axis=0) > 0)
    bot_runs = _runs(roi[-strip:, :].sum(axis=0) > 0)
    if top_runs > bot_runs:
        return "W"
    if bot_runs > top_runs:
        return "M"
    return "?"


def _runs(b: np.ndarray) -> int:
    count, prev = 0, False
    for v in b:
        if v and not prev:
            count += 1
        prev = bool(v)
    return count


def ascii_render(th: np.ndarray, box: tuple[int, int, int, int], w: int = 30, h: int = 15) -> str:
    """Small ASCII render of a glyph; effective for eyeballing clipped or
    ambiguous glyphs (a straight vertical right edge = M, diagonal = W)."""
    x, y, bw, bh = box
    roi = th[y : y + bh, x : x + bw]
    small = cv2.resize(roi, (w, h), interpolation=cv2.INTER_AREA)
    return "\n".join("".join("#" if v > 60 else " " for v in row) for row in small)
