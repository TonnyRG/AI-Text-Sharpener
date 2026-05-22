from pathlib import Path
from ai_text_sharpener.pipeline import (
    analyze_image,
    render_review_document,
    sharpen_image,
)
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


def test_render_uses_per_glyph_positions(sample_image_path, tmp_path):
    """With per-glyph rendering, the total <text> count must exceed the active
    region count (each char becomes its own <text>)."""
    spec = FontSpec(title="Microsoft YaHei", body="Microsoft YaHei", title_min_px=40)
    review = analyze_image(sample_image_path, spec)
    # Drop any auto-detected spans so we exercise the per-glyph path.
    for r in review.regions:
        r.spans = []
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"
    render_review_document(sample_image_path, out_png, out_svg, review)

    svg_text = out_svg.read_text(encoding="utf-8")
    n_active = sum(1 for r in review.regions if r.replace)
    assert n_active > 0
    assert svg_text.count("<text ") > n_active
