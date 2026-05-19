"""End-to-end pipeline: image -> editable plan -> PNG + SVG."""
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

from .detect import detect_text
from .erase import soft_erase
from .fonts import FontSpec, assign_fonts, prepare_render_font_dirs
from .merge import merge_horizontal_neighbors
from .rasterize import svg_to_png
from .review import EditableRegion, ReviewDocument
from .style import bbox_to_rect, extract_style
from .svg_gen import TextElement, TextSpan as SvgSpan, generate_svg


def estimate_text_width(text: str, font_size_px: int) -> float:
    """Heuristic rendered width: CJK / full-width ≈ 1.0em, Latin ≈ 0.55em."""
    width = 0.0
    for ch in text or "":
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3000 <= cp <= 0x33FF) or \
           (0x3400 <= cp <= 0x4DBF) or (0xAC00 <= cp <= 0xD7AF) or \
           (0xFF00 <= cp <= 0xFFEF):
            width += font_size_px * 1.0
        elif ch == " ":
            width += font_size_px * 0.3
        else:
            width += font_size_px * 0.55
    return width


def fit_font_size_to_bbox(region, tolerance: float = 1.05) -> bool:
    """Shrink ``region.font_size_px`` (and any explicit span sizes) so rendered
    width fits within bbox × tolerance.  Only shrinks; never expands.  Returns
    True when the region was modified.
    """
    _, _, w, _ = bbox_to_rect(region.bbox)
    if w <= 0:
        return False
    if region.spans:
        total = sum(
            estimate_text_width(s.text or "", s.font_size_px or region.font_size_px)
            for s in region.spans
        )
    else:
        total = estimate_text_width(region.text or "", region.font_size_px)
    if total <= 0 or total <= w * tolerance:
        return False
    ratio = w / total
    region.font_size_px = max(8, int(region.font_size_px * ratio))
    for s in (region.spans or []):
        if s.font_size_px is not None:
            s.font_size_px = max(8, int(s.font_size_px * ratio))
    return True


def fit_font_sizes_to_bboxes(regions, tolerance: float = 1.05) -> int:
    """Apply ``fit_font_size_to_bbox`` to every region. Returns change count."""
    return sum(1 for r in regions if fit_font_size_to_bbox(r, tolerance))


def auto_align_left_groups(
    regions: list,
    tolerance_px: int = 15,
    min_group_size: int = 3,
) -> int:
    """Set ``text_anchor='left'`` for regions whose bbox left edges align.

    Two regions are considered aligned if their bbox lefts are within
    ``tolerance_px``.  A region joins a left-aligned group when at least
    ``min_group_size`` regions share that left edge (covers a typical bullet
    list).  Mutates ``regions`` in place; returns the count switched to left.
    """
    lefts = [(bbox_to_rect(r.bbox)[0], r) for r in regions]
    switched = 0
    for li, ri in lefts:
        group = [r for l, r in lefts if abs(l - li) <= tolerance_px]
        if len(group) >= min_group_size:
            ri.text_anchor = "left"
            ri.x = li
            switched += 1
    return switched


