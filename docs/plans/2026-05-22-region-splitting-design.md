# Region Splitting — Design

**Status:** Designed, **not scheduled**. Lower priority than text/style/position fidelity
work tracked separately.

**Goal:** Let the user split one OCR region into per-character regions on demand, so
characters can be aligned to the AI image's drawn character positions without the
spacing artifacts seen in the reverted per-glyph rendering attempt
(see commit `b298eb0`).

**Why this works where per-glyph rendering didn't:** Each split child is a normal
`EditableRegion` with its own bbox.  `fit_font_size_to_bbox` therefore re-computes a
per-child font size that matches that child's bbox width.  The font's glyph advance
naturally fills the AI character cell, so the "gaps between every character" failure
mode of the prior approach disappears.

## Architecture

User action in editor → backend computes per-character sub-bboxes from the source
image → editor replaces the parent region with N children → standard render path
takes over.  No SVG output changes.  No data-model schema changes.  Reversibility is
provided by the editor's existing `pushHistory` / Ctrl+Z stack.

## Backend

### `glyph_layout.measure_glyph_bboxes(image_bgr, parent_quad, text) -> (sub_quads, high_confidence)`

Extends `glyph_layout` with a width-returning variant.

- Reuses `_ink_projection` + `_find_ink_islands` (already tested).
- Each character's sub-bbox is the (left, top, right, bottom) of its ink island,
  clipped to the parent quad's height.
- When `len(islands) != len([c for c in text if not c.isspace()])`, fall back to
  equal-mass partition and return `high_confidence=False`.
- Whitespace characters are skipped — no sub-region is created for them.

### `pipeline.split_region_by_glyphs(image_rgb, region) -> List[EditableRegion]`

- For each non-space char + sub-quad pair, build an `EditableRegion`:
  - `text` / `original_text` = the single char
  - `bbox` = the sub-quad
  - `color`, `background`, `font_family`, `font_weight`, `text_anchor` = inherited
    from parent
  - `font_size_px` = `fit_font_size_to_bbox` result on the child
  - `replace` = parent's `replace`
- If `region.spans` is non-empty: raise `ValueError`.  The frontend disables the
  split button in this case; the raise is a defensive backstop.

## Frontend

- Region detail panel gets a "Split into characters" button.
- Disabled when the selected region has spans; tooltip: "请先清除 spans".
- Click → `POST /api/split_region/<region_id>` →
  `{children: [...EditableRegion], high_confidence: bool}`.
- Client: `pushHistory('split-' + region_id)`, replace parent in `state.regions`
  with `children`, re-render.
- When `high_confidence` is `false`, each child gets a CSS class
  `region-uncertain` for a visual hint (light border / corner badge) so the user
  knows to verify alignment.

## Tests

- `tests/test_glyph_layout.py`: `test_measure_glyph_bboxes_*`
  - CJK: one island per character → high_confidence=True, bboxes match islands
  - Latin connected ("tt", "il"): islands mismatch → equal-mass fallback,
    high_confidence=False
  - Whitespace: spaces produce no sub-region
- `tests/test_pipeline.py` (non-OCR portion): `test_split_region_by_glyphs_*`
  - Builds a synthetic image + region; verifies child count, inherited style,
    fit_font_size_to_bbox effect
  - `ValueError` when parent has spans

Frontend split path verified manually for v1; can add headless test later.

## Explicitly out of scope (YAGNI)

- Reverse "merge" button — Ctrl+Z is enough.
- Custom split counts (split into N parts other than per-character).
- spans-aware splitting that distributes spans across children.
- Auto-detecting which regions "deserve" splitting (always user-triggered).
- A confidence threshold that auto-falls-back to keeping the parent.

## Open questions before implementation

- Should `EditableRegion` carry a transient `confidence_warning: str` field that
  round-trips through `review.json`, or should `high_confidence` be a one-shot IPC
  response field that the editor stores in JS only?  Leaning toward the latter
  (no schema change; warning evaporates after save/reload, which is fine — it's an
  edit-time hint, not a persistent property).
