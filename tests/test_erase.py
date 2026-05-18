import numpy as np
from ai_text_sharpener.erase import soft_erase
from ai_text_sharpener.style import RegionStyle
from ai_text_sharpener.detect import TextRegion


def test_soft_erase_fills_bbox_with_background():
    img = np.full((100, 200, 3), 255, dtype=np.uint8)
    img[40:60, 80:120] = 0  # "text"
    region = TextRegion(
        bbox=[[80, 40], [120, 40], [120, 60], [80, 60]],
        text="X",
        confidence=1.0,
    )
    style = RegionStyle(color=(0, 0, 0), background=(255, 255, 255), font_size_px=20)
    result = soft_erase(img, [(region, style)])
    center_pixel = result[50, 100]
    assert center_pixel.mean() > 200


def test_soft_erase_preserves_outside_bbox():
    img = np.full((100, 200, 3), 128, dtype=np.uint8)
    img[40:60, 80:120] = 0
    region = TextRegion(
        bbox=[[80, 40], [120, 40], [120, 60], [80, 60]],
        text="X", confidence=1.0,
    )
    style = RegionStyle(color=(0, 0, 0), background=(255, 255, 255), font_size_px=20)
    result = soft_erase(img, [(region, style)])
    assert result[10, 10].tolist() == [128, 128, 128]
