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
    rect = (70, 30, 60, 40)
    rgb = sample_text_color(img, rect)
    assert sum(rgb) < 100


def test_sample_background_color_picks_outside_border():
    img = _make_test_image()
    rect = (70, 30, 60, 40)
    rgb = sample_background_color(img, rect)
    assert all(c > 240 for c in rgb)


def test_extract_style_returns_complete_style(sample_image_path):
    from ai_text_sharpener.detect import detect_text
    regions = detect_text(str(sample_image_path))
    img = np.array(Image.open(sample_image_path))
    style = extract_style(img, regions[0])
    assert isinstance(style, RegionStyle)
    assert hasattr(style, "color")
    assert hasattr(style, "background")
    assert hasattr(style, "font_size_px")
    assert style.font_size_px > 0
