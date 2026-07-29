# AGENTS.md — cow-finder

Authoritative guidance for AI agents working in this repo. Read this and
`docs/SPEC.md` before editing anything.

## What this is

A photo-in, answers-out solver for "find the COW" word-search puzzles
(letters C, O, W plus decoys Ɔ and M). The code in `cowfinder/` is not a
scaffold — it is a working pipeline validated end-to-end against a real
handheld photo, packaged from a proven interactive session.

## Hard constraints

1. **`docs/SPEC.md` is the design document.** It encodes real failure modes
   that were hit and fixed (OCR unusability, 180° orientation trap, row-merge
   under tilt, global x-clustering collapse, coordinate-transform off-by-ones).
   Do not "simplify" the pipeline in ways the spec calls out as anti-patterns.
2. **The golden test is inviolable.** `tests/golden_photo.jpg` must always
   yield 31 COWs (9→ 1← 6↓ 10↘ 5↙) on a 32×20 grid with rotation=180
   auto-detected. Any change that alters this result is a regression, not an
   improvement, unless you can prove the golden answer itself was wrong.
3. **Never remove the independent re-verification pass** (`verify.reverify`)
   or the `?` uncertainty channel. Ambiguity is reported, never guessed away.
4. **No OCR dependencies.** Geometric classification only; see SPEC for why.

## Working practice

- Run `python -m pytest tests/` before and after changes.
- Keep one canonical coordinate space (upright image) as early as possible;
  the coordinate cheat sheet in SPEC section "Coordinate-transform cheat
  sheet" is where most historical bugs lived.
- New capabilities (other words, other decoy alphabets, batch mode) go in as
  additive options; the default behavior stays golden-test-stable.
- SDK/tool availability: check before claiming build/test results.

## Quick start

```
pip install -e .          # or: pip install opencv-python-headless numpy
python -m cowfinder.cli tests/golden_photo.jpg --out annotated.png
python -m pytest tests/
```
