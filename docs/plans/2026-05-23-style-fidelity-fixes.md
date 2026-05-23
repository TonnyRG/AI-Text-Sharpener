# Style Fidelity Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the two highest-leverage style-fidelity bugs surfaced by the 2026-05-23
intern-report validation: (1) white-on-dark text rendered as invisible dark-on-dark,
and (2) every text region rendered bold because the `title_min_px=40` threshold doesn't
scale to 4K images.

**Architecture:** Both fixes are localized parameter / heuristic changes — no new
modules, no API additions visible to callers. TDD with synthetic fixtures (no
PaddleOCR in the test loop).

**Tech Stack:** Python 3.11 / numpy / existing test harness (pytest).

**Reference:**
- Bug evidence: `output/intern_compare_001.jpg`, `_003.jpg`, `_016.jpg`, `_017.jpg`
- `extract_style` / `sample_text_color`: [style.py:35-43](../../src/ai_text_sharpener/style.py#L35-L43)
- `FontSpec` / `assign_fonts`: [fonts.py](../../src/ai_text_sharpener/fonts.py)
- Threshold consumer: [pipeline.py:117](../../src/ai_text_sharpener/pipeline.py#L117)

---

## Scope

**In:**
- Auto-detect inverse-color text regions (white/light text on dark backgrounds).
- Make the title-vs-body font threshold scale with image height.

**Out of scope (separate plan if needed):**
- Multi-line OCR row recovery (slide_017 "提问更聚焦\n更专业" first line lost).
- Inline color-span detection inside a single OCR region (slide_003 red highlights).
- Font-family fidelity (still hardcoded YaHei).
- CJK/Latin space restoration (`merge.py` deliberate behavior per CLAUDE.md).

---

## Task 1: Scale title threshold with image height

**Root cause:** `FontSpec.title_min_px` defaults to 40. At image_height=4500 the entire
slide's text is well above 40 px, so `assign_fonts` routes every region to the title
font (`Microsoft YaHei Bold`) and every region renders bold.

**Fix:** Add `title_min_ratio` to `FontSpec` (default 0.035 → 4500 × 0.035 ≈ 158 px
threshold).  Add a helper `effective_title_min_px(spec, image_height) -> int` that
returns `max(spec.title_min_px, int(image_height * spec.title_min_ratio))`.  Call it
in `analyze_image` to derive a per-image threshold; pass via a temp `FontSpec` to
`assign_fonts` (zero churn on the `assign_fonts` signature).

**Files:**
- Modify: `src/ai_text_sharpener/fonts.py`
- Modify: `src/ai_text_sharpener/pipeline.py`
- Modify: `tests/test_fonts.py`

### Step 1: Write failing tests

Append to `tests/test_fonts.py`:

```python
from ai_text_sharpener.fonts import effective_title_min_px


def test_effective_title_min_px_scales_with_image_height():
    spec = FontSpec(title="T", body="B", title_min_px=40, title_min_ratio=0.035)
    # 4500 × 0.035 = 157.5 → 157, which dominates the 40 absolute floor
    assert effective_title_min_px(spec, image_height=4500) == 157


def test_effective_title_min_px_floors_at_absolute():
    spec = FontSpec(title="T", body="B", title_min_px=80, title_min_ratio=0.035)
    # 1000 × 0.035 = 35, but 80 absolute floor wins
    assert effective_title_min_px(spec, image_height=1000) == 80


def test_font_spec_default_ratio_is_set():
    spec = FontSpec(title="T", body="B")
    assert spec.title_min_ratio == 0.035
```

### Step 2: Run failing

`.venv/Scripts/python.exe -m pytest tests/test_fonts.py -v`
Expected: 3 new tests FAIL on `ImportError` / `AttributeError`.

### Step 3: Implement

In `src/ai_text_sharpener/fonts.py`, edit `FontSpec`:

```python
@dataclass
class FontSpec:
    title: str
    body: str
    title_min_px: int = 40
    title_min_ratio: float = 0.035  # fraction of image_height for "title" classification
```

Append the helper to the same file:

```python
def effective_title_min_px(spec: FontSpec, image_height: int) -> int:
    """Title threshold scaled to image height; never below ``spec.title_min_px``."""
    return max(spec.title_min_px, int(image_height * spec.title_min_ratio))
```

In `src/ai_text_sharpener/pipeline.py`, update `analyze_image`. Add import at top:

```python
from dataclasses import replace
from .fonts import FontSpec, assign_fonts, effective_title_min_px, prepare_render_font_dirs
```

Then replace the `font_families = assign_fonts(sizes, font_spec)` line with:

```python
    effective_spec = replace(font_spec, title_min_px=effective_title_min_px(font_spec, h))
    font_families = assign_fonts(sizes, effective_spec)
```

### Step 4: Run passing

`.venv/Scripts/python.exe -m pytest tests/test_fonts.py tests/test_pipeline.py -v --ignore-glob="*test_pipeline.py"`

(skip test_pipeline.py — it's OCR-slow; run separately later)

Quicker: `.venv/Scripts/python.exe -m pytest tests/test_fonts.py -v`
Expected: 5 tests pass (2 old + 3 new).

### Step 5: Commit

```
git add src/ai_text_sharpener/fonts.py src/ai_text_sharpener/pipeline.py tests/test_fonts.py
git commit -m "fix(fonts): scale title/body threshold to image height"
```

---

## Task 2: Auto-detect inverse-color text

**Root cause:** `sample_text_color` always picks the median of the **darkest** 20% of
patch pixels.  For a region containing **white text on a dark blue bar**, the darkest
20% are the dark-blue background pixels, so the returned "text color" is dark blue —
which then renders as invisible dark-blue text on a dark-blue erase patch.

**Fix:** Use the patch's own median lightness as a discriminator.  If the patch is
light-dominated (median lightness ≥ 128), text is dark — sample darkest 20% (existing
behaviour).  If the patch is dark-dominated, text is light — sample **lightest** 20%.
No reliance on the bbox-ring background (which can fall outside the dark bar and
return a misleading cream-color reading).

**Files:**
- Modify: `src/ai_text_sharpener/style.py`
- Modify: `tests/test_style.py`

### Step 1: Write failing test

Append to `tests/test_style.py`:

```python
def test_sample_text_color_picks_light_strokes_on_dark_background():
    """White-on-dark-blue title-bar case from intern-report slide_016/017."""
    img = np.full((100, 200, 3), [40, 50, 90], dtype=np.uint8)  # dark navy
    img[40:60, 80:120] = 255  # white "text block"
    rect = (70, 30, 60, 40)  # covers white block + dark frame
    rgb = sample_text_color(img, rect)
    # Should land near white (sum ~765), NOT near dark navy (sum ~180)
    assert sum(rgb) > 600, f"got {rgb}, expected light/white text color"
```

### Step 2: Run failing

`.venv/Scripts/python.exe -m pytest tests/test_style.py::test_sample_text_color_picks_light_strokes_on_dark_background -v`
Expected: FAIL — returned color is around (40, 50, 90), sum ≈ 180.

### Step 3: Implement

Replace the body of `sample_text_color` in `src/ai_text_sharpener/style.py`:

```python
def sample_text_color(img: np.ndarray, rect: Rect) -> RGB:
    """Sample text color robustly for both dark-on-light and light-on-dark cases.

    Uses the patch's own median lightness to decide which polarity the text is:
    light-dominated patch → text is dark, sample darkest 20%; dark-dominated patch
    → text is light, sample lightest 20%.  No reliance on a bbox-ring sample,
    which can fall outside a colored title bar and mislead.
    """
    x, y, w, h = rect
    patch = img[y:y + h, x:x + w]
    if patch.size == 0:
        return (0, 0, 0)
    lum = patch.mean(axis=2)
    median_lum = float(np.median(lum))
    if median_lum >= 128:
        threshold = np.percentile(lum, 20)
        mask = lum <= threshold
    else:
        threshold = np.percentile(lum, 80)
        mask = lum >= threshold
    if not mask.any():
        return tuple(int(c) for c in patch.reshape(-1, 3).mean(axis=0))
    ink_pixels = patch[mask]
    return tuple(int(c) for c in np.median(ink_pixels, axis=0))
```

### Step 4: Run passing

`.venv/Scripts/python.exe -m pytest tests/test_style.py -v`
Expected: all 5 tests pass (4 old + 1 new).  Confirm the original
`test_sample_text_color_picks_dark_strokes` still passes — it should, because the
white-with-black-block image has median lightness ≈ 240, the light-dominated branch
fires, and the existing "darkest 20%" logic returns black.

### Step 5: Commit

```
git add src/ai_text_sharpener/style.py tests/test_style.py
git commit -m "fix(style): auto-detect inverse-color text via patch median lightness"
```

---

## Task 3: Visual validation on the 5 intern-report slides

**Files:**
- Regenerate: `examples/ppt_reviews/intern_report_v2/drafts/slide_{001,003,008,016,017}_draft.png`
- Rebuild: `output/intern_compare_{001,003,008,016,017}.jpg`

### Step 1: Re-sharpen the 5 slides

```
FLAGS_use_mkldnn=0 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONIOENCODING=utf-8 \
  .venv/Scripts/python.exe -c "
from pathlib import Path
from ai_text_sharpener.pipeline import sharpen_image
from ai_text_sharpener.fonts import FontSpec
spec = FontSpec(title='Microsoft YaHei Bold', body='Microsoft YaHei', title_min_px=40)
slides_dir = Path('examples/ppt_reviews/intern_report_v2/slides')
out_dir = Path('examples/ppt_reviews/intern_report_v2/drafts')
for n in [1, 3, 8, 16, 17]:
    sharpen_image(slides_dir / f'slide_{n:03d}.jpg',
                  out_dir / f'slide_{n:03d}_draft.png',
                  out_dir / f'slide_{n:03d}_draft.svg', spec)
    print(f'OK slide_{n:03d}')
"
```

Expected: completes in ≤ 15 minutes total (~3 min/slide CPU, model loaded once).

### Step 2: Rebuild the before/after comparison images

Reuse the same script as before (already produces `output/intern_compare_NNN.jpg`).

### Step 3: Manual inspection criteria

For each of the 5 comparisons, verify:

- **slide_001 (cover)**: subtitle "22 制药（1）班李南樽" is now REGULAR weight (not bold).
- **slide_003 (bullets)**: 3 row descriptions are now REGULAR weight (the bold-everywhere
  bug should be gone).  Inline red emphasis remains lost — that's deferred.
- **slide_008 (diagram)**: should look approximately the same as before (no regression).
- **slide_016 (multi-card)**: title banner "实习中暴露出的自身短板" is now VISIBLE in
  white-on-blue; card body text is REGULAR weight.  Numbers 1–6 in circles should also
  show as white-on-color (not dim).
- **slide_017 (numbered flow)**: title banner "沟通方式的转变与能力的进步" VISIBLE;
  number labels 1–5 in arrows VISIBLE.  Body text in arrow cards REGULAR weight.

If any of those criteria fail, STOP and report — don't push.  The fixes are localized
enough that any failure indicates a wrong assumption in the diagnosis.

### Step 4: Commit the regenerated draft outputs

Drafts are gitignored (`examples/before_after/*.png` etc.); the only thing worth
committing here is the comparison JPG itself if useful as a reference.  For now:

```
git status
# Nothing to add — drafts and comparisons are gitignored / build artefacts.
```

(Skip if status is clean.)

---

## Out-of-scope follow-ups

- **Multi-line OCR row loss** (slide_017 "提问更聚焦\n更专业" → first line dropped).
  Likely a `merge_horizontal_neighbors` interaction or a PaddleOCR result that needs
  vertical-merge counterpart.
- **Inline color span detection** (slide_003 red emphasis): cluster patch pixels by
  hue → emit per-cluster `TextSpan` with appropriate color.
- **Font-family fidelity**: image-based font detection or per-region user picker in
  the editor (already half-supported via `font_family` field).
- **CJK/Latin space restoration**: revisit `merge.py` deliberate-no-space behavior
  with a smarter heuristic.
