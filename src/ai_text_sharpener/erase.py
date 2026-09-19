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
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w_img, x + w), min(h_img, y + h)
        if x1 <= x0 or y1 <= y0:
            continue

        patch = np.full((y1 - y0, x1 - x0, 3), style.background, dtype=np.uint8)

        mask = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        if feather_px > 0:
            # Zero border supplies a real transition. Blurring an all-one
            # crop with OpenCV's default reflected border stays constant.
            mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=feather_px, sigmaY=feather_px,
                                    borderType=cv2.BORDER_CONSTANT)
            mask = np.clip(mask, 0, 1)

        alpha = mask[..., None]
        out[y0:y1, x0:x1] = (patch * alpha + out[y0:y1, x0:x1] * (1 - alpha)).astype(np.uint8)

    return out
