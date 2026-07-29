"""Regression tests for the CLI's failure modes.

Each of these failed before the corresponding fix:
  * an unwritable --out printed success and exited 0
  * --word CAT returned "0 found", indistinguishable from "none present"
  * a photo with no glyphs died in max() on an empty sequence
  * solve() returned a bare 8-tuple, so callers indexed it positionally
  * there was no way to override a mis-detected page rotation
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from cowfinder import cli
from cowfinder.classify import LETTERS

PHOTO = Path(__file__).parent / "golden_photo.jpg"


# --- --word must reject letters the classifier cannot emit -------------------

@pytest.mark.parametrize("word", ["CAT", "cow!", "ABC", ""])
def test_unspellable_words_fail_loudly(word):
    with pytest.raises(SystemExit) as e:
        cli.validate_word(word)
    assert "must not be empty" in str(e.value) or "cannot produce" in str(e.value)


@pytest.mark.parametrize("word", ["COW", "cow", "MOO", "DOC", "WOW"])
def test_words_within_the_alphabet_are_accepted(word):
    assert cli.validate_word(word) == word.upper()
    assert set(cli.validate_word(word)) <= LETTERS


def test_validation_names_the_offending_letters():
    """A rejection that does not say WHICH letter is unusable is a dead end."""
    with pytest.raises(SystemExit) as e:
        cli.validate_word("CAT")
    msg = str(e.value)
    assert "'A'" in msg and "'T'" in msg
    assert "'C'" not in msg  # C is fine; do not blame it


# --- a photo with nothing in it must explain itself --------------------------

def test_blank_image_reports_instead_of_crashing(tmp_path):
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((300, 300, 3), 255, np.uint8))
    with pytest.raises(SystemExit) as e:
        cli.solve(str(blank), "COW", "all")
    # the point is a sentence, not a ValueError from max() on an empty sequence
    assert "no glyphs" in str(e.value).lower()


def test_missing_file_still_reports(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.solve(str(tmp_path / "nope.jpg"), "COW", "all")
    assert "cannot read" in str(e.value)


# --- the result is named, and still indexable --------------------------------

@pytest.fixture(scope="module")
def solved():
    return cli.solve(str(PHOTO), "COW", "all")


def test_result_fields_are_named(solved):
    assert solved.rotation == 180
    assert len(solved.hits) == 31
    assert isinstance(solved.grid, dict)


def test_positional_access_still_works(solved):
    """Existing callers index this tuple; the NamedTuple must not break them."""
    assert solved[4] is solved.hits
    assert solved[2] is solved.grid
    assert solved[6] == solved.rotation
    assert len(solved) == 8


# --- rotation override -------------------------------------------------------

def test_rotate_override_is_honoured(solved):
    forced = cli.solve(str(PHOTO), "COW", "all", rotate="0")
    assert forced.rotation == 0
    # 0 deg is the wrong way up for this photo, so the auto-detected 180 must
    # do strictly better -- otherwise auto-detection is not earning its place.
    assert len(forced.hits) < len(solved.hits)


# --- a failed write must not report success ----------------------------------

def test_unwritable_out_path_fails(tmp_path, capsys):
    bad = tmp_path / "no_such_dir" / "x.png"
    with pytest.raises(SystemExit) as e:
        cli.main([str(PHOTO), "--out", str(bad)])
    assert "failed to write" in str(e.value)
    assert not bad.exists()


def test_successful_write_is_reported(tmp_path, capsys):
    out = tmp_path / "annotated.png"
    cli.main([str(PHOTO), "--out", str(out)])
    assert out.exists() and out.stat().st_size > 0
    assert "annotated ->" in capsys.readouterr().out