def analyze_image(
    input_path: Path,
    font_spec: FontSpec,
    min_height_ratio: float = 0.025,
    min_height_px_cap: int = 50,
    max_font_ratio: float = 0.05,
) -> ReviewDocument:
    """Detect text and return an editable replacement plan."""
    pil_img = Image.open(input_path).convert("RGB")
    img = np.array(pil_img)
    h, w = img.shape[:2]

    regions = detect_text(str(input_path))
    if not regions:
        raise RuntimeError(f"No text detected in {input_path}")

    # min_height_ratio was calibrated for ~1080p (27px). For high-res images (8000px+)
    # the threshold balloons to 112px, silently dropping bullet-point text (~60px).
    # Cap prevents this while keeping the crests-are-too-small behaviour on normal images.
    min_h = min(h * min_height_ratio, min_height_px_cap)
    regions = [r for r in regions if (bbox_to_rect(r.bbox)[3]) >= min_h]
    if not regions:
        raise RuntimeError(f"All detected regions were filtered out for {input_path}")

    regions = merge_horizontal_neighbors(regions)
    styled = [(r, extract_style(img, r)) for r in regions]
    sizes = [s.font_size_px for _, s in styled]
    font_families = assign_fonts(sizes, font_spec)
    font_size_cap = int(h * max_font_ratio)

    editable_regions = []
    for idx, ((region, style), family) in enumerate(zip(styled, font_families), start=1):
        x, y, rw, rh = bbox_to_rect(region.bbox)
        weight = "bold" if family.lower().endswith(("bold", "black")) else "normal"
        font_family = family.replace(" Bold", "").replace(" Black", "")
        editable_regions.append(EditableRegion(
            id=f"r{idx:03d}",
            bbox=region.bbox,
            original_text=region.text,
            text=region.text,
            confidence=region.confidence,
            replace=True,
            x=x + rw // 2,
            y=y + rh // 2,
            font_family=font_family,
            font_size_px=min(style.font_size_px, font_size_cap),
            font_weight=weight,
            letter_spacing_px=0.0,
            color=style.color,
            background=style.background,
        ))

    auto_align_left_groups(editable_regions)
    fit_font_sizes_to_bboxes(editable_regions)

    return ReviewDocument(
        source_image=str(input_path),
        image_width=w,
        image_height=h,
        regions=editable_regions,
    )


def render_review_document(
    input_path: Path,
    output_png: Path,
    output_svg: Path,
    review: ReviewDocument,
    fonts_dir: Path | None = None,
) -> None:
    """Render PNG/SVG from an edited review document."""
    pil_img = Image.open(input_path).convert("RGB")
    img = np.array(pil_img)
    h, w = img.shape[:2]

    if (w, h) != (review.image_width, review.image_height):
        raise ValueError(
            "Review image dimensions do not match input image: "
            f"review={review.image_width}x{review.image_height}, input={w}x{h}"
        )

    active_regions = [region for region in review.regions if region.replace]
    erased = soft_erase(
        img,
        [(region.to_text_region(), region.to_region_style()) for region in active_regions],
    )

    texts = [
        TextElement(
            x=region.x,
            y=region.y,
            text=region.text,
            font_family=region.font_family,
            font_size_px=region.font_size_px,
            color=region.color,
            font_weight=region.font_weight,
            letter_spacing_px=region.letter_spacing_px,
            text_anchor=region.text_anchor,
            spans=[
                SvgSpan(
                    text=s.text,
                    color=s.color,
                    font_size_px=s.font_size_px,
                    font_family=s.font_family,
                    font_weight=s.font_weight,
                    vertical_align=s.vertical_align,
                )
                for s in region.spans
            ],
        )
        for region in active_regions
    ]

    buf = io.BytesIO()
    Image.fromarray(erased).save(buf, format="PNG")
    bg_b64 = base64.b64encode(buf.getvalue()).decode()

    svg_text = generate_svg(w, h, bg_b64, texts)
    Path(output_svg).write_text(svg_text, encoding="utf-8")
    svg_to_png(
        svg_text,
        output_png,
        font_dirs=prepare_render_font_dirs(
            fonts_dir,
            [
                family
                for region in active_regions
                for family in [region.font_family] + [s.font_family for s in region.spans if s.font_family]
            ],
        ),
    )


def sharpen_image(
    input_path: Path,
    output_png: Path,
    output_svg: Path,
    font_spec: FontSpec,
    min_height_ratio: float = 0.025,
    min_height_px_cap: int = 50,
    max_font_ratio: float = 0.05,
) -> None:
    review = analyze_image(
        input_path=input_path,
        font_spec=font_spec,
        min_height_ratio=min_height_ratio,
        min_height_px_cap=min_height_px_cap,
        max_font_ratio=max_font_ratio,
    )
    render_review_document(input_path, output_png, output_svg, review)
