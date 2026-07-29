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
```

A single page with **Take photo** and **Choose photo**. The camera button uses
`capture="environment"`, so Android opens the camera directly rather than the
gallery. Results come back as the count by direction, the annotated grid, and
the reconstructed ASCII grid; anything resting on an unreadable glyph is
reported separately and never folded into the count.

The web extra is optional on purpose — the solver core stays `opencv` +
`numpy`, so the CLI and the golden test never depend on a web stack.

Running as a service: `deploy/cowfinder-web.service`.

See `AGENTS.md` and `docs/SPEC.md` before making changes — this repo was
packaged from a working session and the spec documents real failure modes.

Golden reference: `tests/golden_photo.jpg` → 31 COWs (9→ 1← 6↓ 10↘ 5↙),
32×20 grid. `python -m pytest tests/` must stay green.
