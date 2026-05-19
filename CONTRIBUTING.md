# Contributing to AI Text Sharpener

Thanks for the interest! This project replaces blurry text in AI-generated images with crisp vector text and lets users hand-edit the result through a local browser editor. Contributions of all sizes are welcome.

## Quick start

```bash
git clone https://github.com/<your-fork>/AI-Text-Sharpener.git
cd AI-Text-Sharpener
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux / macOS
pip install -e ".[dev]"
```

PaddlePaddle is heavy. On Windows + CPU the default `paddlepaddle` works. On Linux/macOS or with a GPU, follow the [PaddlePaddle install guide](https://www.paddlepaddle.org.cn/install/quick) and pick the matching wheel.

If you hit `AttributeError: ConvertPirAttribute2RuntimeAttribute` on Windows-CPU, set:

```bash
set FLAGS_use_mkldnn=0
set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

## Running tests

```bash
pytest
```

All 40 tests should pass in <30 s. Tests that touch PaddleOCR (`tests/test_detect.py`) are the slow ones; the rest are fast unit tests.

## Project layout

```
src/ai_text_sharpener/
  cli.py            # `ai-text-sharpener` command
  pipeline.py       # analyze_image + render_review_document
  detect.py         # PaddleOCR wrapper
  erase.py          # soft-erase original text
  style.py          # color + font-size extraction
  merge.py          # merge OCR fragments on the same line
  rasterize.py      # SVG → PNG via resvg
  svg_gen.py        # SVG text overlay generation
  review.py         # ReviewDocument / EditableRegion / TextSpan dataclasses
  project.py        # multi-slide review project manifest
  fonts.py          # font discovery + grouping
  editor.py         # local browser editor (single-file HTML + HTTP handler)
  ppt_import.py     # PPT → review project (Windows COM)
  ppt_export.py     # review project → flat-image PPTX
```

## How the editor works

`editor.py` is one big file: ~1500 lines of inline HTML + JavaScript served by a `ThreadingHTTPServer`. State lives in the browser as a single `state` object mirroring `ReviewDocument`. Server endpoints:

- `GET /api/state` — current review JSON for the active slide
- `POST /api/review` — save JSON only (cheap; what auto-save uses)
- `POST /api/render` — save + render (PNG + SVG)
- `POST /api/redetect` — re-run OCR and merge new regions
- `POST /api/autofit` — shrink font sizes that overflow bboxes
- `POST /api/export-ppt` — flat-image PPTX of all slides
- `GET /api/fonts` — discovered system + imported fonts
- `GET /fonts/<name>` — serve a user-imported font for `@font-face`
- `GET /image` / `/image-rendered` — source image or rendered PNG (with auto-render-if-stale)

## Conventions

- **Don't break existing review JSON.** All `EditableRegion` fields have defaults; new fields go via `data.get(...)` in `from_dict`.
- **No new render-side dependencies without discussion.** resvg-py is the rasterizer; switching would touch the whole pipeline.
- **Editor features should mirror PowerPoint / Figma where possible.** The project's design direction is "feels like PPT, but for AI image text fixup." Avoid bespoke gestures.
- **Tests first for non-trivial logic.** The fonts / pipeline / review modules have unit tests; mirror that for new code.

## Pull requests

1. Fork and branch off `main`.
2. Keep PRs focused — one feature or fix per PR.
3. Run `pytest` locally; CI will also run it.
4. If your change is user-visible (new button, new endpoint, new CLI flag), update `README.md` accordingly.
5. Add yourself to a CONTRIBUTORS section if you'd like attribution.

## Reporting bugs

Open an issue with:
- OS + Python version
- Steps to reproduce
- Input image / review JSON (or a redacted minimal example) if relevant
- Tail of the editor console output

## License

By contributing, you agree your contributions are licensed under Apache 2.0 (see [LICENSE](LICENSE)).
