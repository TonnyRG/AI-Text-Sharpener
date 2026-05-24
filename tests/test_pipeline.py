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


def test_font_size_cap_default_keeps_title_height_on_2250_tall_slide():
    """max_font_ratio default must let a typical PPT-export title through.

    Regression for the "all titles render at exactly 112" bug — for h=2250
    images (PowerPoint export at long-side=4000), 0.05 cap clamped all
    >132-tall bboxes to font_size=112, collapsing title/sub-head distinction.
    """
    from ai_text_sharpener.pipeline import analyze_image
    spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)
    # We only need the cap math; assert via signature inspection that the
    # default is permissive enough to keep a 200-tall title's font (= 170 after
    # the 0.85 multiplier) unclamped on a 2250-tall slide.
    import inspect
    sig = inspect.signature(analyze_image)
    cap_ratio = sig.parameters["max_font_ratio"].default
    h = 2250
    cap = int(h * cap_ratio)
    typical_title_font = int(200 * 0.85)  # 170
    assert cap >= typical_title_font, (
        f"max_font_ratio={cap_ratio} on h={h} gives cap={cap}, "
        f"which still clamps a typical title (~{typical_title_font} px)"
    )


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
