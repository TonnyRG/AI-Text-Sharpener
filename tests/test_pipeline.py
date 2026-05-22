from pathlib import Path
from ai_text_sharpener.pipeline import sharpen_image
from ai_text_sharpener.fonts import FontSpec


def test_sharpen_image_end_to_end(sample_image_path, tmp_path):
    spec = FontSpec(title="Microsoft YaHei", body="Microsoft YaHei", title_min_px=40)
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"

    sharpen_image(sample_image_path, out_png, out_svg, font_spec=spec)

    assert out_png.exists()
    assert out_png.stat().st_size > 1000
    assert out_svg.exists()
    svg_text = out_svg.read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert "<text" in svg_text
