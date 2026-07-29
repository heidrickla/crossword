"""Tests for the phone upload endpoint.

Skipped entirely when Flask is absent -- the web layer is an optional extra and
its absence must never fail the core suite.
"""
import base64
import io
from pathlib import Path

import pytest

flask = pytest.importorskip("flask", reason="web extra not installed")

from cowfinder import web  # noqa: E402  -- must follow the importorskip

PHOTO = Path(__file__).parent / "golden_photo.jpg"


@pytest.fixture()
def client():
    web.app.config["TESTING"] = True
    return web.app.test_client()


def test_page_offers_the_camera(client):
    """The camera path is the whole point: a plain file input would make the
    phone open the gallery instead of the camera."""
    html = client.get("/").get_data(as_text=True)
    assert 'capture="environment"' in html
    assert 'accept="image/*"' in html


def test_upload_returns_the_golden_answer(client):
    with open(PHOTO, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "golden_photo.jpg")}
        r = client.post("/solve", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    j = r.get_json()
    assert j["count"] == 31
    assert j["rotation"] == 180
    assert j["rows"] == 32 and j["cols"] == 20
    assert j["by_direction"] == {"→": 9, "←": 1, "↓": 6,
                                 "↘": 10, "↙": 5}
    # the annotated image must actually decode, not merely be present
    raw = base64.b64decode(j["annotated"])
    assert raw[:2] == b"\xff\xd8"  # JPEG SOI
    assert len(raw) < 4 * 1024 * 1024, "annotated image is too big to send to a phone"


def test_missing_photo_is_a_400(client):
    r = client.post("/solve", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "no photo" in r.get_json()["error"]


def test_unspellable_word_is_reported_not_zero(client):
    """The CLI's word validation must surface as an error, not '0 found'."""
    with open(PHOTO, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "p.jpg"), "word": "CAT"}
        r = client.post("/solve", data=data, content_type="multipart/form-data")
    assert r.status_code == 422
    assert "cannot produce" in r.get_json()["error"]


def test_blank_photo_explains_itself(client, tmp_path):
    import cv2
    import numpy as np
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((300, 300, 3), 255, np.uint8))
    with open(blank, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "blank.png")}
        r = client.post("/solve", data=data, content_type="multipart/form-data")
    assert r.status_code == 422
    assert "no glyphs" in r.get_json()["error"].lower()


@pytest.mark.parametrize("field,value", [("directions", "sideways"), ("rotate", "45")])
def test_bad_options_rejected(client, field, value):
    with open(PHOTO, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "p.jpg"), field: value}
        r = client.post("/solve", data=data, content_type="multipart/form-data")
    assert r.status_code == 400


def test_no_temp_files_left_behind(client, tmp_path, monkeypatch):
    """Every upload spools to disk; a leak would fill /tmp over a session."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    with open(PHOTO, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "p.jpg")}
        client.post("/solve", data=data, content_type="multipart/form-data")
    assert list(tmp_path.iterdir()) == []
