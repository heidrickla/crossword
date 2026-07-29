"""8-direction word search over a sparse grid, with '?'-wildcard reporting.

A word read one way and its reverse read the other over the same cells are
different letter sequences, so matching the ordered word per direction never
double-counts.
"""
from __future__ import annotations

DIRS = {
    (0, 1): "\u2192",  (0, -1): "\u2190",
    (1, 0): "\u2193",  (-1, 0): "\u2191",
    (1, 1): "\u2198",  (1, -1): "\u2199",
    (-1, 1): "\u2197", (-1, -1): "\u2196",
}
#: Both ways along a row. Named for what it means: these puzzles contain
#: backwards words, and an option called "horizontal" that quietly dropped the
#: leftward ones would under-count without saying so. The golden photo has a
#: leftward COW, so this is not hypothetical.
HORIZONTAL = {(0, 1): "\u2192", (0, -1): "\u2190"}

#: Kept so existing callers keep working; prefer HORIZONTAL.
HORIZONTAL_ONLY = {(0, 1): "\u2192"}

Hit = tuple[tuple[tuple[int, int], ...], str]  # (cells, dir symbol)


def find_word(
    grid: dict[tuple[int, int], str],
    word: str = "COW",
    dirs: dict | None = None,
) -> tuple[list[Hit], list[Hit]]:
    """Return (confirmed_hits, uncertain_hits).

    uncertain = trios that would spell the word if a '?' cell took the needed
    letter. Report these separately; resolve via classify.ascii_render or a
    human look, never silently include/exclude.
    """
    dirs = dirs or DIRS
    L = len(word)
    hits: list[Hit] = []
    uncertain: list[Hit] = []
    for (r, c) in grid:
        for (dr, dc), sym in dirs.items():
            cells = tuple((r + k * dr, c + k * dc) for k in range(L))
            if not all(p in grid for p in cells):
                continue
            s = "".join(grid[p] for p in cells)
            if s == word:
                hits.append((cells, sym))
            elif "?" in s and all(a == "?" or a == b for a, b in zip(s, word)):
                uncertain.append((cells, sym))
    return hits, uncertain
