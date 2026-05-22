"""Per-glyph position estimation from line-bbox image regions.

When rendering vector text on top of an AI-generated image, OCR usually only
provides line-level bounding boxes — we have no real per-character coordinates.
Picking the line's center and laying out characters using our font's metrics
gives positions that drift from the AI image's actual glyph centers, because
the AI's "drawn" character widths don't follow any consistent typographic
metric.

This module measures each glyph's position directly from the source pixels:
project the line region's ink density onto the x axis, and either match
character count to ink islands or fall back to equal-mass partition.
"""
from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np


def _axis_aligned_bbox(quad) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _estimate_background_lightness(gray: np.ndarray) -> float:
    h, w = gray.shape
    if h < 4 or w < 4:
        return float(np.median(gray))
    border_w = max(2, min(w, h) // 30)
    border = np.concatenate([
        gray[:border_w, :].ravel(),
        gray[-border_w:, :].ravel(),
        gray[:, :border_w].ravel(),
        gray[:, -border_w:].ravel(),
    ])
    return float(np.median(border))


def _ink_projection(patch_bgr: np.ndarray, ink_threshold: float = 12.0) -> np.ndarray:
    """Sum text-ink mass per column. Returns 1-D float array of length=patch width."""
    if patch_bgr.size == 0:
        return np.zeros(0, dtype=np.float32)
    gray = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = _estimate_background_lightness(gray)
    ink = np.abs(gray - bg)
    ink[ink < ink_threshold] = 0.0
    proj = ink.sum(axis=0)
    # Light horizontal smoothing to suppress 1-px noise without merging glyphs
    if proj.size >= 5:
        kernel = np.ones(5, dtype=np.float32) / 5.0
        proj = np.convolve(proj, kernel, mode="same")
    return proj


def _find_ink_islands(
    proj: np.ndarray,
    rel_threshold: float = 0.05,
    min_gap_px: int = 2,
) -> List[Tuple[int, int]]:
    """Return [(start_x, end_x_exclusive)] for each continuous run of ink.

    ``rel_threshold`` is relative to the projection peak — columns at < 5% of
    peak ink are considered gaps.  Small noise gaps (< ``min_gap_px``) are
    merged into the neighbouring island.
    """
    if proj.size == 0:
        return []
    peak = float(proj.max())
    if peak <= 0:
        return []
    thresh = peak * rel_threshold
    mask = proj > thresh
    islands: List[Tuple[int, int]] = []
    in_run = False
    run_start = 0
    for i, on in enumerate(mask):
        if on and not in_run:
            run_start = i
            in_run = True
        elif not on and in_run:
            islands.append((run_start, i))
            in_run = False
    if in_run:
        islands.append((run_start, len(mask)))

    # Merge islands separated by tiny gaps (anti-aliasing fringe)
    if not islands:
        return []
    merged = [islands[0]]
    for start, end in islands[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= min_gap_px:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _centroid(proj: np.ndarray, start: int, end: int) -> int:
    seg = proj[start:end]
    total = float(seg.sum())
    if total <= 0:
        return (start + end) // 2
    xs = np.arange(start, end)
    return int(round(float((xs * seg).sum() / total)))


def glyph_centers_from_projection(proj: np.ndarray, n_glyphs: int) -> List[int]:
    """Return ``n_glyphs`` x-centers (local to the projection).

    First try matching ink-island count to ``n_glyphs`` — if it matches, return
    each island's ink-weighted centroid (ideal case).  Otherwise fall back to
    equal-mass partition (robust but coarser).
    """
    if n_glyphs <= 0 or proj.size == 0:
        return []
    if n_glyphs == 1:
        islands = _find_ink_islands(proj)
        if islands:
            start, end = islands[0][0], islands[-1][1]
            return [_centroid(proj, start, end)]
        return [proj.size // 2]

    islands = _find_ink_islands(proj)
    if len(islands) == n_glyphs:
        return [_centroid(proj, s, e) for s, e in islands]

    # Fallback: equal-mass partition.
    cum = np.cumsum(proj)
    total = float(cum[-1])
    if total <= 0:
        # No ink at all: evenly spaced over the projection width
        step = proj.size / n_glyphs
        return [int(round(step * (i + 0.5))) for i in range(n_glyphs)]
    boundaries = [0]
    for i in range(1, n_glyphs):
        target = total * i / n_glyphs
        boundaries.append(int(np.searchsorted(cum, target)))
    boundaries.append(proj.size)
    return [_centroid(proj, a, b) for a, b in zip(boundaries[:-1], boundaries[1:])]


def measure_glyph_centers(
    image_bgr: np.ndarray,
    bbox_quad,
    n_glyphs: int,
) -> List[int]:
    """Return ``n_glyphs`` absolute-x centers inside the bbox quadrilateral.

    Coordinates are in the original ``image_bgr`` frame (not the bbox-local
    crop), so callers can drop them straight into an SVG ``x=`` attribute.
    """
    if n_glyphs <= 0:
        return []
    x0, y0, x1, y1 = _axis_aligned_bbox(bbox_quad)
    h_img, w_img = image_bgr.shape[:2]
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w_img, x1)
    y1 = min(h_img, y1)
    if x1 <= x0 or y1 <= y0:
        # Degenerate bbox: evenly distribute over the requested span
        span = max(1, x1 - x0)
        step = span / n_glyphs
        return [int(round(x0 + step * (i + 0.5))) for i in range(n_glyphs)]
    patch = image_bgr[y0:y1, x0:x1]
    proj = _ink_projection(patch)
    local_centers = glyph_centers_from_projection(proj, n_glyphs)
    return [x0 + c for c in local_centers]
