"""cowfinder CLI.

    python -m cowfinder.cli photo.jpg [--word COW] [--directions all|horizontal]
                            [--rotate auto|0|90|180|270]
                            [--out annotated.png] [--strips strips.png]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Any, NamedTuple

import cv2
import numpy as np

from . import gridify, orient, search, verify
from .classify import LETTERS, ascii_render, classify
from .segment import binarize, find_glyphs

ROTATIONS = ("auto", "0", "90", "180", "270")


class Solved(NamedTuple):
    """Result of a solve.

    A NamedTuple rather than a bare tuple: callers used to index this
    positionally (``solved[4]`` for hits), so adding a field silently shifted
    every caller and every assertion. Names remove that trap while keeping
    positional access working, so existing tests and unpacking are unaffected.
    """

    bgr: np.ndarray
    th: np.ndarray
    grid: dict[tuple[int, int], str]
    boxes: dict[tuple[int, int], Any]
    hits: list
    uncertain: list
    rotation: int
    skew: float


def validate_word(word: str) -> str:
    """Reject words the classifier cannot possibly spell.

    The glyph classifier emits only C/D/O/W/M. Searching for 'CAT' can never
    match, and reporting '0 found' invites the reading 'the puzzle has none'
    when the truth is 'this tool cannot see an A'.
    """
    w = word.upper()
    if not w:
        raise SystemExit("--word must not be empty")
    bad = sorted(set(w) - LETTERS)
    if bad:
        raise SystemExit(
            "--word %r contains %s, which this classifier cannot produce.\n"
            "Recognised letters are %s (D is the backwards-C decoy, M the "
            "upside-down-W). No OCR is used, so other letters are not merely "
            "unreliable -- they are unrepresentable."
            % (word, ", ".join(repr(b) for b in bad), "/".join(sorted(LETTERS)))
        )
    return w


def solve(path: str, word: str, directions: str, rotate: str = "auto") -> Solved:
    word = validate_word(word)

    bgr = cv2.imread(path)
    if bgr is None:
        raise SystemExit(f"cannot read {path}")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Orientation is the single most consequential guess in the pipeline, so
    # allow it to be overridden. Auto-detection is a heuristic over a glyph
    # sample; without an escape hatch a misdetect leaves no way forward.
    deg = orient.best_rotation(gray) if rotate == "auto" else int(rotate)
    gray = orient.apply_rotation(gray, deg)
    bgr = orient.apply_rotation(bgr, deg)

    th = binarize(gray)
    boxes = find_glyphs(th)
    if not boxes:
        raise SystemExit(
            "no glyphs found in %s -- nothing to solve.\n"
            "Usually the photo is blank, cropped past the grid, or so unevenly "
            "lit that thresholding kept nothing." % path
        )
    cells = [(classify(th, b), b) for b in boxes]

    centers = np.array([(b[0] + b[2] / 2, b[1] + b[3] / 2) for _, b in cells])
    angle = gridify.deskew_angle(centers)
    rows = gridify.cluster_rows(cells, angle)
    grid_cells = gridify.assign_columns(rows)

    grid = {k: ch for k, (ch, _b) in grid_cells.items()}
    gboxes = {k: b for k, (_ch, b) in grid_cells.items()}
    if not grid:
        raise SystemExit(
            "%d glyphs were detected but none could be placed on a grid.\n"
            "Row clustering found no usable structure -- check the photo is of "
            "a grid and is not extremely skewed." % len(boxes)
        )

    dirs = search.HORIZONTAL_ONLY if directions == "horizontal" else search.DIRS
    hits, uncertain = search.find_word(grid, word, dirs)

    bad = verify.reverify(th, gboxes, hits, word)
    if bad:
        for (hit, s) in bad:
            print(f"VERIFY FAIL {hit} -> {s}", file=sys.stderr)
        raise SystemExit("independent re-verification failed; refusing to report")

    return Solved(bgr, th, grid, gboxes, hits, uncertain, deg, angle)


def _write(img, path: str, label: str) -> None:
    """Write an image and prove it landed.

    cv2.imwrite returns False rather than raising on an unwritable path or an
    unknown extension. Ignoring it printed a success line for a file that was
    never created, and exited 0 -- a false green.
    """
    if not cv2.imwrite(path, img):
        raise SystemExit(
            f"failed to write {label} to {path!r} -- check the directory exists, "
            "is writable, and the extension is one OpenCV encodes (.png/.jpg)"
        )
    print(f"{label} -> {path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cowfinder")
    ap.add_argument("photo")
    ap.add_argument("--word", default="COW")
    ap.add_argument("--directions", choices=["all", "horizontal"], default="all")
    ap.add_argument("--rotate", choices=ROTATIONS, default="auto",
                    help="override page-orientation detection (degrees clockwise)")
    ap.add_argument("--out", default=None, help="annotated image path")
    ap.add_argument("--strips", default=None, help="per-hit crop strip image path")
    a = ap.parse_args(argv)

    s = solve(a.photo, a.word, a.directions, a.rotate)
    word = a.word.upper()

    R = max(r for r, _ in s.grid) + 1
    C = max(c for _, c in s.grid) + 1
    print(f"rotation: {s.rotation} deg   row skew: {s.skew:.1f} deg   grid: {R}x{C}")
    for r in range(R):
        print(f"{r:3d} " + "".join(s.grid.get((r, c), ".") for c in range(C)))

    print(f"\n{word}: {len(s.hits)} found")
    for sym, n in sorted(Counter(sym for _, sym in s.hits).items()):
        print(f"  {sym} {n}")
    for cells, sym in sorted(s.hits):
        print(f"  {sym} {list(cells)}")

    if s.uncertain:
        print("\nUNCERTAIN (depend on '?' glyphs) - inspect before counting:")
        for cells, sym in s.uncertain:
            print(f"  {sym} {list(cells)}")
            for p in cells:
                if s.grid[p] == "?":
                    print(ascii_render(s.th, s.boxes[p]))
                    print()

    if a.out:
        _write(verify.annotate(s.bgr, s.boxes, s.hits), a.out, "annotated")
    if a.strips:
        _write(verify.crop_strips(s.bgr, s.boxes, s.hits), a.strips, "strips")


if __name__ == "__main__":
    main()
