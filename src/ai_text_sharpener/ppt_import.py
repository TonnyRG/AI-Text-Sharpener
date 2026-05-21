"""Import PowerPoint decks into editable review projects."""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Iterable, List

from .fonts import FontSpec
from .pipeline import analyze_image, render_review_document
from .project import (
    ReviewProject,
    ReviewProjectItem,
    project_relative_path,
    write_review_project,
)
from .review import ReviewDocument, write_review_document

Analyzer = Callable[[Path, FontSpec], ReviewDocument]
Renderer = Callable[[Path, Path, Path, ReviewDocument], None]
Exporter = Callable[[Path, Path], List[Path]]


DEFAULT_EXPORT_LONG_SIDE_PX = 4000  # ~300 DPI for a 13.3" widescreen slide


def export_ppt_slides_with_powerpoint(
    ppt_path: Path,
    slides_dir: Path,
    long_side_px: int = DEFAULT_EXPORT_LONG_SIDE_PX,
) -> List[Path]:
    """Export each slide to a JPG using Microsoft PowerPoint COM automation.

    ``long_side_px`` controls the export resolution; PowerPoint's default
    (~960px wide) is too coarse for OCR on detailed slides.  We request a
    pixel size where the slide's long edge ≈ ``long_side_px`` so small body
    text remains crisp enough for PaddleOCR.

    Initializes COM for the calling thread; required when invoked from an HTTP
    worker thread (the editor's ThreadingHTTPServer).  CLI main-thread callers
    would have COM auto-initialized by win32com, but it's harmless to call
    CoInitialize on a thread that already has it — it just bumps the refcount.
    """
    try:
        import win32com.client  # type: ignore[import-not-found]
        import pythoncom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "PPT import on Windows requires pywin32. "
            "Install it with: python -m pip install pywin32"
        ) from exc

    ppt_path = Path(ppt_path).resolve()
    slides_dir = Path(slides_dir)
    slides_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    try:
        app = None
        presentation = None
        with tempfile.TemporaryDirectory(prefix="ppt_export_", dir=str(slides_dir.parent)) as tmp:
            # PowerPoint's Export() interprets relative paths against its own
            # working directory (usually My Documents), so the JPGs land
            # outside our temp dir.  Resolve to absolute up-front.
            export_dir = Path(tmp).resolve()
            try:
                app = win32com.client.DispatchEx("PowerPoint.Application")
                presentation = app.Presentations.Open(str(ppt_path), WithWindow=False)
                # Compute pixel size so the slide's long side ≈ long_side_px.
                # PageSetup.SlideWidth/Height are in points (1 pt = 1/72 inch).
                slide_w_pt = presentation.PageSetup.SlideWidth
                slide_h_pt = presentation.PageSetup.SlideHeight
                long_pt = max(slide_w_pt, slide_h_pt) or 720
                scale = long_side_px / long_pt
                scale_w = int(round(slide_w_pt * scale))
                scale_h = int(round(slide_h_pt * scale))
                presentation.Export(str(export_dir), "JPG", scale_w, scale_h)
            except Exception as exc:
                raise RuntimeError(f"PowerPoint slide export failed: {exc}") from exc
            finally:
                if presentation is not None:
                    presentation.Close()
                if app is not None:
                    app.Quit()

            exported = _sort_powerpoint_exports(export_dir.glob("*.jpg"))
            if not exported:
                exported = _sort_powerpoint_exports(export_dir.glob("*.JPG"))
            if not exported:
                raise RuntimeError("PowerPoint did not produce slide images")

            slide_paths = []
            for index, exported_path in enumerate(exported, start=1):
                target = slides_dir / f"slide_{index:03d}.jpg"
                shutil.copy2(exported_path, target)
                slide_paths.append(target)
            return slide_paths
    finally:
        pythoncom.CoUninitialize()


def create_ppt_review_project(
    ppt_path: Path,
    output_dir: Path,
    font_spec: FontSpec,
    exporter: Exporter = export_ppt_slides_with_powerpoint,
    analyzer: Analyzer = analyze_image,
    renderer: Renderer = render_review_document,
) -> Path:
    """Export a PPT deck, analyze each slide, and write a review project."""
    ppt_path = Path(ppt_path)
    output_dir = Path(output_dir)
    slides_dir = output_dir / "slides"
    reviews_dir = output_dir / "reviews"
    drafts_dir = output_dir / "drafts"
    finals_dir = output_dir / "finals"
    for directory in [slides_dir, reviews_dir, drafts_dir, finals_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    slide_paths = exporter(ppt_path, slides_dir)
    if not slide_paths:
        raise RuntimeError(f"No slides were exported from: {ppt_path}")

    items = []
    for index, slide_path in enumerate(slide_paths, start=1):
        slide_id = f"slide-{index:03d}"
        stem = f"slide_{index:03d}"
        review_path = reviews_dir / f"{stem}_review.json"
        draft_png = drafts_dir / f"{stem}_draft.png"
        draft_svg = drafts_dir / f"{stem}_draft.svg"
        final_png = finals_dir / f"{stem}_final.png"
        final_svg = finals_dir / f"{stem}_final.svg"

        review = analyzer(slide_path, font_spec)
        review.source_image = str(slide_path)
        write_review_document(review, review_path)
        renderer(slide_path, draft_png, draft_svg, review)

        items.append(
            ReviewProjectItem(
                id=slide_id,
                name=f"Slide {index}",
                image_path=project_relative_path(output_dir, slide_path),
                review_path=project_relative_path(output_dir, review_path),
                output_png=project_relative_path(output_dir, final_png),
                output_svg=project_relative_path(output_dir, final_svg),
                draft_png=project_relative_path(output_dir, draft_png),
                draft_svg=project_relative_path(output_dir, draft_svg),
            )
        )

    project = ReviewProject(
        source_ppt=str(ppt_path),
        items=items,
    )
    project_path = output_dir / "review_project.json"
    write_review_project(project, project_path)
    return project_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a PPT/PPTX deck for review editing.")
    parser.add_argument("ppt_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--title-font", default="Microsoft YaHei Bold")
    parser.add_argument("--body-font", default="Microsoft YaHei")
    parser.add_argument("--title-min-px", type=int, default=40)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--no-open-editor", action="store_true")
    args = parser.parse_args()

    if not args.ppt_path.exists():
        raise SystemExit(f"PPT file not found: {args.ppt_path}")

    output_dir = args.output_dir or Path("examples") / "ppt_reviews" / args.ppt_path.stem
    spec = FontSpec(
        title=args.title_font,
        body=args.body_font,
        title_min_px=args.title_min_px,
    )
    project_path = create_ppt_review_project(args.ppt_path, output_dir, spec)
    print(f"Review project -> {project_path}")

    if args.no_open_editor:
        return

    from .editor import serve_editor

    serve_editor(
        host=args.host,
        port=args.port,
        project_path=project_path,
        open_browser=not args.no_open,
    )


def _sort_powerpoint_exports(paths: Iterable[Path]) -> List[Path]:
    def key(path: Path) -> tuple[int, str]:
        digits = "".join(ch for ch in path.stem if ch.isdigit())
        return (int(digits), path.name) if digits else (9999, path.name)

    return sorted(paths, key=key)


if __name__ == "__main__":
    main()
