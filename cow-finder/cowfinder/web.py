"""Phone front end: take or pick a photo, get the answer back.

Additive by design (AGENTS.md): the CLI and the golden path are untouched, and
Flask is an optional extra -- `pip install -e .[web]`. Importing this module is
the only thing that needs it.

Why a web page rather than an app: `<input type="file" accept="image/*"
capture="environment">` opens the camera directly on Android and falls back to
the gallery, with no install, no store, and no platform code.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import tempfile
import time
from collections import Counter

import cv2

from . import verify
from .cli import ROTATIONS, solve, solve_steps

try:
    from flask import Flask, g, jsonify, request
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise SystemExit(
        "the web UI needs Flask: pip install -e '.[web]'"
    ) from exc

# A modern phone camera is the thing uploading here: an S24 Ultra at full
# resolution produces files well past the 30MB this used to allow, and the
# rejection looked like "nothing happened" from the phone.
MAX_UPLOAD = 96 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

# Log every request. Without this the service logged only start/stop, so an
# upload that never arrived and an upload that failed silently were
# indistinguishable -- there was no way to tell whether the phone had reached
# the server at all.
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cowfinder.web")


@app.before_request
def _start_timer():
    g._t0 = time.monotonic()
    if request.path != "/":
        log.info(
            "-> %s %s from %s  content-length=%s",
            request.method, request.path, request.remote_addr,
            request.content_length,
        )


@app.after_request
def _log_result(resp):
    dt = (time.monotonic() - getattr(g, "_t0", time.monotonic())) * 1000
    log.info("<- %s %s %s  %.0fms", request.method, request.path, resp.status_code, dt)
    return resp


@app.errorhandler(413)
def _too_big(_e):
    """Flask aborts oversized uploads before the view runs, and its default
    response is HTML -- which the page could not parse, so the phone showed
    nothing at all."""
    log.warning("413 upload too large (limit %d bytes)", MAX_UPLOAD)
    return jsonify(
        error="that photo is larger than %d MB. Try your camera's smaller "
              "resolution setting." % (MAX_UPLOAD // (1024 * 1024))
    ), 413


@app.errorhandler(Exception)
def _unhandled(e):
    """Anything unexpected must still come back as JSON with a reason; an HTML
    500 page is unparseable by the client and surfaces as silence."""
    log.exception("unhandled error")
    return jsonify(error="%s: %s" % (type(e).__name__, e)), 500


PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>COW finder</title>
<style>
  :root {
    --bg:#101418; --card:#182028; --line:#2b3742; --text:#e8eef3;
    --dim:#8fa3b0; --accent:#ffcf4d; --ok:#5fd08a; --warn:#ff9a5c;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
  main{max-width:44rem;margin:0 auto;padding:1.25rem}
  h1{font-size:1.35rem;margin:0 0 .25rem;letter-spacing:-.01em}
  .sub{color:var(--dim);font-size:.9rem;margin:0 0 1.25rem}
  .pick{display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1rem}
  label.btn{flex:1 1 12rem;text-align:center;background:var(--accent);color:#12181d;
       font-weight:650;padding:1rem;border-radius:10px;cursor:pointer}
  label.btn.alt{background:none;color:var(--text);border:1px solid var(--line)}
  input[type=file]{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
  .opts{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap;
        color:var(--dim);font-size:.85rem;margin-bottom:1rem}
  select,input[type=text]{background:var(--card);color:var(--text);
        border:1px solid var(--line);border-radius:8px;padding:.45rem .6rem;font:inherit}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
        padding:1rem;margin-bottom:1rem}
  .big{font-size:2.6rem;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
  .dirs{display:flex;gap:1rem;flex-wrap:wrap;margin-top:.6rem;
        font-variant-numeric:tabular-nums;color:var(--dim)}
  .dirs b{color:var(--text)}
  img{width:100%;border-radius:10px;display:block}
  /* The canvas must sit exactly over the photo, so both are sized by the same
     wrapper rather than each finding its own dimensions. */
  .shot{position:relative;line-height:0}
  .shot canvas{position:absolute;inset:0;width:100%;height:100%}
  .counter{position:sticky;top:0;z-index:2}
  .stagewrap{padding:.5rem}
  pre{overflow-x:auto;font:12px/1.35 ui-monospace,Menlo,Consolas,monospace;
      color:var(--dim);margin:0}
  .warn{color:var(--warn)}
  .err{color:#ff7a7a}
  .hide{display:none}
  .spin{color:var(--dim)}
</style>
<main>
  <h1>COW finder</h1>
  <p class="sub">Photograph a word-search grid. It finds every COW and shows you where.</p>

  <div class="pick">
    <label class="btn">Take photo
      <input type="file" id="cam" accept="image/*" capture="environment">
    </label>
    <label class="btn alt">Choose photo
      <input type="file" id="lib" accept="image/*">
    </label>
  </div>

  <div class="opts">
    <span>Word <input type="text" id="word" value="COW" size="5" autocapitalize="characters"></span>
    <span>Directions
      <select id="dirs"><option value="all">All 8 ways</option><option value="horizontal">Along rows, both ways</option><option value="forward">Rightward only</option></select>
    </span>
    <span>Rotation
      <select id="rot"><option>auto</option><option>0</option><option>90</option><option>180</option><option>270</option></select>
    </span>
  </div>

  <p id="status" class="spin hide"></p>

  <div id="live" class="hide">
    <div class="card counter">
      <div class="big"><span id="n">0</span>
        <span style="font-size:1rem;font-weight:400;color:var(--dim)">found</span></div>
      <div class="dirs" id="bydir"></div>
      <p id="unc" class="warn hide" style="margin:.75rem 0 0;font-size:.9rem"></p>
    </div>
    <div class="card stagewrap">
      <!-- the photo, with the overlay canvas sitting exactly on top of it -->
      <div class="shot">
        <img id="shot" alt="The photo you sent">
        <canvas id="ov"></canvas>
      </div>
    </div>
    <div class="card hide" id="gridcard"><pre id="grid"></pre></div>
  </div>
</main>
<script>
(function () {
  "use strict";
  // Everything lives in an IIFE. A top-level `var status = <element>` collided
  // with window.status -- a legacy DOM property that only holds strings -- so
  // the element was coerced away and send() threw on its first line, before
  // the upload. The picker opened, a photo was chosen, and nothing happened.
  var statusEl = document.getElementById("status");
  var liveEl = document.getElementById("live");
  var shot = document.getElementById("shot");
  var ov = document.getElementById("ov");
  var nEl = document.getElementById("n");
  var byDirEl = document.getElementById("bydir");
  var uncEl = document.getElementById("unc");
  var gridCard = document.getElementById("gridcard");
  var gridEl = document.getElementById("grid");

  // One colour per direction, so a glance at the overlay tells you which way a
  // word runs without reading any labels.
  var COLOR = {
    "→": "#ffcf4d", "←": "#ff9a5c",
    "↓": "#5fd08a", "↑": "#4dd4e8",
    "↘": "#7aa7ff", "↙": "#c58cff",
    "↗": "#ff7ab8", "↖": "#8fe36b"
  };

  function fail(msg) {
    statusEl.className = "err";
    statusEl.classList.remove("hide");
    statusEl.textContent = msg;
  }

  function say(msg) {
    statusEl.className = "spin";
    statusEl.classList.remove("hide");
    statusEl.textContent = msg;
  }

  // The canvas is sized to the IMAGE's pixels, not the screen's, so hit boxes
  // arrive in the same coordinate space the server measured them in. CSS then
  // scales both together and the overlay can never drift from the photo.
  function fitCanvas(w, h) {
    ov.width = w;
    ov.height = h;
    return ov.getContext("2d");
  }

  function drawHit(ctx, hit) {
    var col = COLOR[hit.dir] || "#ffffff";
    var b, i, cx = [], cy = [];
    ctx.lineWidth = Math.max(2, ov.width / 400);
    ctx.strokeStyle = col;
    ctx.fillStyle = col;

    for (i = 0; i < hit.boxes.length; i++) {
      b = hit.boxes[i];
      ctx.globalAlpha = 0.25;
      ctx.fillRect(b[0], b[1], b[2], b[3]);
      ctx.globalAlpha = 1;
      ctx.strokeRect(b[0], b[1], b[2], b[3]);
      cx.push(b[0] + b[2] / 2);
      cy.push(b[1] + b[3] / 2);
    }
    // a line through the word makes the direction readable at a glance
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    ctx.moveTo(cx[0], cy[0]);
    ctx.lineTo(cx[cx.length - 1], cy[cy.length - 1]);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function send(file) {
    if (!file) return;
    var ctx = null;

    // Show their photo immediately, before a byte is uploaded. The solve can
    // take seconds on a large image and a blank screen reads as broken.
    var localURL = URL.createObjectURL(file);
    shot.src = localURL;
    ov.width = ov.height = 0;
    liveEl.classList.remove("hide");
    gridCard.classList.add("hide");
    nEl.textContent = "0";
    byDirEl.innerHTML = "";
    uncEl.classList.add("hide");
    say("Uploading " + (Math.round(file.size / 1048576 * 10) / 10) + " MB…");

    var fd = new FormData();
    fd.append("photo", file);
    fd.append("word", document.getElementById("word").value || "COW");
    fd.append("directions", document.getElementById("dirs").value);
    fd.append("rotate", document.getElementById("rot").value);

    var counts = {};
    var found = 0;

    fetch("solve/stream", { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok || !r.body) {
          return r.text().then(function (t) {
            var j = null;
            try { j = JSON.parse(t); } catch (_) {}
            throw new Error((j && j.error) || ("server returned " + r.status));
          });
        }
        var reader = r.body.getReader();
        var dec = new TextDecoder();
        var buf = "";

        function pump() {
          return reader.read().then(function (res) {
            if (res.done) { return; }
            buf += dec.decode(res.value, { stream: true });
            var lines = buf.split("\n");
            buf = lines.pop();                 // keep the partial line
            lines.forEach(function (line) {
              if (!line.trim()) return;
              var ev;
              try { ev = JSON.parse(line); } catch (_) { return; }
              handle(ev);
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (e) { fail(e.message || String(e)); })
      .then(function () { URL.revokeObjectURL(localURL); });

    function handle(ev) {
      if (ev.type === "stage") {
        say(ev.text + "…");
      } else if (ev.type === "error") {
        fail(ev.error);
      } else if (ev.type === "image") {
        // swap the local preview for the upright image the server actually
        // solved, so the overlay lines up with what was measured
        shot.src = "data:image/jpeg;base64," + ev.jpeg;
        ctx = fitCanvas(ev.width, ev.height);
        say("Marking hits…");
      } else if (ev.type === "hit") {
        found = ev.n;
        nEl.textContent = found;
        counts[ev.dir] = (counts[ev.dir] || 0) + 1;
        byDirEl.innerHTML = Object.keys(counts).map(function (k) {
          return "<span style=\"color:" + (COLOR[k] || "#fff") + "\">" + k
               + " <b>" + counts[k] + "</b></span>";
        }).join("");
        if (ctx) drawHit(ctx, ev);
      } else if (ev.type === "grid") {
        gridEl.textContent = "grid " + ev.rows + "×" + ev.cols
                           + ", skew " + ev.skew + "°";
      } else if (ev.type === "done") {
        nEl.textContent = ev.count;
        if (ev.uncertain) {
          uncEl.textContent = ev.uncertain + " more depend on a glyph that could not"
                            + " be read — not counted above.";
          uncEl.classList.remove("hide");
        }
        gridEl.textContent = "rotation " + ev.rotation + "°, "
                           + gridEl.textContent;
        gridCard.classList.remove("hide");
        statusEl.classList.add("hide");
      }
    }
  }

  // A phone has no console, so a silent script error is indistinguishable from
  // a dead app. Put it on the screen.
  window.addEventListener("error", function (ev) {
    fail("page error: " + (ev.message || "unknown"));
  });

  document.getElementById("cam").addEventListener("change", function () { send(this.files[0]); });
  document.getElementById("lib").addEventListener("change", function () { send(this.files[0]); });
})();
</script>
"""


