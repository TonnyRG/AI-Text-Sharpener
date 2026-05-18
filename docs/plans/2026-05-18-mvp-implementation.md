# AI Text Sharpener MVP 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现一个命令行 MVP，输入 AI 生成的图片 + 字体清单，输出文字部分被锐利矢量文字替换的 PNG 和 SVG。

**Architecture:** Python CLI 工具，使用 PaddleOCR 检测文字 + 经典图像处理软擦除 + 直接生成 SVG 叠加层。MVP 不含 Web UI，先打通核心管线。

**Tech Stack:** Python 3.11 / PaddleOCR / Pillow / OpenCV / resvg-py / Click / pytest

**Reference design:** [2026-05-18-design.md](./2026-05-18-design.md)

**Project root:** `E:\Project\Shiny-PreADME项目辅助\AI-Text-Sharpener\`

---

## 范围说明

**MVP 包含**：
- 单张图片 CLI 处理
- PaddleOCR 中英文（含数字、符号）检测识别
- 文字样式提取（颜色、字号、背景色）
- 软擦除（无神经 inpainting）
- 用户预指定字体（标题/正文，按字号阈值自动分配）
- 输出 PNG（扁平化）和 SVG（可编辑）

**MVP 不包含**（推后到 v0.2+）：
- Web UI、批量处理、Vision LLM 兜底、PPTX 输出、特效复刻、Docker

**验收标准**：
- 用 `E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\` 下 15 张图测试
- OCR 准确率 ≥ 95%（中英文）
- 位置偏差 ≤ 3 像素
- 单张处理时间 ≤ 30 秒（CPU 也可接受 60 秒）
- 主观盲测 ≥ 80% 人认为锐化后更优

---

## Task 1: 项目骨架与环境

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.gitignore`
- Create: `src/ai_text_sharpener/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/.gitkeep`

**Step 1: 创建项目目录与 git 初始化**

```bash
cd "E:\Project\Shiny-PreADME项目辅助\AI-Text-Sharpener"
mkdir -p src/ai_text_sharpener tests/fixtures
git init
```

**Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "ai-text-sharpener"
version = "0.1.0"
description = "Replace blurry text in AI-generated images with crisp vector text"
requires-python = ">=3.11"
authors = [{name = "Li Nanzun", email = "licolinsr@gmail.com"}]
license = {text = "Apache-2.0"}
dependencies = [
    "paddleocr>=2.7.0",
    "paddlepaddle>=2.6.0",
    "pillow>=10.0.0",
    "opencv-python>=4.9.0",
    "numpy>=1.26.0",
    "resvg-py>=0.1.0",
    "click>=8.1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-cov>=4.1.0"]

[project.scripts]
ai-text-sharpener = "ai_text_sharpener.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

**Step 3: 写 `.gitignore`**

```
__pycache__/
*.pyc
*.egg-info/
.venv/
.pytest_cache/
.coverage
htmlcov/
build/
dist/
tests/fixtures/output/
*.log
.DS_Store
```

**Step 4: 写最简 `README.md`**

```markdown
# AI Text Sharpener

Replace blurry text in AI-generated images with crisp vector text.

## Status
v0.1 MVP - 开发中

## Usage
\`\`\`bash
ai-text-sharpener input.jpg -o output.png --title-font "Microsoft YaHei Bold" --body-font "Microsoft YaHei"
\`\`\`

See [docs/plans/](docs/plans/) for design and implementation plans.
```

**Step 5: 写 `src/ai_text_sharpener/__init__.py`**

```python
__version__ = "0.1.0"
```

**Step 6: 写 `tests/conftest.py`**

```python
import shutil
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_IMAGES = Path(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra")


@pytest.fixture(scope="session")
def sample_image_path():
    """Return path to a representative sample image (image1.jpg - cover page)."""
    src = SAMPLE_IMAGES / "image1.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src


@pytest.fixture(scope="session")
def sample_image_chart():
    """Return path to a chart-containing image (image10.jpg)."""
    src = SAMPLE_IMAGES / "image10.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src
```

