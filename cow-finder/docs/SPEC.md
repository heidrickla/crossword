# COW Finder — Word-Search Puzzle Solver Spec

Build a CLI tool that takes a photo of a printed "find the COW" word-search grid (letters C, O, W plus decoys Ɔ and M) and outputs the count and locations of every "COW", with an annotated result image. This spec encodes lessons learned from a working prototype — the gotchas listed here are all real failure modes that were hit and fixed.

## Goal

```
cowfinder solve photo.jpg [--word COW] [--directions all|horizontal] [--out annotated.png]
```

Output:
- Total count, broken down by direction (→ ← ↓ ↑ ↘ ↙ ↗ ↖)
- Grid coordinates of each hit
- Annotated image with hits drawn color-coded by direction
- Reconstructed ASCII grid (for debugging and manual verification)

## Why OCR is the wrong tool (don't start there)

Tesseract fails hard on these puzzles and this was verified empirically:
1. The decoy alphabet includes **Ɔ (backwards C)** and **M (upside-down W)**. OCR collapses Ɔ→C and can't be trusted on M vs W, which destroys the puzzle's entire premise.
2. Whitelisting `COW` makes tesseract silently drop or misread the decoys, producing rows with missing letters — you can't even trust letter *positions*.
3. OCR gives no confidence signal per glyph, so you can't flag ambiguous cells.

**Use shape classification on segmented glyphs instead.** The five glyph classes are geometrically trivial to distinguish; OCR adds failure modes without adding value.

## Pipeline

### 1. Orientation detection (critical — this bit me)

Phone photos of a page can be rotated 0/90/180/270. **Do not assume; detect.** The tell: run classification on a candidate orientation and check the class distribution. In a COW puzzle, the intended orientation contains genuine `C` and `W` glyphs. If classification returns **only Ɔ and M with zero C/W, the image is exactly 180° off** — every C reads as Ɔ and every W as M. Auto-detect by classifying a sample of ~50 glyphs at each of the 4 rotations and picking the one that yields a healthy mix of C/W (or the max count of the target word after full solve).

Cheap equivalent transform if you've already built the grid upside down: reverse row order, reverse each row, and swap C↔Ɔ, W↔M.

### 2. Binarize and segment