@app.get("/")
def index():
    """The page, explicitly uncacheable.

    Served with no Cache-Control, ETag or Last-Modified, a browser has no
    validator and falls back to heuristic caching -- so a phone kept showing a
    page from before the deploy and every fix looked like it had done nothing.
    The HTML is a few KB and carries the app's only JavaScript; there is no
    reason to cache it and every reason not to.
    """
    resp = app.make_response(PAGE)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.post("/solve")
def solve_upload():
    f = request.files.get("photo")
    if f is None or not f.filename:
        return jsonify(error="no photo was sent"), 400

    word = (request.form.get("word") or "COW").strip()
    directions = request.form.get("directions") or "all"
    rotate = request.form.get("rotate") or "auto"
    if directions not in ("all", "horizontal", "forward"):
        return jsonify(error="directions must be 'all', 'horizontal' or 'forward'"), 400
    if rotate not in ROTATIONS:
        return jsonify(error="rotate must be one of %s" % ", ".join(ROTATIONS)), 400

    # solve() takes a path: phone photos are large and OpenCV decodes from disk
    # perfectly well, so spooling to a temp file beats holding two copies in RAM.
    suffix = os.path.splitext(f.filename)[1][:8] or ".jpg"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        f.save(tmp)
        tmp.close()
        try:
            s = solve(tmp.name, word, directions, rotate)
        except SystemExit as exc:
            # every deliberate failure in the pipeline raises SystemExit with a
            # human sentence; surface that rather than a 500
            return jsonify(error=str(exc)), 422
    finally:
        os.unlink(tmp.name)

    rows = max(r for r, _ in s.grid) + 1
    cols = max(c for _, c in s.grid) + 1
    ascii_grid = "\n".join(
        "%3d %s" % (r, "".join(s.grid.get((r, c), ".") for c in range(cols)))
        for r in range(rows)
    )

    # JPEG, not PNG: the annotated PNG of a 4000px photo is ~17MB, which is a
    # miserable thing to push down a phone connection.
    img = verify.annotate(s.bgr, s.boxes, s.hits)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return jsonify(error="could not encode the annotated image"), 500

    return jsonify(
        count=len(s.hits),
        by_direction=dict(sorted(Counter(sym for _, sym in s.hits).items())),
        uncertain=len(s.uncertain),
        rotation=s.rotation,
        skew=round(float(s.skew), 1),
        rows=rows,
        cols=cols,
        grid=ascii_grid,
        annotated=base64.b64encode(buf.tobytes()).decode("ascii"),
    )