**Step 7: 创建虚拟环境并安装依赖**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**预期**：所有依赖安装成功。**注意**：PaddleOCR 首次安装在 Windows 上较大（~2GB），需要时间。

**Step 8: 验证环境**

```bash
python -c "import paddleocr, cv2, PIL, click, resvg_py; print('OK')"
pytest --collect-only
```

**预期**：`OK` 输出 + pytest 无 collection error（即使无测试也算通过）。

**Step 9: Commit**

```bash
git add pyproject.toml README.md .gitignore src/ tests/
git commit -m "chore: bootstrap project skeleton with deps"
```

---

## Task 2: 文字检测模块（detect.py）

**Files:**
- Create: `src/ai_text_sharpener/detect.py`
- Create: `tests/test_detect.py`

**Step 1: 先写失败的测试 `tests/test_detect.py`**

```python
from ai_text_sharpener.detect import detect_text, TextRegion


def test_detect_returns_list_of_regions(sample_image_path):
    regions = detect_text(str(sample_image_path))
    assert isinstance(regions, list)
    assert len(regions) > 0
    assert all(isinstance(r, TextRegion) for r in regions)


def test_text_region_has_required_fields(sample_image_path):
    regions = detect_text(str(sample_image_path))
    r = regions[0]
    assert hasattr(r, "bbox")           # 4 corner points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    assert hasattr(r, "text")           # str
    assert hasattr(r, "confidence")     # 0~1 float
    assert len(r.bbox) == 4
    assert 0.0 <= r.confidence <= 1.0


def test_detect_finds_known_text_on_cover(sample_image_path):
    """image1.jpg 是封面页，应能识别出 'Shiny-preADME' 字样。"""
    regions = detect_text(str(sample_image_path))
    all_text = " ".join(r.text for r in regions)
    assert "Shiny" in all_text or "shiny" in all_text.lower()
    assert "ADME" in all_text.upper()
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_detect.py -v
```

**预期**：`ModuleNotFoundError: No module named 'ai_text_sharpener.detect'`

**Step 3: 实现 `src/ai_text_sharpener/detect.py`**

```python
"""Text detection wrapper around PaddleOCR."""
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from paddleocr import PaddleOCR


@dataclass
class TextRegion:
    bbox: list          # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] in pixels
    text: str
    confidence: float


@lru_cache(maxsize=1)
def _get_ocr() -> PaddleOCR:
    """Lazy-init PaddleOCR (loads ~500MB models on first call)."""
    return PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)


def detect_text(image_path: str) -> List[TextRegion]:
    """Detect all text regions in image. Supports Chinese, English, digits, symbols."""
    ocr = _get_ocr()
    raw = ocr.ocr(image_path, cls=True)

    # PaddleOCR returns [[ [bbox, (text, conf)], ... ]] (one inner list per image)
    if not raw or not raw[0]:
        return []

    return [
        TextRegion(bbox=item[0], text=item[1][0], confidence=float(item[1][1]))
        for item in raw[0]
    ]
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_detect.py -v -s
```

**预期**：3 个测试全部 PASS。**首次运行会下载 PaddleOCR 模型，耗时 1~3 分钟。**

**Step 5: 手动验证检测结果**

写一个一次性脚本 `scripts/debug_detect.py`：

```python
import json
from ai_text_sharpener.detect import detect_text

regions = detect_text(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\image1.jpg")
for r in regions:
    print(f"[{r.confidence:.2f}] {r.text}")
```

运行 `python scripts/debug_detect.py`，**人工检查输出**是否包含封面所有文字（标题、副标题、作者、专业、日期等）。如果遗漏明显，记录问题但不阻塞 Task 3——后面整合时再调优。

**Step 6: Commit**

```bash
git add src/ai_text_sharpener/detect.py tests/test_detect.py scripts/debug_detect.py
git commit -m "feat(detect): add PaddleOCR text detection wrapper"
```

---

## Task 3: 样式提取模块（style.py）

**Files:**
- Create: `src/ai_text_sharpener/style.py`
- Create: `tests/test_style.py`

**Step 1: 写失败的测试**

