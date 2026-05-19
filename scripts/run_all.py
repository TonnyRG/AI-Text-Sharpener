"""Build a review queue for the 15 PPT images.

For each source image, this script creates:
- *_original.jpg: copied source image
- *_review.json: editable replacement decisions
- *_draft.png / *_draft.svg: first-pass rendered output
- *_final.png / *_final.svg: target output path for the editor

The generated review_queue.md lists one editor command per image.
"""
import os
import shutil
import time
from pathlib import Path

from ai_text_sharpener.fonts import FontSpec
from ai_text_sharpener.pipeline import analyze_image, render_review_document
from ai_text_sharpener.project import (
    ReviewProject,
    ReviewProjectItem,
    project_relative_path,
    write_review_project,
)
from ai_text_sharpener.review import write_review_document

# Override per machine via ATS_PPT_SRC env var.
SRC = Path(
    os.environ.get("ATS_PPT_SRC")
    or r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra"
)
DST = Path("examples/before_after")
DST.mkdir(parents=True, exist_ok=True)

spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)


def _image_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.stem.removeprefix("image")
    return (int(suffix), path.name) if suffix.isdigit() else (9999, path.name)


def _editor_command(original_path: Path, review_path: Path, output_png: Path) -> str:
    return (
        "ai-text-sharpener-editor "
        f'"{original_path}" "{review_path}" --output-png "{output_png}"'
    )


def _write_queue_report(results: list[dict]) -> None:
    lines = [
        "# Review Queue",
        "",
        "Generated files live in `examples/before_after/`.",
        "",
        "Use each command to open one slide in the local browser editor, then click Save and Render.",
        "",
        "| Image | Status | Regions | Draft | Final | Review JSON | Editor command |",
        "|---|---|---:|---|---|---|---|",
    ]
    for item in results:
        if item["status"] == "OK":
            lines.append(
                "| {name} | {status} | {regions} | `{draft}` | `{final}` | `{review}` | `{command}` |".format(
                    name=item["name"],
                    status=item["status"],
                    regions=item["regions"],
                    draft=item["draft_png"],
                    final=item["final_png"],
                    review=item["review_json"],
                    command=item["command"],
                )
            )
        else:
            lines.append(
                f"| {item['name']} | FAILED: {item['error']} | 0 |  |  |  |  |"
            )
    (DST / "review_queue.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_project_manifest(results: list[dict]) -> None:
    items = []
    for index, item in enumerate((r for r in results if r["status"] == "OK"), start=1):
        stem = Path(item["name"]).stem
        original = DST / f"{stem}_original.jpg"
        final_png = Path(item["final_png"])
        items.append(
            ReviewProjectItem(
                id=f"slide-{index:03d}",
                name=stem,
                image_path=project_relative_path(DST, original),
                review_path=project_relative_path(DST, Path(item["review_json"])),
                output_png=project_relative_path(DST, final_png),
                output_svg=project_relative_path(DST, final_png.with_suffix(".svg")),
                draft_png=project_relative_path(DST, Path(item["draft_png"])),
                draft_svg=project_relative_path(DST, Path(item["draft_png"]).with_suffix(".svg")),
            )
        )
    write_review_project(ReviewProject(items=items), DST / "review_project.json")


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Source directory not found: {SRC}")

    image_paths = sorted(SRC.glob("*.jpg"), key=_image_sort_key)
    if not image_paths:
        raise SystemExit(f"No .jpg files found in: {SRC}")

    t_total_start = time.time()
    results = []

    for img_path in image_paths:
        print(f"\nProcessing {img_path.name} ...", flush=True)
        original = DST / f"{img_path.stem}_original.jpg"
        review_json = DST / f"{img_path.stem}_review.json"
        draft_png = DST / f"{img_path.stem}_draft.png"
        draft_svg = DST / f"{img_path.stem}_draft.svg"
        final_png = DST / f"{img_path.stem}_final.png"
        t0 = time.time()

        try:
            shutil.copy(img_path, original)
            review = analyze_image(img_path, spec)
            review.source_image = str(original)
            write_review_document(review, review_json)
            render_review_document(img_path, draft_png, draft_svg, review)
            dt = time.time() - t0
            command = _editor_command(original, review_json, final_png)
            print(f"  OK  ({dt:.1f}s, {len(review.regions)} regions)", flush=True)
            results.append({
                "name": img_path.name,
                "status": "OK",
                "dt": dt,
                "regions": len(review.regions),
                "draft_png": str(draft_png),
                "final_png": str(final_png),
                "review_json": str(review_json),
                "command": command,
                "error": "",
            })
        except Exception as exc:
            dt = time.time() - t0
            print(f"  FAILED ({dt:.1f}s): {exc}", flush=True)
            results.append({
                "name": img_path.name,
                "status": "FAILED",
                "dt": dt,
                "regions": 0,
                "draft_png": "",
                "final_png": "",
                "review_json": "",
                "command": "",
                "error": str(exc),
            })

    _write_queue_report(results)
    _write_project_manifest(results)

    t_total = time.time() - t_total_start
    print("\n=== Summary ===")
    print(f"Total: {t_total:.1f}s ({t_total/60:.1f} min) for {len(results)} images")
    ok = sum(1 for item in results if item["status"] == "OK")
    print(f"OK: {ok}/{len(results)}, Failed: {len(results) - ok}")
    if results:
        avg = sum(item["dt"] for item in results) / len(results)
        print(f"Avg time/image: {avg:.1f}s")
    print(f"Review queue -> {DST / 'review_queue.md'}")
    print(f"Review project -> {DST / 'review_project.json'}")


if __name__ == "__main__":
    main()