MAX_PREVIEW_W = 1400  # a phone screen; full 4000px would be pointless bytes


def _encode_preview(bgr):
    """Upright image, scaled to something a phone should receive, plus the scale."""
    h, w = bgr.shape[:2]
    scale = min(1.0, MAX_PREVIEW_W / float(w))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    if not ok:
        raise RuntimeError("could not encode the preview")
    return base64.b64encode(buf.tobytes()).decode("ascii"), scale, bgr.shape[1], bgr.shape[0]


@app.post("/solve/stream")
def solve_stream():
    """Newline-delimited JSON, one object per event, flushed as it happens.

    The overlay is drawn on the CLIENT from geometry rather than baked into a
    server-side image. Two reasons: the count can tick up as hits appear, and
    the boxes stay in the upright image's own coordinate space -- SPEC's
    coordinate cheat sheet exists because transforming them by hand is where
    the bugs lived.
    """
    f = request.files.get("photo")
    if f is None or not f.filename:
        return jsonify(error="no photo was sent"), 400
    word = (request.form.get("word") or "COW").strip()
    directions = request.form.get("directions") or "all"
    rotate = request.form.get("rotate") or "auto"
    if directions not in ("all", "horizontal", "forward"):
        return jsonify(error="directions must be 'all', 'horizontal' or 'forward'"), 400
    if rotate not in ROTATIONS:
        return jsonify(error="rotate must be one of %s" % ", ".join(ROTATIONS)), 400

    suffix = os.path.splitext(f.filename)[1][:8] or ".jpg"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.save(tmp)
    tmp.close()

    def events():
        try:
            solved = None
            for kind, payload in solve_steps(tmp.name, word, directions, rotate):
                if kind == "done":
                    solved = payload
                    break
                yield json.dumps({"type": kind, **payload}) + "\n"

            preview, scale, pw, ph = _encode_preview(solved.bgr)
            yield json.dumps({"type": "image", "jpeg": preview,
                              "width": pw, "height": ph}) + "\n"

            # One event per hit so the counter climbs as they are drawn.
            for i, (cells, sym) in enumerate(sorted(solved.hits), 1):
                boxes = []
                for p in cells:
                    x, y, w, h = solved.boxes[p]
                    boxes.append([round(x * scale), round(y * scale),
                                  round(w * scale), round(h * scale)])
                yield json.dumps({"type": "hit", "n": i, "dir": sym,
                                  "cells": [list(p) for p in cells],
                                  "boxes": boxes}) + "\n"

            yield json.dumps({
                "type": "done",
                "count": len(solved.hits),
                "uncertain": len(solved.uncertain),
                "by_direction": dict(sorted(Counter(s for _c, s in solved.hits).items())),
                "rotation": solved.rotation,
                "skew": round(float(solved.skew), 1),
            }) + "\n"
        except SystemExit as exc:
            # Headers are already sent, so the status code cannot change --
            # the error has to travel as an event or it vanishes.
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("stream failed")
            yield json.dumps({"type": "error",
                              "error": "%s: %s" % (type(exc).__name__, exc)}) + "\n"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    return app.response_class(events(), mimetype="application/x-ndjson",
                              headers={"X-Accel-Buffering": "no",
                               "Cache-Control": "no-store"})


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="cowfinder-web")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8420)
    a = ap.parse_args()
    try:
        from waitress import serve as _serve
        print(f"cowfinder-web on http://{a.host}:{a.port}")
        _serve(app, host=a.host, port=a.port)
    except ModuleNotFoundError:
        app.run(host=a.host, port=a.port)


if __name__ == "__main__":
    main()