```python
import numpy as np
from PIL import Image
from ai_text_sharpener.style import (
    extract_style, RegionStyle, bbox_to_rect, sample_text_color, sample_background_color
)
from ai_text_sharpener.detect import TextRegion


def _make_test_image() -> np.ndarray:
    """White 200x100 image with black 'X' shape in center."""
    img = np.full((100, 200, 3), 255, dtype=np.uint8)
    img[40:60, 80:120] = 0  # black block (proxy for text strokes)
    return img


def test_bbox_to_rect_converts_quad_to_axis_aligned():
    quad = [[10, 20], [110, 20], [110, 50], [10, 50]]
    x, y, w, h = bbox_to_rect(quad)
    assert (x, y, w, h) == (10, 20, 100, 30)


def test_sample_text_color_picks_dark_strokes():
    img = _make_test_image()
    rect = (70, 30, 60, 40)  # covers the black block + some white
    rgb = sample_text_color(img, rect)
    # Should be close to black, not white
    assert sum(rgb) < 100  # well below pure white (765)


def test_sample_background_color_picks_outside_border():
    img = _make_test_image()
    rect = (70, 30, 60, 40)
    rgb = sample_background_color(img, rect)
    # Border ring is all white
    assert all(c > 240 for c in rgb)


def test_extract_style_returns_complete_style(sample_image_path):
    from ai_text_sharpener.detect import detect_text
    regions = detect_text(str(sample_image_path))
    img = np.array(Image.open(sample_image_path))
    style = extract_style(img, regions[0])
    assert isinstance(style, RegionStyle)
    assert hasattr(style, "color")        # (r, g, b) 0~255
    assert hasattr(style, "background")   # (r, g, b) 0~255
    assert hasattr(style, "font_size_px") # int
    assert style.font_size_px > 0
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_style.py -v
```

**预期**：`ModuleNotFoundError`

**Step 3: 实现 `src/ai_text_sharpener/style.py`**

```python
"""Extract visual style (color, size, background) from text regions."""
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from .detect import TextRegion

RGB = Tuple[int, int, int]
Rect = Tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class RegionStyle:
    color: RGB
    background: RGB
    font_size_px: int


def bbox_to_rect(bbox) -> Rect:
    """Convert quadrilateral bbox to axis-aligned (x, y, w, h)."""
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    x, y = int(min(xs)), int(min(ys))
    w, h = int(max(xs) - x), int(max(ys) - y)
    return x, y, w, h


def sample_text_color(img: np.ndarray, rect: Rect) -> RGB:
    """Sample text color by taking the median of the darkest 20% pixels in bbox."""
    x, y, w, h = rect
    patch = img[y:y+h, x:x+w]
    if patch.size == 0:
        return (0, 0, 0)
    # Use luminance to find dark pixels (text strokes)
    lum = patch.mean(axis=2)
    threshold = np.percentile(lum, 20)
    mask = lum <= threshold
    if not mask.any():
        return tuple(int(c) for c in patch.reshape(-1, 3).mean(axis=0))
    dark_pixels = patch[mask]
    return tuple(int(c) for c in np.median(dark_pixels, axis=0))


def sample_background_color(img: np.ndarray, rect: Rect, ring_px: int = 3) -> RGB:
    """Sample background by taking median color in a ring just outside the bbox."""
    h_img, w_img = img.shape[:2]
    x, y, w, h = rect
    x0, y0 = max(0, x - ring_px), max(0, y - ring_px)
    x1, y1 = min(w_img, x + w + ring_px), min(h_img, y + h + ring_px)
    outer = img[y0:y1, x0:x1].copy()
    # Mask out the inner bbox region
    inner_x0, inner_y0 = x - x0, y - y0
    outer[inner_y0:inner_y0 + h, inner_x0:inner_x0 + w] = 0
    # Use non-zero pixels only
    flat = outer.reshape(-1, 3)
    mask = flat.any(axis=1)
    if not mask.any():
        return (255, 255, 255)
    return tuple(int(c) for c in np.median(flat[mask], axis=0))


def extract_style(img: np.ndarray, region: TextRegion) -> RegionStyle:
    rect = bbox_to_rect(region.bbox)
    return RegionStyle(
        color=sample_text_color(img, rect),
        background=sample_background_color(img, rect),
        font_size_px=int(rect[3] * 0.85),
    )
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_style.py -v
```

