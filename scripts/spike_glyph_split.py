"""Spike: per-glyph position estimation from line bbox via ink-projection.

Loads image1 + its review JSON, picks a line region, splits it into N glyph
sub-bboxes using a horizontal ink-density projection profile, and saves a
debug PNG with the split lines overlaid for visual inspection.

Usage:
    python scripts/spike_glyph_split.py [--region r002] [--image image1]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def axis_aligned_bbox(quad) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def estimate_background_lightness(gray_patch: np.ndarray) -> float:
    """Median lightness of the border ring — assumes background is around the edges."""
    h, w = gray_patch.shape
    border_w = max(2, min(w, h) // 30)
    border_pixels = np.concatenate([
        gray_patch[:border_w, :].ravel(),
        gray_patch[-border_w:, :].ravel(),
        gray_patch[:, :border_w].ravel(),
        gray_patch[:, -border_w:].ravel(),
    ])
    return float(np.median(border_pixels))


def ink_projection(patch_bgr: np.ndarray) -> np.ndarray:
    """Return per-column ink mass (1D signal, len = patch width)."""
    gray = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = estimate_background_lightness(gray)
    ink = np.abs(gray - bg)
    # Threshold weak background variations to reduce noise
    ink[ink < 12.0] = 0.0
    proj = ink.sum(axis=0)
    # Smooth slightly to suppress single-pixel noise
    if proj.size >= 7:
        kernel = np.ones(5, dtype=np.float32) / 5.0
        proj = np.convolve(proj, kernel, mode="same")
    return proj


def split_by_equal_mass(proj: np.ndarray, n_glyphs: int) -> List[int]:
    """Return n_glyphs-1 cut x-positions that divide total ink into equal mass chunks.

    Robust against varying glyph widths (wide CJK vs narrow Latin 'i').
    """
    if n_glyphs <= 1 or proj.size == 0:
        return []
    cum = np.cumsum(proj)
    total = float(cum[-1])
    if total <= 0:
        # No ink found → fall back to equal spacing
        step = proj.size / n_glyphs
        return [int(round(step * (i + 1))) for i in range(n_glyphs - 1)]
    targets = [total * (i + 1) / n_glyphs for i in range(n_glyphs - 1)]
    cuts = [int(np.searchsorted(cum, t)) for t in targets]
    return cuts


def glyph_centers(proj: np.ndarray, n_glyphs: int) -> List[int]:
    """Per-glyph x-center as the ink-weighted centroid within each sub-segment."""
    if n_glyphs <= 0 or proj.size == 0:
        return []
    cuts = split_by_equal_mass(proj, n_glyphs)
    boundaries = [0] + cuts + [proj.size]
    centers = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        seg = proj[a:b]
        if seg.sum() <= 0:
            centers.append(int((a + b) // 2))
        else:
            xs = np.arange(a, b)
            centers.append(int(round(float((xs * seg).sum() / seg.sum()))))
    return centers


def draw_overlay(
    image_bgr: np.ndarray,
    bbox_xyxy: Tuple[int, int, int, int],
    cuts_local: List[int],
    centers_local: List[int],
    text: str,
) -> np.ndarray:
    x0, y0, x1, y1 = bbox_xyxy
    out = image_bgr.copy()
    # Bbox in green
    cv2.rectangle(out, (x0, y0), (x1, y1), (0, 200, 0), 3)
    # Cut lines in red (split boundaries between glyphs)
    for cx in cuts_local:
        gx = x0 + cx
        cv2.line(out, (gx, y0), (gx, y1), (0, 0, 255), 2)
    # Centers in blue dots (one per detected glyph)
    for i, cx in enumerate(centers_local):
        gx = x0 + cx
        cv2.circle(out, (gx, (y0 + y1) // 2), 8, (255, 80, 0), -1)
    # Title strip above the bbox
    label = f"text={text!r} | glyphs={len(centers_local)}"
    cv2.putText(out, label, (x0, max(0, y0 - 16)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 3)
    cv2.putText(out, label, (x0, max(0, y0 - 16)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", type=Path,
                    default=Path("examples/before_after/image1_review.json"))
    ap.add_argument("--region", default="r002")
    ap.add_argument("--out", type=Path,
                    default=Path("scripts/spike_glyph_split_output.png"))
    args = ap.parse_args()

    review = json.loads(args.review.read_text(encoding="utf-8"))
    src_image = Path(review["source_image"])
    image_bgr = cv2.imread(str(src_image))
    if image_bgr is None:
        raise SystemExit(f"Failed to read image: {src_image}")

    region = next(r for r in review["regions"] if r["id"] == args.region)
    text = region.get("text", "")
    # Use the bbox field which is a quadrilateral
    x0, y0, x1, y1 = axis_aligned_bbox(region["bbox"])
    patch = image_bgr[y0:y1, x0:x1]
    print(f"Region {args.region}: text={text!r}")
    print(f"  bbox xyxy = ({x0},{y0})-({x1},{y1})  size={x1-x0}x{y1-y0}")
    print(f"  expected glyphs (len strip spaces) = "
          f"{len(text)} / {len(text.replace(' ', ''))}")

    n = len(text)
    proj = ink_projection(patch)
    cuts = split_by_equal_mass(proj, n)
    centers = glyph_centers(proj, n)
    print(f"  cuts (local x): {cuts}")
    print(f"  centers (local x): {centers}")

    overlay = draw_overlay(image_bgr, (x0, y0, x1, y1), cuts, centers, text)
    # Save full image with overlay
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), overlay)
    print(f"Overlay -> {args.out}")

    # Also save just the cropped strip with overlay for easier inspection
    crop = overlay[y0:y1, x0:x1]
    crop_out = args.out.with_name(args.out.stem + "_crop.png")
    cv2.imwrite(str(crop_out), crop)
    print(f"Crop overlay -> {crop_out}")


if __name__ == "__main__":
    main()
