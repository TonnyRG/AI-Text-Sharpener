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
    """Sample text color by picking the foreground pixels (those whose luminance
    is farthest from the bbox-mean luminance).

    Works symmetrically for dark-on-light and light-on-dark.  Uses absolute
    distance from the patch's mean luminance rather than a one-sided percentile,
    and floors the cutoff at half of the max distance so that very thin text
    (e.g. small white text on a wide dark title bar — ~3-5% of bbox area) still
    gets picked up.  A pure percentile-only cutoff would land inside the
    dominant background range whenever text occupies < 20% of the area, making
    the returned color equal to the background.
    """
    x, y, w, h = rect
    patch = img[y:y+h, x:x+w]
    if patch.size == 0:
        return (0, 0, 0)
    lum = patch.mean(axis=2)
    bg_lum = lum.mean()
    abs_diff = np.abs(lum - bg_lum)
    max_diff = float(abs_diff.max())
    if max_diff < 5.0:
        # Nearly uniform patch — no text contrast to find; return overall mean.
        return tuple(int(c) for c in patch.reshape(-1, 3).mean(axis=0))
    threshold = max(float(np.percentile(abs_diff, 80)), max_diff * 0.5)
    mask = abs_diff >= threshold
    if not mask.any():
        return tuple(int(c) for c in patch.reshape(-1, 3).mean(axis=0))
    fg_pixels = patch[mask]
    return tuple(int(c) for c in np.median(fg_pixels, axis=0))


def sample_background_color(img: np.ndarray, rect: Rect, ring_px: int = 3) -> RGB:
    """Sample background by taking median color in a ring just outside the bbox."""
    h_img, w_img = img.shape[:2]
    x, y, w, h = rect
    x0, y0 = max(0, x - ring_px), max(0, y - ring_px)
    x1, y1 = min(w_img, x + w + ring_px), min(h_img, y + h + ring_px)
    outer = img[y0:y1, x0:x1].copy()
    inner_x0, inner_y0 = x - x0, y - y0
    outer[inner_y0:inner_y0 + h, inner_x0:inner_x0 + w] = 0
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