**预期**：4 个测试全部 PASS。

**Step 5: Commit**

```bash
git add src/ai_text_sharpener/style.py tests/test_style.py
git commit -m "feat(style): extract color/background/font-size per region"
```

---

## Task 4: 软擦除模块（erase.py）

**Files:**
- Create: `src/ai_text_sharpener/erase.py`
- Create: `tests/test_erase.py`

**Step 1: 写失败的测试**

```python
import numpy as np
from ai_text_sharpener.erase import soft_erase
from ai_text_sharpener.style import RegionStyle
from ai_text_sharpener.detect import TextRegion


def test_soft_erase_fills_bbox_with_background():
    img = np.full((100, 200, 3), 255, dtype=np.uint8)
    img[40:60, 80:120] = 0  # "text"
    region = TextRegion(
        bbox=[[80, 40], [120, 40], [120, 60], [80, 60]],
        text="X",
        confidence=1.0,
    )
    style = RegionStyle(color=(0, 0, 0), background=(255, 255, 255), font_size_px=20)
    result = soft_erase(img, [(region, style)])
    # The center of the bbox should no longer be black
    center_pixel = result[50, 100]
    assert center_pixel.mean() > 200  # was 0, should be ~background (255)


def test_soft_erase_preserves_outside_bbox():
    img = np.full((100, 200, 3), 128, dtype=np.uint8)
    img[40:60, 80:120] = 0
    region = TextRegion(
        bbox=[[80, 40], [120, 40], [120, 60], [80, 60]],
        text="X", confidence=1.0,
    )
    style = RegionStyle(color=(0, 0, 0), background=(255, 255, 255), font_size_px=20)
    result = soft_erase(img, [(region, style)])
    # Far from bbox should be untouched
    assert result[10, 10].tolist() == [128, 128, 128]
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_erase.py -v
```

**Step 3: 实现 `src/ai_text_sharpener/erase.py`**

```python
"""Soft erase: fill text bboxes with background color and feather edges."""
from typing import List, Tuple

import cv2
import numpy as np

from .detect import TextRegion
from .style import RegionStyle, bbox_to_rect


def soft_erase(
    img: np.ndarray,
    regions: List[Tuple[TextRegion, RegionStyle]],
    feather_px: int = 4,
) -> np.ndarray:
    """Return a copy of img with each text region's bbox filled by its background color.

    Edges are feathered using Gaussian blur to avoid visible color patches when the
    background has gradients/textures.
    """
    out = img.copy()
    h_img, w_img = img.shape[:2]

    for region, style in regions:
        x, y, w, h = bbox_to_rect(region.bbox)
        # Clip to image bounds
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w_img, x + w), min(h_img, y + h)
        if x1 <= x0 or y1 <= y0:
            continue

        # Create background-colored patch
        patch = np.full((y1 - y0, x1 - x0, 3), style.background, dtype=np.uint8)

        # Build feather alpha mask: 1.0 inside, fades to 0 at edges over feather_px
        mask = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        if feather_px > 0:
            mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=feather_px, sigmaY=feather_px)
            mask = np.clip(mask, 0, 1)

        # Blend: out = patch * mask + out * (1 - mask)
        alpha = mask[..., None]
        out[y0:y1, x0:x1] = (patch * alpha + out[y0:y1, x0:x1] * (1 - alpha)).astype(np.uint8)

    return out
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_erase.py -v
```

**Step 5: 手动可视化验证**

更新 `scripts/debug_detect.py` 增加擦除步骤，把擦除结果存为 `debug_erased.png`，人工查看是否：
- 文字位置变成背景色
- 边缘平滑不突兀
- 非文字区域完全保留

**Step 6: Commit**

```bash
git add src/ai_text_sharpener/erase.py tests/test_erase.py
git commit -m "feat(erase): soft-erase text regions with feathered background fill"
```

---

## Task 5: 字体分配模块（fonts.py）

**Files:**
- Create: `src/ai_text_sharpener/fonts.py`
- Create: `tests/test_fonts.py`

