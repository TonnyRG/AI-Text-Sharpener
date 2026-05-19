"""Export a review project to a flat-image PPTX (one rendered slide per page)."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .project import (
    ReviewProjectItem,
    load_review_project,
    resolve_project_path,
)

EMU_PER_INCH = 914400
DEFAULT_SLIDE_WIDTH_INCHES = 13.333  # standard PPT 16:9 width


def _resolve_render_path(project_path: Path, item: ReviewProjectItem) -> Path:
    """Return the best available rendered PNG: final, falling back to draft."""
    for value in (item.output_png, item.draft_png):
        if not value:
            continue
        candidate = resolve_project_path(project_path, value)
        if candidate.exists():
            return candidate
    raise RuntimeError(
        f"No rendered PNG for slide {item.id} ({item.name}). "
        "Click Render in the editor before exporting."
    )


def export_project_to_pptx(
    project_path: Path,
    output_pptx: Path,
    slide_width_inches: float = DEFAULT_SLIDE_WIDTH_INCHES,
) -> Path:
    """Write a flat-image PPTX where each slide is the rendered PNG full-bleed.

    Slide size = ``slide_width_inches`` × (height derived from first image's
    aspect ratio).  PPT decks require a single slide size for all pages, so the
    first slide's aspect ratio wins.  Standard PPT 16:9 width is 13.333 inches.
    """
    from pptx import Presentation

    project_path = Path(project_path)
    output_pptx = Path(output_pptx)
    project = load_review_project(project_path)
    if not project.items:
        raise RuntimeError(f"Project has no items: {project_path}")

    images = [(item, _resolve_render_path(project_path, item)) for item in project.items]

    with Image.open(images[0][1]) as im:
        first_w, first_h = im.size
    slide_w_emu = int(slide_width_inches * EMU_PER_INCH)
    slide_h_emu = int(slide_w_emu * first_h / first_w)

    prs = Presentation()
    prs.slide_width = slide_w_emu
    prs.slide_height = slide_h_emu

    blank_layout = prs.slide_layouts[6]
    for _, png in images:
        slide = prs.slides.add_slide(blank_layout)
        slide.shapes.add_picture(
            str(png), 0, 0, width=prs.slide_width, height=prs.slide_height,
        )

    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_pptx))
    return output_pptx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a review project to a flat-image PPTX."
    )
    parser.add_argument("project_path", type=Path)
    parser.add_argument("--output", "-o", type=Path, default=None)
    parser.add_argument(
        "--width-inches", type=float, default=DEFAULT_SLIDE_WIDTH_INCHES,
        help="Slide width in inches (default 13.333 = standard 16:9).",
    )
    args = parser.parse_args()

    if not args.project_path.exists():
        raise SystemExit(f"Project file not found: {args.project_path}")

    output = args.output or args.project_path.parent / (
        args.project_path.stem + "_export.pptx"
    )
    result = export_project_to_pptx(
        args.project_path, output, slide_width_inches=args.width_inches,
    )
    print(f"PPTX -> {result}")


if __name__ == "__main__":
    main()
