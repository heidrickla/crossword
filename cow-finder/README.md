# cow-finder

Photo of a "find the COW" word-search puzzle in, verified answers out.

Segments and geometrically classifies every glyph (C, O, W plus decoys Ɔ/M),
auto-detects page rotation, reconstructs the grid under perspective tilt,
searches all 8 directions, independently re-verifies every hit from raw
pixels, and emits an annotated image plus per-hit crop strips.

```
python -m cowfinder.cli photo.jpg --out annotated.png --strips strips.png
```

See `AGENTS.md` and `docs/SPEC.md` before making changes — this repo was
packaged from a working session and the spec documents real failure modes.

Golden reference: `tests/golden_photo.jpg` → 31 COWs (9→ 1← 6↓ 10↘ 5↙),
32×20 grid. `python -m pytest tests/` must stay green.