**Step 1: 写失败的测试**

```python
from ai_text_sharpener.fonts import assign_fonts, FontSpec


def test_assign_fonts_uses_title_for_large_text():
    spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)
    sizes = [60, 30, 80, 20]
    fonts = assign_fonts(sizes, spec)
    assert fonts == [
        "Microsoft YaHei Bold",
        "Microsoft YaHei",
        "Microsoft YaHei Bold",
        "Microsoft YaHei",
    ]


def test_assign_fonts_threshold_inclusive():
    spec = FontSpec(title="T", body="B", title_min_px=40)
    assert assign_fonts([40], spec) == ["T"]
    assert assign_fonts([39], spec) == ["B"]
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_fonts.py -v
```

**Step 3: 实现 `src/ai_text_sharpener/fonts.py`**

```python
"""Assign user-specified fonts to detected regions based on font size threshold."""
from dataclasses import dataclass
from typing import List


@dataclass
class FontSpec:
    title: str
    body: str
    title_min_px: int = 40  # font_size_px >= this -> title font


def assign_fonts(font_sizes_px: List[int], spec: FontSpec) -> List[str]:
    return [spec.title if s >= spec.title_min_px else spec.body for s in font_sizes_px]
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_fonts.py -v
```

**Step 5: Commit**

```bash
git add src/ai_text_sharpener/fonts.py tests/test_fonts.py
git commit -m "feat(fonts): assign title/body fonts by size threshold"
```

---

## Task 6: SVG 生成模块（svg_gen.py）

**Files:**
- Create: `src/ai_text_sharpener/svg_gen.py`
- Create: `tests/test_svg_gen.py`

**Step 1: 写失败的测试**

```python
import base64
import re
from ai_text_sharpener.svg_gen import generate_svg, TextElement


def test_generate_svg_embeds_background_image():
    bg_b64 = base64.b64encode(b"fake-png-bytes").decode()
    svg = generate_svg(width=800, height=600, background_b64=bg_b64, texts=[])
    assert '<svg' in svg
    assert 'width="800"' in svg
    assert 'height="600"' in svg
    assert bg_b64 in svg
    assert 'xlink:href="data:image/png;base64,' in svg


def test_generate_svg_adds_text_elements():
    texts = [
        TextElement(x=100, y=200, text="Hello", font_family="Arial",
                    font_size_px=24, color=(255, 0, 0), font_weight="normal"),
        TextElement(x=300, y=400, text="标题", font_family="Microsoft YaHei",
                    font_size_px=48, color=(0, 0, 0), font_weight="bold"),
    ]
    svg = generate_svg(width=800, height=600, background_b64="x", texts=texts)
    assert "Hello" in svg
    assert "标题" in svg
    assert 'font-family="Arial"' in svg
    assert 'font-family="Microsoft YaHei"' in svg
    assert 'font-weight="bold"' in svg
    assert 'fill="rgb(255,0,0)"' in svg


def test_text_x_is_center_anchored():
    """Text x should be the horizontal center of bbox, with text-anchor=middle."""
    texts = [TextElement(x=400, y=100, text="X", font_family="Arial",
                         font_size_px=20, color=(0,0,0), font_weight="normal")]
    svg = generate_svg(width=800, height=600, background_b64="x", texts=texts)
    assert 'text-anchor="middle"' in svg
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_svg_gen.py -v
```

**Step 3: 实现 `src/ai_text_sharpener/svg_gen.py`**

