from pathlib import Path
from ai_text_sharpener.pipeline import (
    sharpen_image,
    _reassign_family_weight_by_final_size,
)
from ai_text_sharpener.fonts import FontSpec
from ai_text_sharpener.review import EditableRegion


def _region(font_size_px, family="Microsoft YaHei Bold", weight="bold"):
    return EditableRegion(
        id="r001",
        bbox=[[0, 0], [200, 0], [200, 40], [0, 40]],
        original_text="x", text="x", confidence=1.0, replace=True,
        x=100, y=20,
        font_family=family.replace(" Bold", "").replace(" Black", ""),
        font_size_px=font_size_px, font_weight=weight,
        letter_spacing_px=0.0, color=(0, 0, 0), background=(255, 255, 255),
    )


def test_reassign_family_weight_demotes_bold_when_shrunk_below_threshold():
    """A region initially assigned title-bold whose font shrinks below the
    threshold during fit_font_sizes_to_bboxes must be re-tagged as body/normal.
    """
    spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei",
                    title_min_px=100)
    r = _region(font_size_px=80)  # below threshold after notional shrink
    _reassign_family_weight_by_final_size([r], spec)
    assert r.font_family == "Microsoft YaHei"
    assert r.font_weight == "normal"


def test_reassign_family_weight_keeps_bold_when_still_above_threshold():
    spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei",
                    title_min_px=100)
    r = _region(font_size_px=150, weight="normal")  # was wrongly tagged normal
    _reassign_family_weight_by_final_size([r], spec)
    assert r.font_family == "Microsoft YaHei"
    assert r.font_weight == "bold"


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
