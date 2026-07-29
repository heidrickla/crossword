"""Golden regression: the reference photo yields exactly 31 COWs on a 32x20
grid (9 right, 1 left, 6 down, 10 down-right, 5 down-left, none upward), and
horizontal hits on the 2-D grid match hits found on per-row strings (the
column-alignment canary)."""
from collections import Counter
from pathlib import Path

import pytest

from cowfinder.cli import solve
from cowfinder import search

PHOTO = Path(__file__).parent / "golden_photo.jpg"


@pytest.fixture(scope="module")
def solved():
    return solve(str(PHOTO), "COW", "all")


def test_grid_shape(solved):
    _bgr, _th, grid, _boxes, _hits, _unc, deg, _angle = solved
    assert deg == 180
    assert max(r for r, _ in grid) + 1 == 32
    assert max(c for _, c in grid) + 1 == 20


def test_counts(solved):
    hits = solved[4]
    assert len(hits) == 31
    by_dir = Counter(sym for _, sym in hits)
    assert by_dir == {"\u2192": 9, "\u2190": 1, "\u2193": 6, "\u2198": 10, "\u2199": 5}


def test_column_alignment_canary(solved):
    """Horizontal hits from row strings must equal horizontal hits from grid."""
    grid = solved[2]
    hits = solved[4]
    grid_h = {cells for cells, sym in hits if sym == "\u2192"}

    R = max(r for r, _ in grid) + 1
    C = max(c for _, c in grid) + 1
    string_h = set()
    for r in range(R):
        s = "".join(grid.get((r, c), ".") for c in range(C))
        start = 0
        while (j := s.find("COW", start)) >= 0:
            string_h.add(((r, j), (r, j + 1), (r, j + 2)))
            start = j + 1
    assert grid_h == string_h


def test_no_verify_failures(solved):
    # solve() raises on re-verification failure; reaching here means it passed
    assert True