```python
"""Generate SVG with embedded image background and overlaid text elements."""
from dataclasses import dataclass
from html import escape
from typing import List, Tuple


@dataclass
class TextElement:
    x: int                     # center x (text-anchor=middle)
    y: int                     # baseline y
    text: str
    font_family: str
    font_size_px: int
    color: Tuple[int, int, int]
    font_weight: str = "normal"


_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
    '  <image x="0" y="0" width="{w}" height="{h}" '
    'xlink:href="data:image/png;base64,{bg}"/>\n'
    '{texts}'
    '</svg>\n'
)


def _text_tag(t: TextElement) -> str:
    return (
        f'  <text x="{t.x}" y="{t.y}" '
        f'font-family="{escape(t.font_family)}" '
        f'font-size="{t.font_size_px}" '
        f'font-weight="{t.font_weight}" '
        f'fill="rgb({t.color[0]},{t.color[1]},{t.color[2]})" '
        f'text-anchor="middle" dominant-baseline="middle">'
        f'{escape(t.text)}</text>\n'
    )


def generate_svg(width: int, height: int, background_b64: str,
                 texts: List[TextElement]) -> str:
    return _SVG_TEMPLATE.format(
        w=width, h=height, bg=background_b64,
        texts="".join(_text_tag(t) for t in texts),
    )
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_svg_gen.py -v
```

**Step 5: Commit**

```bash
git add src/ai_text_sharpener/svg_gen.py tests/test_svg_gen.py
git commit -m "feat(svg): generate SVG with image background and text overlays"
```

---

## Task 7: 栅格化模块（rasterize.py）

**Files:**
- Create: `src/ai_text_sharpener/rasterize.py`
- Create: `tests/test_rasterize.py`

**Step 1: 写失败的测试**

```python
from pathlib import Path
from ai_text_sharpener.rasterize import svg_to_png


def test_svg_to_png_produces_valid_png(tmp_path):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
           '<rect width="100" height="50" fill="red"/></svg>')
    out = tmp_path / "out.png"
    svg_to_png(svg, out)
    assert out.exists()
    # PNG magic bytes
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_rasterize.py -v
```

**Step 3: 实现 `src/ai_text_sharpener/rasterize.py`**

```python
"""Rasterize SVG to PNG using resvg."""
from pathlib import Path

import resvg_py


def svg_to_png(svg_text: str, output_path: Path) -> None:
    png_bytes = resvg_py.svg_to_png(svg_text)
    Path(output_path).write_bytes(png_bytes)
```

**注意**：若 `resvg_py` API 与上述不匹配，先 `python -c "import resvg_py; help(resvg_py)"` 查看实际 API，调整调用方式。备选库：`cairosvg`（更老但 API 稳定）。

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_rasterize.py -v
```

**Step 5: Commit**

```bash
git add src/ai_text_sharpener/rasterize.py tests/test_rasterize.py
git commit -m "feat(rasterize): convert SVG to PNG via resvg"
```

---

## Task 8: 管线整合（pipeline.py）+ CLI（cli.py）

**Files:**
- Create: `src/ai_text_sharpener/pipeline.py`
- Create: `src/ai_text_sharpener/cli.py`
- Create: `tests/test_pipeline.py`

**Step 1: 写集成测试**

```python
from pathlib import Path
from ai_text_sharpener.pipeline import sharpen_image
from ai_text_sharpener.fonts import FontSpec


def test_sharpen_image_end_to_end(sample_image_path, tmp_path):
    spec = FontSpec(title="Microsoft YaHei", body="Microsoft YaHei", title_min_px=40)
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"

    sharpen_image(sample_image_path, out_png, out_svg, font_spec=spec)

    assert out_png.exists()
    assert out_png.stat().st_size > 1000
    assert out_svg.exists()
    svg_text = out_svg.read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert "<text" in svg_text
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_pipeline.py -v
```

**Step 3: 实现 `src/ai_text_sharpener/pipeline.py`**

```python
"""End-to-end pipeline: image -> sharpened PNG + editable SVG."""
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

from .detect import detect_text
from .erase import soft_erase
from .fonts import FontSpec, assign_fonts
from .rasterize import svg_to_png
from .style import bbox_to_rect, extract_style
from .svg_gen import TextElement, generate_svg


