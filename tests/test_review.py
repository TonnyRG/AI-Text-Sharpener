from PIL import Image

from ai_text_sharpener.pipeline import render_review_document
from ai_text_sharpener.review import (
    EditableRegion,
    ReviewDocument,
    TextSpan,
    load_review_document,
    write_review_document,
)


def _region(region_id, text, replace=True):
    return EditableRegion(
        id=region_id,
        bbox=[[10, 10], [60, 10], [60, 30], [10, 30]],
        original_text=text,
        text=text,
        confidence=0.9,
        replace=replace,
        x=35,
        y=20,
        font_family="Arial",
        font_size_px=16,
        font_weight="normal",
        letter_spacing_px=0.0,
        color=(0, 0, 0),
        background=(255, 255, 255),
    )


def test_review_document_round_trip(tmp_path):
    review = ReviewDocument(
        source_image="input.png",
        image_width=100,
        image_height=50,
        regions=[_region("r001", "Hello", replace=False)],
    )
    path = tmp_path / "review.json"

    write_review_document(review, path)
    loaded = load_review_document(path)

    assert loaded.image_width == 100
    assert loaded.regions[0].id == "r001"
    assert loaded.regions[0].replace is False
    assert loaded.regions[0].color == (0, 0, 0)
    assert loaded.regions[0].letter_spacing_px == 0.0


def test_review_document_span_font_family_round_trip(tmp_path):
    region = _region("r001", "2026 年")
    region.spans = [
        TextSpan(text="2026", font_family="Times New Roman"),
        TextSpan(text=" 年", font_family="Noto Sans SC"),
    ]
    review = ReviewDocument(
        source_image="input.png",
        image_width=100,
        image_height=50,
        regions=[region],
    )
    path = tmp_path / "review.json"

    write_review_document(review, path)
    loaded = load_review_document(path)

    assert loaded.regions[0].spans[0].font_family == "Times New Roman"
    assert loaded.regions[0].spans[1].font_family == "Noto Sans SC"


def test_load_review_document_accepts_utf8_bom(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(
        '{"image_width": 100, "image_height": 50, "regions": []}',
        encoding="utf-8-sig",
    )

    loaded = load_review_document(path)

    assert loaded.image_width == 100


def test_render_review_document_skips_disabled_regions(tmp_path):
    input_path = tmp_path / "input.png"
    Image.new("RGB", (100, 50), "white").save(input_path)
    review = ReviewDocument(
        source_image=str(input_path),
        image_width=100,
        image_height=50,
        regions=[
            _region("r001", "KEEP", replace=False),
            _region("r002", "EDITED", replace=True),
        ],
    )
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"

    render_review_document(input_path, out_png, out_svg, review)

    svg = out_svg.read_text(encoding="utf-8")
    # Per-glyph rendering emits one <text> per char.
    assert all(f">{c}<" in svg for c in "EDITED")
    # KEEP region (replace=False) should produce no glyph for 'K' (unique to KEEP).
    assert ">K<" not in svg
    assert out_png.exists()


def test_render_review_document_passes_prepared_font_dirs(tmp_path, monkeypatch):
    input_path = tmp_path / "input.png"
    Image.new("RGB", (100, 50), "white").save(input_path)
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    review = ReviewDocument(
        source_image=str(input_path),
        image_width=100,
        image_height=50,
        regions=[_region("r001", "Noto")],
    )
    review.regions[0].spans = [TextSpan(text="Noto", font_family="Noto Serif SC")]
    out_png = tmp_path / "out.png"
    out_svg = tmp_path / "out.svg"
    captured = {}

    prepared = [fonts_dir / ".generated", fonts_dir]

    def fake_prepare(passed_fonts_dir, families):
        captured["passed_fonts_dir"] = passed_fonts_dir
        captured["families"] = list(families)
        return prepared

    def fake_svg_to_png(_svg_text, output_path, font_dirs=None):
        captured["font_dirs"] = list(font_dirs or [])
        output_path.write_bytes(b"png")

    monkeypatch.setattr("ai_text_sharpener.pipeline.prepare_render_font_dirs", fake_prepare)
    monkeypatch.setattr("ai_text_sharpener.pipeline.svg_to_png", fake_svg_to_png)

    render_review_document(input_path, out_png, out_svg, review, fonts_dir=fonts_dir)

    assert captured["passed_fonts_dir"] == fonts_dir
    assert captured["families"] == ["Arial", "Noto Serif SC"]
    assert captured["font_dirs"] == prepared
