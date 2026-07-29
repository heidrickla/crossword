"""All eight directions must actually find a word.

Coverage gap this closes: the golden photo contains no upward hits (SPEC says
"none upward"), so the golden test exercises only 5 of the 8 directions. Up,
up-right and up-left had never been proven to work by any test -- they were
believed to work because the direction table lists them.

These build grids directly, with no image, so they test the search alone.
"""
from collections import Counter

import pytest

from cowfinder import search

COW = "COW"


def _grid_with(word: str, start, step, size=7, filler="O"):
    """A size x size grid of filler with `word` written from `start` along `step`."""
    g = {(r, c): filler for r in range(size) for c in range(size)}
    r, c = start
    dr, dc = step
    for i, ch in enumerate(word):
        g[(r + i * dr, c + i * dc)] = ch
    return g


ALL_EIGHT = [
    ((0, 1), "→", (3, 2)),   # right
    ((0, -1), "←", (3, 4)),  # left
    ((1, 0), "↓", (2, 3)),   # down
    ((-1, 0), "↑", (4, 3)),  # up
    ((1, 1), "↘", (2, 2)),   # down-right
    ((1, -1), "↙", (2, 4)),  # down-left
    ((-1, 1), "↗", (4, 2)),  # up-right
    ((-1, -1), "↖", (4, 4)), # up-left
]


@pytest.mark.parametrize("step,sym,start", ALL_EIGHT)
def test_each_direction_is_found(step, sym, start):
    grid = _grid_with(COW, start, step)
    hits, _unc = search.find_word(grid, COW, search.DIRS)
    syms = [s for _cells, s in hits]
    assert sym in syms, f"{sym} was not found; got {syms}"


def test_the_direction_table_has_all_eight():
    assert len(search.DIRS) == 8
    assert set(search.DIRS.values()) == set("→←↓↑↘↙↗↖")


def test_a_word_and_its_reverse_are_not_double_counted():
    """COW read one way is WOC read the other, so the same three cells must
    yield exactly one COW -- not one per traversal."""
    grid = _grid_with(COW, (3, 2), (0, 1))
    hits, _ = search.find_word(grid, COW, search.DIRS)
    cow_cells = [tuple(sorted(cells)) for cells, _s in hits]
    assert len(cow_cells) == len(set(cow_cells)), "the same cells were counted twice"


def test_horizontal_means_both_ways():
    """'horizontal' previously meant rightward only, so a backwards COW on the
    same row was silently dropped -- the puzzles contain those."""
    grid = _grid_with(COW, (3, 1), (0, 1))          # a forward COW
    for i, ch in enumerate(COW):                     # and a backward one
        grid[(5, 5 - i)] = ch
    hits, _ = search.find_word(grid, COW, search.HORIZONTAL)
    syms = sorted(s for _c, s in hits)
    assert syms == ["←", "→"], f"expected both horizontal ways, got {syms}"


def test_diagonals_both_ways_on_one_grid():
    """The four diagonals, all present at once, must each be reported.

    One per corner heading inward. An earlier version of this test put all four
    near the middle of a 9x9 grid and they overwrote each other's letters --
    the test failed on its own layout, not on the search.
    """
    N = 12
    grid = {(r, c): "O" for r in range(N) for c in range(N)}
    corners = [
        ((0, 0), (1, 1), "↘"),
        ((0, N - 1), (1, -1), "↙"),
        ((N - 1, 0), (-1, 1), "↗"),
        ((N - 1, N - 1), (-1, -1), "↖"),
    ]
    for (r, c), (dr, dc), _sym in corners:
        for i, ch in enumerate(COW):
            grid[(r + i * dr, c + i * dc)] = ch

    hits, _ = search.find_word(grid, COW, search.DIRS)
    found = Counter(s for _c, s in hits)
    for _start, _step, sym in corners:
        assert found[sym] == 1, f"diagonal {sym}: expected 1, got {found[sym]} ({dict(found)})"
