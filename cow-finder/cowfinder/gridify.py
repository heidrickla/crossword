"""Row/column reconstruction under perspective tilt.

Failure modes this module exists to prevent (all observed in practice):
  * naive y-clustering merges adjacent rows / splits single rows under tilt
  * global x-clustering collapses or invents columns (perspective compresses
    spacing toward the far edge of the photo)

Strategy:
  * deskew rows by scanning tilt angles and maximizing histogram sharpness
  * repair merged clusters (2-3x modal glyph count) by re-splitting on raw y
  * assign columns by SORTED POSITION INDEX for rows with the modal count;
    align irregular rows against neighbors by x (short row -> clipped edge
    glyph; long row -> stray edge artifact with a large x gap: drop it)
"""
from __future__ import annotations

import math

import numpy as np

Box = tuple[int, int, int, int]
Cell = tuple[str, Box]  # (char, box)


def deskew_angle(centers: np.ndarray, lo: float = -8, hi: float = 8, step: float = 0.1) -> float:
    best = (-1.0, 0.0)
    for a in np.arange(lo, hi, step):
        yp = centers[:, 1] - centers[:, 0] * math.tan(math.radians(a))
        hist, _ = np.histogram(yp, bins=max(50, len(centers) // 4))
        score = float((hist.astype(np.float64) ** 2).sum())
        if score > best[0]:
            best = (score, float(a))
    return best[1]


def cluster_rows(items: list[Cell], angle: float, gap_frac: float = 0.55) -> list[list[Cell]]:
    """Cluster glyphs into rows using tilt-corrected y, then repair merges."""
    tan = math.tan(math.radians(angle))
    keyed = sorted(items, key=lambda it: (it[1][1] + it[1][3] / 2) - (it[1][0] + it[1][2] / 2) * tan)
    med_h = float(np.median([b[3] for _, b in items]))

    rows: list[list[Cell]] = []
    prev_y = None
    for it in keyed:
        yp = (it[1][1] + it[1][3] / 2) - (it[1][0] + it[1][2] / 2) * tan
        if prev_y is None or yp - prev_y > med_h * gap_frac:
            rows.append([])
        rows[-1].append(it)
        prev_y = yp

    # repair merged rows: split any cluster with >=1.6x modal size on raw y
    counts = [len(r) for r in rows]
    modal = int(np.median(counts))
    out: list[list[Cell]] = []
    for r in rows:
        if len(r) >= 1.6 * modal:
            out.extend(_split_merged(r, med_h))
        else:
            out.append(r)
    for r in out:
        r.sort(key=lambda it: it[1][0])
    return out


def _split_merged(row: list[Cell], med_h: float) -> list[list[Cell]]:
    order = sorted(row, key=lambda it: it[1][1] + it[1][3] / 2)
    subs: list[list[Cell]] = []
    means: list[float] = []
    for it in order:
        yc = it[1][1] + it[1][3] / 2
        if subs and abs(yc - means[-1]) < med_h * 0.8:
            subs[-1].append(it)
            means[-1] = float(np.mean([b[1] + b[3] / 2 for _, b in subs[-1]]))
        else:
            subs.append([it])
            means.append(yc)
    return subs


def assign_columns(rows: list[list[Cell]]) -> dict[tuple[int, int], Cell]:
    """Return sparse grid {(row, col): cell}. Position-index for modal rows;
    x-alignment against nearest modal neighbor for irregular rows."""
    counts = [len(r) for r in rows]
    modal = int(np.median(counts))
    grid: dict[tuple[int, int], Cell] = {}

    ref_by_row: dict[int, list[float]] = {
        ri: [b[0] + b[2] / 2 for _, b in r] for ri, r in enumerate(rows) if len(r) == modal
    }

    for ri, r in enumerate(rows):
        if len(r) == modal:
            for ci, cell in enumerate(r):
                grid[(ri, ci)] = cell
            continue
        ref = _nearest_ref(ref_by_row, ri)
        if ref is None:
            for ci, cell in enumerate(r):  # degenerate: no modal row anywhere
                grid[(ri, ci)] = cell
            continue
        used: set[int] = set()
        for cell in sorted(r, key=lambda it: it[1][0]):
            xc = cell[1][0] + cell[1][2] / 2
            ci = int(np.argmin([abs(xc - rx) for rx in ref]))
            if ci in used:
                continue  # stray edge artifact colliding with a real glyph
            # strays sit far from any reference column: drop them
            if abs(xc - ref[ci]) > 0.6 * _pitch(ref):
                continue
            used.add(ci)
            grid[(ri, ci)] = cell
    return grid


def _nearest_ref(refs: dict[int, list[float]], ri: int) -> list[float] | None:
    if not refs:
        return None
    key = min(refs, key=lambda k: abs(k - ri))
    return refs[key]


def _pitch(ref: list[float]) -> float:
    return float(np.median(np.diff(ref))) if len(ref) > 1 else 1e9
