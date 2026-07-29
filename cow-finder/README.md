# cow-finder

Photo of a "find the COW" word-search puzzle in, verified answers out.

Segments and geometrically classifies every glyph (C, O, W plus decoys Ɔ/M),
auto-detects page rotation, reconstructs the grid under perspective tilt,
searches all 8 directions, independently re-verifies every hit from raw
pixels, and emits an annotated image plus per-hit crop strips.

```
python -m cowfinder.cli photo.jpg --out annotated.png --strips strips.png
```

Options: `--word` (letters must be ones the classifier can emit: C/D/O/W/M,
where D is the backwards-C decoy and M the upside-down W), `--directions
all|horizontal`, `--rotate auto|0|90|180|270` to override orientation
detection when it guesses wrong.

## From a phone

```
pip install -e ".[web]"
python -m cowfinder.web            # http://<host>:8420
python -m cowfinder.web --port 80  # what the service unit runs
```

**Use port 80 for anything a phone reaches over the VPN.** Verified 2026-07-29:
from a phone on UniFi Teleport, `10.10.60.20:8420` times out while the same
service on `:80` loads immediately — and the same `:8420` answers fine from
hosts on another VLAN. Nothing on the host filters (no ufw, iptables ACCEPT),
and no gateway policy names the address, subnet or port, so the block is
somewhere in the Teleport path rather than anything configurable found so far.
Standard ports work; treat high ports as unreachable from the phone.

A single page with **Take photo** and **Choose photo**. The camera button uses
`capture="environment"`, so Android opens the camera directly rather than the
gallery.

Your photo appears immediately, before a byte is uploaded. `POST /solve/stream`
then returns newline-delimited JSON as the work happens — a stage per real step
(orienting, segmenting, classifying, gridding, searching, verifying), then the
upright image, then **one event per hit**. The page draws each hit onto a canvas
over the photo, colour-coded by direction, with the counter climbing as they
land. Anything resting on an unreadable glyph is reported separately and never
folded into the count.

The overlay is drawn client-side from geometry rather than baked into a
server-rendered image: the boxes stay in the coordinate space the server
measured them in, which is where `docs/SPEC.md`'s coordinate bugs used to live.
`POST /solve` still returns a single JSON blob with a flattened annotated image
for non-interactive use; a test asserts the two endpoints agree.

The web extra is optional on purpose — the solver core stays `opencv` +
`numpy`, so the CLI and the golden test never depend on a web stack.

Running as a service: `deploy/cowfinder-web.service`.

See `AGENTS.md` and `docs/SPEC.md` before making changes — this repo was
packaged from a working session and the spec documents real failure modes.

Golden reference: `tests/golden_photo.jpg` → 31 COWs (9→ 1← 6↓ 10↘ 5↙),
32×20 grid. `python -m pytest tests/` must stay green.
