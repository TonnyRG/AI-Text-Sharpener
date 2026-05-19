# AI Text Sharpener

Replace blurry text in AI-generated images with crisp, editable vector text — then export the cleaned-up deck back to PPTX.

AI image generators are great at illustration but bad at text: the result is usually a soup of half-formed characters. This tool detects every text region with PaddleOCR, gently erases the originals, and rasters back sharp vector text in fonts of your choice. Everything is editable in a local browser editor before the final render.

## Status

`v0.1` — MVP feature-complete. End-to-end pipeline works on Windows. Linux/macOS support is mostly untested.

## Features

- **OCR text detection** with PaddleOCR (PP-OCRv5 server models, CPU or GPU)
- **Soft-erase** original blurry text without obvious patches
- **SVG / PNG output** rendered with resvg — vector-perfect text
- **Local browser editor** for hand-fixing OCR mistakes, font, color, position, alignment
  - PPT-style interactions: marquee multi-select, drag, arrow-key nudge, snap-to-align
  - Right-click rich formatting: superscript / subscript / bold / color / size per character
  - Inline spans for mixed formatting in one text line (e.g. `H₂O`)
  - Eyedropper color picker (uses native EyeDropper API where available)
  - Auto-render with debounce; auto-fit font sizes to bbox
  - Undo / redo (Ctrl+Z / Ctrl+Y)
- **Font management**: scans installed system fonts grouped by language; drop additional `.ttf`/`.otf`/`.ttc` into `fonts/` to import
- **Multi-slide projects**: PPT import via PowerPoint COM (Windows), batch processing, flat-image PPTX export

## Install

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # Linux / macOS
pip install -e .
```

PaddlePaddle is the heavyweight dependency. Default install gets the CPU build. For GPU, follow the [PaddlePaddle install guide](https://www.paddlepaddle.org.cn/install/quick) and pick the matching wheel before `pip install -e .`.

Windows-CPU users: set these env vars to avoid a known OneDNN bug:

```bash
set FLAGS_use_mkldnn=0
set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

## Quick start — single image

```bash
ai-text-sharpener input.jpg -o output.png \
  --title-font "Microsoft YaHei Bold" \
  --body-font "Microsoft YaHei"
```

Output: `output.png` (rasterized) + `output.svg` (vector).

## Editable workflow

1. Generate a draft + review JSON:
   ```bash
   ai-text-sharpener input.jpg -o draft.png --review-json review.json
   ```
2. Open the browser editor:
   ```bash
   ai-text-sharpener-editor input.jpg review.json --output-png final.png
   ```
   Click into a text region, fix OCR mistakes, drag to reposition, right-click selected characters for super/subscript/color. Auto-saves as you go.
3. Hit **Render** (or just let auto-render fire) for the final `final.png` + `final.svg`.

## Batch PPT workflow

Import a `.pptx` deck, edit slide-by-slide, and export back to a flat-image PPTX:

```bash
ai-text-sharpener-ppt deck.pptx --output-dir examples/ppt_reviews/deck
# Opens the multi-slide editor automatically.
# When done, click "Export PPT" in the toolbar.
```

The exported PPTX has each slide as a full-bleed rendered PNG. Re-edit the source PPT if you need PowerPoint-level granularity; the exported deck is for distribution.

## Importing custom fonts

Drop any `.ttf` / `.otf` / `.ttc` file into `fonts/` (created automatically at the project root on first editor launch) and refresh the browser. The font's internal family name appears under the **Imported** group in the Inspector's font picker, and is used by both the canvas preview and the final SVG render.

## Documentation

- [docs/plans/2026-05-18-design.md](docs/plans/2026-05-18-design.md) — full design rationale
- [docs/plans/2026-05-18-mvp-implementation.md](docs/plans/2026-05-18-mvp-implementation.md) — task-by-task implementation plan
- [docs/mvp-validation-report.md](docs/mvp-validation-report.md) — per-slide validation results
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, project layout, conventions

## License

Apache 2.0 — see [LICENSE](LICENSE).
