# Glyph-Layout Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make rendered vector text land on the AI image's actual per-glyph positions instead of the line-bbox center, by feeding `measure_glyph_centers` output into the SVG render path.

**Architecture:**
- `glyph_layout.py` already exists, tested, and unused. Wire it in at **render time** (not analyze time) so editor JSON stays small and edits to `region.text` recompute positions naturally.
- For each active region without spans, measure `len(region.text)` x-centers from the bbox ink projection. Emit one `<text>` element per glyph at its measured (x, y) with `text-anchor="middle"`. This matches the proven mixed-family code path style and avoids SVG multi-x + `text-anchor` ambiguity in resvg.
- Regions with `spans` keep the current rendering path unchanged (spans handle styled subranges; per-glyph positioning of mixed-styling text is out of scope for this iteration).
- Fall back to the current single-`<text>` path when text is empty or measurement returns no centers.

**Tech Stack:** Python 3.11 / numpy / OpenCV / existing `svg_gen.py` + `glyph_layout.py` / pytest.

**Reference:**
- [glyph_layout.py](../../src/ai_text_sharpener/glyph_layout.py) — already complete (8/8 tests pass)
- [pipeline.py:153-220](../../src/ai_text_sharpener/pipeline.py#L153-L220) — `render_review_document` is the integration point
- [svg_gen.py:71-107](../../src/ai_text_sharpener/svg_gen.py#L71-L107) — `_text_tag` is where the per-glyph branch goes

---

## Scope

**In:**
- Single-family, single-span text regions (the 90% case in the existing PPT corpus).
- Both CJK and Latin (ink projection is script-agnostic).
- Graceful fallback when char count changes after editing (equal-mass partition kicks in).

**Out of scope (defer):**
- Per-glyph positioning across `spans` runs.
- Editor UI for showing/dragging measured positions.
- `letter_spacing_px` interaction — ignored in per-glyph mode (positions are explicit).

---

## Task 1: Add per-glyph rendering branch to `svg_gen.py`

**Files:**
- Modify: `src/ai_text_sharpener/svg_gen.py`
- Modify: `tests/test_svg_gen.py`

**Step 1: Write failing tests in `tests/test_svg_gen.py`**

Append:

```python
def test_glyph_xs_emits_one_text_per_char():
    t = TextElement(
        x=100, y=50, text="ABC", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 50, 90],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    # 3 <text> tags, one per glyph, each at its own x
    assert svg.count("<text ") == 3
    assert 'x="10"' in svg and 'x="50"' in svg and 'x="90"' in svg
    assert svg.count('>A<') == 1
    assert svg.count('>B<') == 1
    assert svg.count('>C<') == 1
    # All glyphs share the parent y and font
    assert svg.count('y="50"') == 3
    assert svg.count('font-family="Arial"') == 3


def test_glyph_xs_ignored_when_spans_present():
    """Spans path is unchanged; per-glyph not applied to span runs in this iteration."""
    t = TextElement(
        x=100, y=50, text="AB", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 90],
        spans=[TextSpan(text="A"), TextSpan(text="B")],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    # Falls back to spans rendering: one <text> with two <tspan> (no mixed families)
    assert svg.count("<text ") == 1
    assert "<tspan" in svg


def test_glyph_xs_length_mismatch_falls_back_to_single_text():
    """If glyph_xs length != len(text), don't try per-glyph; render the old way."""
    t = TextElement(
        x=100, y=50, text="ABC", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 50],  # 2 xs for 3 chars
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert svg.count("<text ") == 1
    assert ">ABC<" in svg


def test_glyph_xs_empty_text_no_output():
    t = TextElement(
        x=100, y=50, text="", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert "<text " not in svg
```

**Step 2: Run tests to confirm failure**

```
.venv/Scripts/python.exe -m pytest tests/test_svg_gen.py -v
```

Expected: 4 new tests FAIL (`TypeError: unexpected keyword argument 'glyph_xs'`).

**Step 3: Implement in `src/ai_text_sharpener/svg_gen.py`**

Add field to `TextElement` (after `spans`):

```python
glyph_xs: Optional[List[int]] = None  # if set and len matches text, emit one <text> per glyph
```

Add helper above `_text_tag`:

```python
def _per_glyph_tags(t: TextElement) -> str:
    """Emit one <text> per character at its measured x.  Used when caller has
    measured per-glyph centers from the source image.  Bypassed for empty text
    or when spans are present (spans path stays as-is in this iteration)."""
    parts: List[str] = []
    for ch, gx in zip(t.text, t.glyph_xs or []):
        if not ch:
            continue
        attrs = (
            f'x="{int(gx)}" y="{t.y}" '
            f'font-family="{escape(t.font_family)}" '
            f'font-size="{t.font_size_px}" '
            f'font-weight="{t.font_weight}" '
            f'fill="rgb({t.color[0]},{t.color[1]},{t.color[2]})" '
            f'text-anchor="middle" dominant-baseline="middle"'
        )
        parts.append(f'  <text {attrs}>{escape(ch)}</text>\n')
    return "".join(parts)
```

In `_text_tag`, before the existing `if not t.spans:` branch, add:

```python
    if (
        t.glyph_xs is not None
        and not t.spans
        and t.text
        and len(t.glyph_xs) == len(t.text)
    ):
        return _per_glyph_tags(t)
```

**Step 4: Run tests to confirm pass**

```
.venv/Scripts/python.exe -m pytest tests/test_svg_gen.py -v
```

Expected: all tests pass (old + 4 new).

**Step 5: Commit**

```
git add src/ai_text_sharpener/svg_gen.py tests/test_svg_gen.py
git commit -m "feat(svg): per-glyph <text> emission when glyph_xs provided"
```

---

## Task 2: Wire `measure_glyph_centers` into `render_review_document`

**Files:**
- Modify: `src/ai_text_sharpener/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Step 1: Write failing test in `tests/test_pipeline.py`**

Append (uses the existing `sample_image_path` fixture):

```python
def test_render_uses_per_glyph_positions(sample_image_path, tmp_path):
    """The SVG should contain multiple <text> tags for at least one region,
    proving per-glyph positioning was applied somewhere on the page."""
    from ai_text_sharpener.pipeline import analyze_image, render_review_document
    from ai_text_sharpener.fonts import FontSpec

    spec = FontSpec(title="Microsoft YaHei", body="Microsoft YaHei", title_min_px=40)
    review = analyze_image(sample_image_path, spec)
    # Drop spans to ensure the per-glyph path is exercised
    for r in review.regions:
        r.spans = []
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"
    render_review_document(sample_image_path, out_png, out_svg, review)

    svg_text = out_svg.read_text(encoding="utf-8")
    # With per-glyph rendering, the total <text> count exceeds the active
    # region count (each char becomes its own <text>).
    n_active = sum(1 for r in review.regions if r.replace)
    assert svg_text.count("<text ") > n_active
```

**Step 2: Run test to confirm failure**

```
.venv/Scripts/python.exe -m pytest tests/test_pipeline.py::test_render_uses_per_glyph_positions -v
```

Expected: FAIL (current renderer emits one `<text>` per region; `count == n_active`).

**Step 3: Implement in `src/ai_text_sharpener/pipeline.py`**

In `render_review_document`, replace the `texts = [TextElement(...) for region in active_regions]` block. The change:
- Load `img_bgr` once for measurement (the existing `img` is RGB from PIL — convert for OpenCV).
- For each active region: if `region.spans` is empty and `region.text` is non-empty, call `measure_glyph_centers(img_bgr, region.bbox, len(region.text))`; pass the result as `glyph_xs`.
- Otherwise leave `glyph_xs=None`.

Concrete diff (replace the existing `texts = [...]` list comprehension with):

```python
    import cv2  # local import keeps top of module unchanged if you prefer
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    texts = []
    for region in active_regions:
        glyph_xs = None
        if not region.spans and region.text:
            glyph_xs = measure_glyph_centers(img_bgr, region.bbox, len(region.text))
        texts.append(TextElement(
            x=region.x,
            y=region.y,
            text=region.text,
            font_family=region.font_family,
            font_size_px=region.font_size_px,
            color=region.color,
            font_weight=region.font_weight,
            letter_spacing_px=region.letter_spacing_px,
            text_anchor=region.text_anchor,
            glyph_xs=glyph_xs,
            spans=[
                SvgSpan(
                    text=s.text, color=s.color, font_size_px=s.font_size_px,
                    font_family=s.font_family, font_weight=s.font_weight,
                    vertical_align=s.vertical_align,
                )
                for s in region.spans
            ],
        ))
```

Move `import cv2` to the top of the module with the other imports.

**Step 4: Run all pipeline tests to confirm pass and no regressions**

```
.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -v
```

Expected: all tests pass, including the new one.

**Step 5: Run the full test suite to confirm no other breakage**

```
.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

**Step 6: Commit**

```
git add src/ai_text_sharpener/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): measure per-glyph centers from ink and feed to SVG"
```

---

## Task 3: Visual validation on `image1` and commit spike artifacts cleanup

**Files:**
- Verify: `examples/before_after/image1_sharpened.png` (regenerate)
- Optionally remove: stale spike PNGs under `scripts/spike_glyph_split*.png` (kept only as exploration artifacts)

**Step 1: Re-run the sharpener on image1 (uses the existing review JSON if present)**

```
.venv/Scripts/python.exe -m ai_text_sharpener.cli "E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\image1.jpg" -o "examples/before_after/image1_sharpened.png"
```

Expected: completes without error.

**Step 2: Open the output PNG and compare against `image1_original.jpg`**

Manual check: characters in the title row ("Shiny-preADME") and the subtitle now sit directly on top of the original ink, with no horizontal drift.

If positions look wrong:
- Check `measure_glyph_centers` returns sane local-x for that region using a one-off debug print.
- Confirm `region.bbox` quad is still in image coords after `merge_horizontal_neighbors` (it should be — merge preserves quads).
- STOP and report; don't paper over.

**Step 3: Decide on spike script cleanup**

The spikes already produced these artifacts:
- `scripts/spike_glyph_split.py` (the spike itself, ok to keep)
- `scripts/spike_glyph_split_output*.png`, `scripts/spike_glyph_split_r005*.png` (debug images)

Either delete the debug PNGs or add `scripts/spike_glyph_split_*.png` to `.gitignore`. Choose the gitignore route — keeps reproducibility, doesn't pollute the tree.

```
# add to .gitignore
scripts/spike_glyph_split_*.png
```

**Step 4: Commit**

```
git add .gitignore
git commit -m "chore: ignore spike_glyph_split debug PNGs"
```

---

## Out-of-scope follow-ups (write to punch list, do NOT do now)

- Per-glyph layout across `spans` runs (requires splitting `measure_glyph_centers` output by per-span char counts).
- Editor UI to show measured per-glyph centers and let users nudge individual glyphs.
- Measurement-quality signal: if `len(islands) == n_glyphs`, mark "high confidence"; otherwise the equal-mass fallback may misalign — surface this in the editor.
- Vertical (y) per-glyph measurement for rotated or curved text (not currently supported by OCR detection anyway).