def sharpen_image(
    input_path: Path,
    output_png: Path,
    output_svg: Path,
    font_spec: FontSpec,
) -> None:
    # Load image as RGB numpy array
    pil_img = Image.open(input_path).convert("RGB")
    img = np.array(pil_img)
    h, w = img.shape[:2]

    # 1. Detect text
    regions = detect_text(str(input_path))
    if not regions:
        raise RuntimeError(f"No text detected in {input_path}")

    # 2. Extract style per region
    styled = [(r, extract_style(img, r)) for r in regions]

    # 3. Soft-erase
    erased = soft_erase(img, styled)

    # 4. Assign fonts by size
    sizes = [s.font_size_px for _, s in styled]
    font_families = assign_fonts(sizes, font_spec)

    # 5. Build text elements (center-anchored)
    texts = []
    for (region, style), family in zip(styled, font_families):
        x, y, rw, rh = bbox_to_rect(region.bbox)
        weight = "bold" if family.lower().endswith(("bold", "black")) else "normal"
        texts.append(TextElement(
            x=x + rw // 2,
            y=y + rh // 2,
            text=region.text,
            font_family=family.replace(" Bold", "").replace(" Black", ""),
            font_size_px=style.font_size_px,
            color=style.color,
            font_weight=weight,
        ))

    # 6. Encode erased image as base64 PNG for SVG embedding
    buf = io.BytesIO()
    Image.fromarray(erased).save(buf, format="PNG")
    bg_b64 = base64.b64encode(buf.getvalue()).decode()

    # 7. Generate SVG
    svg_text = generate_svg(w, h, bg_b64, texts)
    Path(output_svg).write_text(svg_text, encoding="utf-8")

    # 8. Rasterize to PNG
    svg_to_png(svg_text, output_png)
```

**Step 4: 实现 `src/ai_text_sharpener/cli.py`**

```python
"""CLI entry point."""
from pathlib import Path

import click

from .fonts import FontSpec
from .pipeline import sharpen_image


@click.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output-png", required=True, type=click.Path(path_type=Path))
@click.option("--svg", "output_svg", type=click.Path(path_type=Path), default=None,
              help="SVG output path (default: <output-png>.svg)")
@click.option("--title-font", default="Microsoft YaHei Bold", show_default=True)
@click.option("--body-font", default="Microsoft YaHei", show_default=True)
@click.option("--title-min-px", default=40, show_default=True, type=int,
              help="Font size threshold (px) for title vs body")
def main(input_path, output_png, output_svg, title_font, body_font, title_min_px):
    """Replace blurry text in an AI-generated image with crisp vector text."""
    if output_svg is None:
        output_svg = output_png.with_suffix(".svg")
    spec = FontSpec(title=title_font, body=body_font, title_min_px=title_min_px)
    click.echo(f"Processing {input_path} ...")
    sharpen_image(input_path, output_png, output_svg, spec)
    click.echo(f"OK -> {output_png}  +  {output_svg}")


if __name__ == "__main__":
    main()
```

**Step 5: 运行集成测试确认通过**

```bash
pytest tests/test_pipeline.py -v -s
```

**Step 6: 手动跑一遍 CLI**

```bash
ai-text-sharpener "E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\image1.jpg" -o "out_image1.png"
```

**预期**：生成 `out_image1.png` 和 `out_image1.svg`，**人工检查**：
- 文字位置是否对齐
- 字体是否锐利
- 是否有明显错位/缺失/光晕

记录所有发现的问题，但不要立刻修——先把所有 15 张图跑一遍看整体表现。

**Step 7: Commit**

```bash
git add src/ai_text_sharpener/pipeline.py src/ai_text_sharpener/cli.py tests/test_pipeline.py
git commit -m "feat(cli): integrate pipeline and add CLI entry point"
```

---

## Task 9: 批量验证 + 问题清单

**Files:**
- Create: `scripts/run_all.py`
- Create: `examples/before_after/.gitkeep`
- Create: `docs/mvp-validation-report.md`

**Step 1: 写批处理脚本 `scripts/run_all.py`**

```python
"""Process all 15 PPT images and produce side-by-side comparison."""
import shutil
from pathlib import Path

from ai_text_sharpener.fonts import FontSpec
from ai_text_sharpener.pipeline import sharpen_image

SRC = Path(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra")
DST = Path("examples/before_after")
DST.mkdir(parents=True, exist_ok=True)

spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)

