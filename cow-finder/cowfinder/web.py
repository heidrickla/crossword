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
import os
import tempfile
from collections import Counter

import cv2

from . import verify
from .cli import ROTATIONS, solve

try:
    from flask import Flask, jsonify, request
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise SystemExit(
        "the web UI needs Flask: pip install -e '.[web]'"
    ) from exc

# Phone photos run 2-8MB; 30 is generous without inviting an accidental DoS
# from a device that decides to upload a burst.
MAX_UPLOAD = 30 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD


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
      <select id="dirs"><option value="all">All 8</option><option value="horizontal">Rightward only</option></select>
    </span>
    <span>Rotation
      <select id="rot"><option>auto</option><option>0</option><option>90</option><option>180</option><option>270</option></select>
    </span>
  </div>

  <p id="status" class="spin hide"></p>
  <div id="out" class="hide">
    <div class="card">
      <div class="big"><span id="n">0</span> <span style="font-size:1rem;font-weight:400;color:var(--dim)">found</span></div>
      <div class="dirs" id="bydir"></div>
      <p id="unc" class="warn hide" style="margin:.75rem 0 0;font-size:.9rem"></p>
    </div>
    <div class="card"><img id="ann" alt="Annotated grid with each hit marked"></div>
    <div class="card"><pre id="grid"></pre></div>
  </div>
</main>
<script>
  var status = document.getElementById("status");
  var out = document.getElementById("out");

  function send(file) {
    if (!file) return;
    out.classList.add("hide");
    status.classList.remove("hide");
    status.className = "spin";
    status.textContent = "Reading the grid…";

    var fd = new FormData();
    fd.append("photo", file);
    fd.append("word", document.getElementById("word").value || "COW");
    fd.append("directions", document.getElementById("dirs").value);
    fd.append("rotate", document.getElementById("rot").value);

    fetch("solve", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j.error || "failed");
        var j = res.j;
        document.getElementById("n").textContent = j.count;
        document.getElementById("bydir").innerHTML =
          Object.keys(j.by_direction).map(function (k) {
            return "<span>" + k + " <b>" + j.by_direction[k] + "</b></span>";
          }).join("");
        var u = document.getElementById("unc");
        if (j.uncertain) {
          u.textContent = j.uncertain + " more depend on a glyph that could not be read"
                        + " — not counted above.";
          u.classList.remove("hide");
        } else { u.classList.add("hide"); }
        document.getElementById("ann").src = "data:image/jpeg;base64," + j.annotated;
        document.getElementById("grid").textContent =
          "rotation " + j.rotation + "°, skew " + j.skew + "°, grid "
          + j.rows + "×" + j.cols + "\n\n" + j.grid;
        status.classList.add("hide");
        out.classList.remove("hide");
      })
      .catch(function (e) {
        status.className = "err";
        status.textContent = e.message;
      });
  }

  document.getElementById("cam").addEventListener("change", function () { send(this.files[0]); });
  document.getElementById("lib").addEventListener("change", function () { send(this.files[0]); });
</script>
"""


@app.get("/")
def index():
    return PAGE


@app.post("/solve")
def solve_upload():
    f = request.files.get("photo")
    if f is None or not f.filename:
        return jsonify(error="no photo was sent"), 400

    word = (request.form.get("word") or "COW").strip()
    directions = request.form.get("directions") or "all"
    rotate = request.form.get("rotate") or "auto"
    if directions not in ("all", "horizontal"):
        return jsonify(error="directions must be 'all' or 'horizontal'"), 400
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
