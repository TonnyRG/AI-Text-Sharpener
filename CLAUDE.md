# AI Text Sharpener — Project Context for Claude

This file is auto-loaded by Claude Code. Read once at session start, then
treat as background — don't quote it back to the user.

## Project basics

- Goal & full design: see [docs/plans/2026-05-18-design.md](docs/plans/2026-05-18-design.md)
- Task-by-task plan: see [docs/plans/2026-05-18-mvp-implementation.md](docs/plans/2026-05-18-mvp-implementation.md)
- User wants you to execute the plan task-by-task with the
  `superpowers:executing-plans` skill — invoke it when resuming work.

## Working with this user

- **No multi-option discussions** when a path is already in the plan.
  At most 2 options + a recommendation, only when there's a genuine
  blocker. The user once said *"我没看懂你的意思，总之先按顺序继续做吧"*
  after a 4-way comparison — that response is what to avoid.
- "Follow the plan" beats "improve the plan" during MVP. v0.2+ ideas
  go in a notes/punch list, not into the code.
- Verify reports: a "tests passed" notification is not enough — read the
  log tail before claiming completion. (Bash background tasks here have
  shown false `exit code 0` notifications.)

## Compute & environment

- **Two-machine setup**:
  - This machine (本机): CPU-only, paddlepaddle CPU build, used for dev/test.
  - 电脑 B: RTX 5070, should use `paddlepaddle-gpu`. Syncthing keeps
    `F:\Project\AI-Text-Sharpener` in sync with the本机 path. Each
    machine has its own `.venv` (not synced — see `.stignore`).
- **Required env vars when running anything that touches PaddleOCR**:
  - `FLAGS_use_mkldnn=0` — paddlepaddle 3.x has a Windows-CPU bug in
    PIR+OneDNN (`AttributeError: ConvertPirAttribute2RuntimeAttribute`).
    Setting this is harmless on GPU too. Already passed via the constructor
    `enable_mkldnn=False`, but the env var is belt-and-braces.
  - `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` — skip the model-host
    connectivity probe that hangs in CN networks.
  - `PYTHONIOENCODING=utf-8` — needed for `print()` of CJK in Windows
    consoles (debug scripts).
- **Mirror & proxy**: pip installs from `https://mirrors.aliyun.com/pypi/simple/`
  with `--timeout 300 --retries 10 --resume-retries 10`. PaddleOCR model
  downloads go through the user's HTTP proxy (typically
  `HTTPS_PROXY=http://127.0.0.1:7890`) when ModelScope source isn't enough.

## Known quirks (do NOT "fix" without discussion)

- `merge.py` deliberately does NOT add a space between latin runs. The
  user wants OCR character errors visible (e.g. "RSShiny" — the second
  letter is actually a misread "R" from the source image's "R Shiny").
  v0.2 GUI will let the user hand-correct that text.
- `min_height_ratio=0.025` in pipeline.py skips small regions like
  school crests. Those areas remain as the original pixels by design —
  the user explicitly asked that crests not be modified.
- `font_size` is capped at `image_height * 0.05` because PaddleOCR
  occasionally returns bboxes that include decorative padding around
  artistic titles (the cover page had a 5066×726 bbox for "Shiny-preADME"
  which would otherwise become a 617px font).

## MVP status at last commit

- Task 1-8: complete. CLI works end-to-end on `image1.jpg`.
- Task 9 (batch validation): in progress. Pending: run all 15 PPT
  images with the latest fixes, write `docs/mvp-validation-report.md`,
  decide v0.2 priorities.
- Next obvious work item after validation: design v0.2's user-editing GUI
  (design.md §4.2 module ⑤). Stack: FastAPI + Konva.js per the plan.
