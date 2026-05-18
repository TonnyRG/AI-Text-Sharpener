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
    pil_img = Image.open(input_path).convert("RGB")
    img = np.array(pil_img)
    h, w = img.shape[:2]

    regions = detect_text(str(input_path))
    if not regions:
        raise RuntimeError(f"No text detected in {input_path}")

    styled = [(r, extract_style(img, r)) for r in regions]

    erased = soft_erase(img, styled)

    sizes = [s.font_size_px for _, s in styled]
    font_families = assign_fonts(sizes, font_spec)

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

    buf = io.BytesIO()
    Image.fromarray(erased).save(buf, format="PNG")
    bg_b64 = base64.b64encode(buf.getvalue()).decode()

    svg_text = generate_svg(w, h, bg_b64, texts)
    Path(output_svg).write_text(svg_text, encoding="utf-8")

    svg_to_png(svg_text, output_png)
