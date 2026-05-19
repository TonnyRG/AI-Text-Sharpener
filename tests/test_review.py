from PIL import Image

from ai_text_sharpener.pipeline import render_review_document
from ai_text_sharpener.review import (
    EditableRegion,
    ReviewDocument,
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
    assert "EDITED" in svg
    assert "KEEP" not in svg
    assert out_png.exists()