for img_path in sorted(SRC.glob("*.jpg")):
    print(f"Processing {img_path.name} ...")
    out_png = DST / f"{img_path.stem}_sharpened.png"
    out_svg = DST / f"{img_path.stem}_sharpened.svg"
    shutil.copy(img_path, DST / f"{img_path.stem}_original.jpg")
    try:
        sharpen_image(img_path, out_png, out_svg, spec)
        print(f"  OK")
    except Exception as e:
        print(f"  FAILED: {e}")
```

**Step 2: 运行批处理**

```bash
python scripts/run_all.py
```

**预期**：处理完 15 张图片，输出到 `examples/before_after/`，每张图有 3 个文件（原图 + 锐化 PNG + SVG）。

**Step 3: 人工评估**

打开 `examples/before_after/` 文件夹，对每张图前后对比。在 `docs/mvp-validation-report.md` 中按以下模板记录：

```markdown
# MVP 验证报告 — 2026-MM-DD

## 整体观感
[盲测前后对比，主观打分 1~10]

## 单图问题清单
| 图号 | 问题 | 严重度 | 是否阻塞 v0.1 |
|---|---|---|---|
| image1 | "Shiny" 识别为 "Shing"，置信度 0.6 | 中 | 否（v0.2 加 LLM 兜底） |
| image5 | 圆形标号内"5"被替换，位置错位 | 高 | 是（v0.1 需要白名单） |
| ... | | | |

## 验收达成情况
- OCR 准确率：__% （目标 ≥95%）
- 位置偏差：__px （目标 ≤3px）
- 处理时间：__秒/张（目标 ≤30s）

## 后续动作
- [ ] 必须修复（v0.1 内）
- [ ] 推到 v0.2
- [ ] 推到 v1.0
```

**Step 4: Commit 验证产物（不包含大文件 PNG）**

```bash
# 只 commit 报告，不 commit 生成的 png/svg（添加到 .gitignore）
echo "examples/before_after/*.png" >> .gitignore
echo "examples/before_after/*.svg" >> .gitignore
echo "examples/before_after/*.jpg" >> .gitignore
git add scripts/run_all.py docs/mvp-validation-report.md .gitignore
git commit -m "docs: add MVP validation report from 15 PPT images"
```

**Step 5: 决策点**

基于验证报告决定下一步：
- **效果达标** → 进入 v0.2（Web UI、批量处理、字体智能推荐）
- **效果有缺陷但方向对** → 修复阻塞问题后再决定
- **方向有根本问题** → 回到设计阶段重新评估

---

## 总体提醒

### TDD 纪律
每个任务严格按 **"写测试 → 看失败 → 写实现 → 看通过 → commit"** 顺序，**不要跳步**。即使是简单功能，也要先写测试——这会迫使你思考接口设计。

### 提交频率
每个 Task 至少一个 commit。如果一个 Task 内有多个明显独立的逻辑变更（比如改了多个不相关文件），可以分多个 commit。

### 不要做的事
- ❌ 在 MVP 阶段加任何"以防万一"的功能（重试、降级、多语言、配置文件等）
- ❌ 优化性能（先跑通，30s/张也可接受）
- ❌ 加日志框架（用 `click.echo` 或 `print` 即可）
- ❌ 加 Web UI（v0.2 才做）
- ❌ 在 README/docs 里写没实现的承诺

### 卡住时
- PaddleOCR 在 Windows 上装不上 → 改用 EasyOCR（接口类似）作为备选
- resvg_py 装不上 → 改用 cairosvg
- 中文字体在 SVG 里渲染乱码 → 确认字体文件存在（Windows 自带 msyh.ttc），并在 SVG 中正确引用字体名

---

## 时间预估

| Task | 预估 |
|---|---|
| 1. 项目骨架 | 30 min（含 PaddleOCR 下载） |
| 2. 文字检测 | 1.5 hr |
| 3. 样式提取 | 1.5 hr |
| 4. 软擦除 | 1 hr |
| 5. 字体分配 | 30 min |
| 6. SVG 生成 | 1 hr |
| 7. 栅格化 | 30 min |
| 8. 管线 + CLI | 1.5 hr |
| 9. 批量验证 | 1 hr（处理 + 评估） |
| **总计** | **~9 小时** |

可以分 2~3 天做完，每天 3~4 小时。
