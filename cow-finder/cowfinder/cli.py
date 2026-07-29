"""cowfinder CLI.

    python -m cowfinder.cli photo.jpg [--word COW] [--directions all|horizontal]
                            [--out annotated.png] [--strips strips.png]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import cv2
import numpy as np

from . import gridify, orient, search, verify
from .classify import ascii_render, classify
from .segment import binarize, find_glyphs


def solve(path: str, word: str, directions: str):
    bgr = cv2.imread(path)
    if bgr is None:
        raise SystemExit(f"cannot read {path}")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    deg = orient.best_rotation(gray)
    gray = orient.apply_rotation(gray, deg)
    bgr = orient.apply_rotation(bgr, deg)

    th = binarize(gray)
    boxes = find_glyphs(th)
    cells = [(classify(th, b), b) for b in boxes]

    centers = np.array([(b[0] + b[2] / 2, b[1] + b[3] / 2) for _, b in cells])
    angle = gridify.deskew_angle(centers)
    rows = gridify.cluster_rows(cells, angle)
    grid_cells = gridify.assign_columns(rows)

    grid = {k: ch for k, (ch, _b) in grid_cells.items()}
    gboxes = {k: b for k, (_ch, b) in grid_cells.items()}

    dirs = search.HORIZONTAL_ONLY if directions == "horizontal" else search.DIRS
    hits, uncertain = search.find_word(grid, word, dirs)

    bad = verify.reverify(th, gboxes, hits, word)
    if bad:
        for (hit, s) in bad:
            print(f"VERIFY FAIL {hit} -> {s}", file=sys.stderr)
        raise SystemExit("independent re-verification failed; refusing to report")

    return bgr, th, grid, gboxes, hits, uncertain, deg, angle


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cowfinder")
    ap.add_argument("photo")
    ap.add_argument("--word", default="COW")
    ap.add_argument("--directions", choices=["all", "horizontal"], default="all")
    ap.add_argument("--out", default=None, help="annotated image path")
    ap.add_argument("--strips", default=None, help="per-hit crop strip image path")
    a = ap.parse_args(argv)

    bgr, th, grid, gboxes, hits, uncertain, deg, angle = solve(a.photo, a.word, a.directions)

    R = max(r for r, _ in grid) + 1
    C = max(c for _, c in grid) + 1
    print(f"rotation: {deg} deg   row skew: {angle:.1f} deg   grid: {R}x{C}")
    for r in range(R):
        print(f"{r:3d} " + "".join(grid.get((r, c), ".") for c in range(C)))

    print(f"\n{a.word}: {len(hits)} found")
    for sym, n in sorted(Counter(s for _, s in hits).items()):
        print(f"  {sym} {n}")
    for cells, sym in sorted(hits):
        print(f"  {sym} {list(cells)}")

    if uncertain:
        print(f"\nUNCERTAIN (depend on '?' glyphs) — inspect before counting:")
        for cells, sym in uncertain:
            print(f"  {sym} {list(cells)}")
            for p in cells:
                if grid[p] == "?":
                    print(ascii_render(th, gboxes[p]))
                    print()

    if a.out:
        cv2.imwrite(a.out, verify.annotate(bgr, gboxes, hits))
        print(f"annotated -> {a.out}")
    if a.strips:
        cv2.imwrite(a.strips, verify.crop_strips(bgr, gboxes, hits))
        print(f"strips -> {a.strips}")


if __name__ == "__main__":
    main()