- Grayscale → `cv2.adaptiveThreshold` (ADAPTIVE_THRESH_MEAN_C, INV, blockSize≈51, C≈15). Adaptive, not global — paper photos have illumination gradients.
- Morphological open (3×3) to kill speckle.
- `connectedComponentsWithStats`; keep components with plausible glyph size (filter on w, h, area relative to the median — for a 4000px photo, glyphs were ~55–70px; don't hardcode, derive from the median component size).

### 3. Glyph classification (the core)

Classify each component ROI into `{C, Ɔ, O, W, M, ?}` using geometry, in this order:

1. **O — hole test.** `findContours` with `RETR_CCOMP`; if any child contour has area > 5% of the bbox → closed loop → `O`. Do this FIRST; everything else assumes no hole.
2. **Ring vs zigzag.** Compute radial distances of ink pixels from the centroid. `rel_std = r.std()/r.mean()`. Ring-like (C/Ɔ with a gap, so no hole was found) has `rel_std < ~0.30`; W/M zigzags come in around 0.38–0.40. This threshold was stable in practice.
3. **C vs Ɔ — gap direction.** Angular histogram of ink pixels around the centroid (36 bins over 360°). The empty bins mark the gap. Circular-mean the empty-bin angles: gap pointing right (−90°..+90°) → `C`, gap pointing left → `Ɔ`.
4. **W vs M — contact-run counting.** Count connected ink runs along the top edge strip vs bottom edge strip of the bbox (strip height ≈ h/10, min 2px). W touches the top in 3 places and the bottom in 2; M is the reverse. If runs tie → `?` (don't guess).

Keep `?` as an explicit class. Ambiguity is information — see step 6.

### 4. Grid reconstruction (harder than it looks on phone photos)

Perspective/tilt from a handheld photo means naive y-clustering **will merge adjacent rows and split single rows**. This happened; rows fragmented at the top and three rows merged at the bottom.

- **Row deskew:** for each candidate tilt angle `a` in −8°..+8° (0.1° steps), project centroids to `y' = y − x·tan(a)` and score the histogram sharpness (`(hist**2).sum()`). Use the best angle, then cluster `y'` with a gap threshold (~0.6× row pitch).
- **Row-merge repair:** any cluster with ≈2–3× the modal glyph count is merged rows — re-split it by raw y within the cluster.
- **Column assignment — do NOT globally cluster x.** Global 1-D clustering of x-centers failed twice (perspective compresses spacing toward the far edge of the photo, and column tilt differs from row tilt). What works:
  - If a row has exactly the modal glyph count (e.g. 20), **column index = sorted position index**. This is the robust path and covers almost all rows.
  - For irregular rows only, align by x against neighboring full rows: a row that's short is usually missing an **edge** glyph (clipped by the photo border) — detect which end by comparing its first/last x to the neighbor's. A row that's long usually has a **stray edge artifact** (partial glyph at the photo border, big x-gap to the rest) — drop it.
- Column alignment correctness is invisible for horizontal search but **essential for diagonal/vertical search**. A misaligned grid produced phantom diagonal hits and missed real ones. Sanity check: horizontal hits found on the 2-D grid must exactly match hits found on the per-row strings.

### 5. Word search

Standard 8-direction scan over the sparse grid `{(row,col): char}`. Only accept trios where all three cells exist (edge rows can have holes). Note: `COW` read one way and `WOC` read the other over the same cells are different letter sequences, so matching the ordered word per direction never double-counts.

Directions configurable: the puzzle owner may want forward-only, or all 8.

### 6. Ambiguity resolution (don't skip this)

After the main search, enumerate every trio that would spell the word **if a `?` cell took the needed letter** (template match with wildcards). For each implicated `?` glyph, run targeted secondary analysis:
- Re-check `rel_std` — zigzag stats (≈0.40, wider than tall) rule out C/O regardless of the W/M tie.
- Render the ROI as small ASCII art (resize to ~30×15, threshold, print `#`/space) — this is genuinely effective for a human or the model to read a single ambiguous glyph, including **clipped edge glyphs** (e.g. the right ⅔ of an M looks like `\/|`; a straight vertical right edge means M, a diagonal means W).
- Edge-of-photo glyphs are the usual `?` source; they're often not even part of the intended puzzle page.

Report any hit that depends on an unresolvable `?` separately as "uncertain" rather than silently including/excluding it.

### 7. Independent verification pass (this caught real bugs)

Before reporting, **re-classify every glyph of every hit directly from raw pixels** using the classifier as an oracle, independent of the grid bookkeeping. This catches coordinate-transform bugs (the 180° mapping, row reversal, column mirroring are all easy to get off-by-one). Require 100% re-verification or fail loudly with the mismatching cells.

Also generate a per-hit crop strip (3 glyph crops side by side, in reading order) so a human can eyeball every hit in seconds.

### 8. Annotated output

Draw on the upright image: bbox per glyph + a line from first to last letter of each hit, color-coded by direction (e.g. red →, orange ←, blue ↓, green ↘, purple ↙). Print the ASCII grid and a direction-count summary.

## Coordinate-transform cheat sheet (source of most bugs)

If working coords are in a rotated space and output must be upright:
- 180° rotation of a point/bbox in an H×W image: `x' = W − (x + w)`, `y' = H − (y + h)`.
- Grid built upside down → fixed grid: `fixed[r][c] = swap(orig[R−1−r][C−1−c])` with `swap = {Ɔ↔C, M↔W, O↔O}`.
- Keep ONE canonical space (upright image) as early as possible; convert everything into it once and never mix spaces.

## Test plan

- Unit-test the classifier on synthetic rendered glyphs (all 5 classes, ±5° rotation, 3 font weights, clipped variants).
- Golden test: the reference photo should yield **9 horizontal COWs / 31 total across 5 directions (9→, 1←, 6↓, 10↘, 5↙, none upward)** on a 32-row × 20-col grid.
- Property test: solving `rotate180(image)` must yield the identical hit set (mapped through the transform).
- Regression: horizontal hits from row-strings == horizontal hits from the 2-D grid (column-alignment canary).

## Suggested structure

```
cowfinder/
  cli.py            # argparse entry
  orient.py         # rotation detection
  segment.py        # threshold + components
  classify.py       # 5-class glyph classifier (+ ASCII debug render)
  gridify.py        # deskew, row cluster/repair, column assignment
  search.py         # 8-direction wildcard-aware search
  verify.py         # independent re-verification + crop strips
  annotate.py       # output image
  tests/
```

Python 3.11+, deps: `opencv-python-headless`, `numpy`. No OCR dependency.
