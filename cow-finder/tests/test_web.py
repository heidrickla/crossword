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


@pytest.mark.parametrize("name", ["status", "name", "length", "top", "self",
                                  "parent", "origin", "closed", "history"])
def test_no_top_level_var_shadows_a_window_property(client, name):
    """`var status = <element>` at global scope silently broke the whole page.

    window.status is a legacy DOM property that only holds strings, so the
    element was coerced away and the handler threw before uploading anything --
    the phone showed nothing at all, with no server-side trace. These names are
    all window properties that behave the same way.
    """
    import re
    html = client.get("/").get_data(as_text=True)
    pattern = r"^\s*(?:var|let|const)\s+%s\s*=" % re.escape(name)
    assert not re.search(pattern, html, re.M), (
        f"'{name}' is declared at what may be global scope and shadows "
        f"window.{name}"
    )


def test_script_is_wrapped_so_declarations_stay_local(client):
    """An IIFE is what makes the check above structural rather than a
    name-by-name game of whack-a-mole."""
    html = client.get("/").get_data(as_text=True)
    assert "(function () {" in html and '"use strict"' in html


def test_errors_surface_on_the_page(client):
    """A phone has no console: a failure that is not rendered is silence."""
    html = client.get("/").get_data(as_text=True)
    assert 'window.addEventListener("error"' in html
    assert "JSON.parse" in html, "a non-JSON error body must not throw a parse error"


def test_oversized_upload_returns_json_not_html(client):
    """Flask's default 413 is an HTML page, which the client cannot parse --
    it surfaced as nothing happening."""
    big = b"x" * (web.MAX_UPLOAD + 1024)
    r = client.post("/solve", data={"photo": (io.BytesIO(big), "big.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 413
    assert r.is_json and "larger than" in r.get_json()["error"]


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


# --- the streaming endpoint -------------------------------------------------

def _stream(client, **form):
    with open(PHOTO, "rb") as fh:
        data = {"photo": (io.BytesIO(fh.read()), "golden_photo.jpg")}
        data.update(form)
        r = client.post("/solve/stream", data=data,
                        content_type="multipart/form-data")
    assert r.status_code == 200
    import json as _json
    return [_json.loads(l) for l in r.get_data(as_text=True).splitlines() if l.strip()]


def test_stream_reports_progress_before_the_answer(client):
    """The point of streaming is that something arrives while the work happens;
    a single 'done' at the end would be the old behaviour with extra machinery."""
    evs = _stream(client)
    kinds = [e["type"] for e in evs]
    assert kinds.count("stage") >= 4, kinds
    assert kinds.index("stage") < kinds.index("done")
    steps = [e["step"] for e in evs if e["type"] == "stage"]
    for expected in ("reading", "orienting", "segmenting", "classifying",
                     "gridding", "searching", "verifying"):
        assert expected in steps, f"{expected} missing from {steps}"


def test_stream_emits_one_event_per_hit_then_done(client):
    evs = _stream(client)
    hits = [e for e in evs if e["type"] == "hit"]
    done = [e for e in evs if e["type"] == "done"][0]
    assert len(hits) == 31 == done["count"]
    # the counter on the page is driven by n; it must climb 1..31 in order
    assert [h["n"] for h in hits] == list(range(1, 32))
    assert done["rotation"] == 180


def test_hits_arrive_before_done(client):
    evs = _stream(client)
    kinds = [e["type"] for e in evs]
    assert kinds.index("hit") < kinds.index("done")
    assert kinds.index("image") < kinds.index("hit"), \
        "the canvas must be sized before any hit is drawn on it"


def test_hit_boxes_land_inside_the_image(client):
    """Boxes are scaled to the preview; one outside its bounds means the
    overlay would be drawn in the wrong place -- SPEC's coordinate trap."""
    evs = _stream(client)
    img = [e for e in evs if e["type"] == "image"][0]
    assert img["width"] <= web.MAX_PREVIEW_W
    for h in [e for e in evs if e["type"] == "hit"]:
        assert len(h["boxes"]) == 3
        for x, y, w, h_ in h["boxes"]:
            assert 0 <= x and 0 <= y, (x, y)
            assert x + w <= img["width"] + 2, (x, w, img["width"])
            assert y + h_ <= img["height"] + 2, (y, h_, img["height"])


def test_stream_reports_failures_as_events(client, tmp_path):
    """Headers are already sent, so a failure cannot change the status code --
    it has to arrive as an event or the page just stops."""
    import cv2
    import numpy as np
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((300, 300, 3), 255, np.uint8))
    with open(blank, "rb") as fh:
        r = client.post("/solve/stream",
                        data={"photo": (io.BytesIO(fh.read()), "blank.png")},
                        content_type="multipart/form-data")
    assert r.status_code == 200          # the stream itself succeeded
    import json as _json
    evs = [_json.loads(l) for l in r.get_data(as_text=True).splitlines() if l.strip()]
    err = [e for e in evs if e["type"] == "error"]
    assert err and "no glyphs" in err[0]["error"].lower()


def test_stream_and_plain_endpoint_agree(client):
    """Two endpoints, one pipeline: if these ever disagree the refactor leaked."""
    evs = _stream(client)
    done = [e for e in evs if e["type"] == "done"][0]
    with open(PHOTO, "rb") as fh:
        plain = client.post("/solve",
                            data={"photo": (io.BytesIO(fh.read()), "p.jpg")},
                            content_type="multipart/form-data").get_json()
    assert done["count"] == plain["count"]
    assert done["by_direction"] == plain["by_direction"]
    assert done["rotation"] == plain["rotation"]


def test_page_draws_its_own_overlay(client):
    html = client.get("/").get_data(as_text=True)
    assert "solve/stream" in html
    assert "getReader" in html, "the page must consume the stream incrementally"
    assert "createObjectURL" in html, "the photo should appear before the upload finishes"


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
