from click.testing import CliRunner
from PIL import Image

from ai_text_sharpener.cli import main
from ai_text_sharpener.review import EditableRegion, ReviewDocument, write_review_document


def test_cli_renders_from_review_json(tmp_path):
    input_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(input_path)
    review_path = tmp_path / "review.json"
    review = ReviewDocument(
        source_image=str(input_path),
        image_width=120,
        image_height=60,
        regions=[
            EditableRegion(
                id="r001",
                bbox=[[20, 20], [80, 20], [80, 40], [20, 40]],
                original_text="Original",
                text="Edited",
                confidence=0.95,
                replace=True,
                x=50,
                y=30,
                font_family="Arial",
                font_size_px=18,
                font_weight="bold",
                color=(0, 0, 0),
                background=(255, 255, 255),
            )
        ],
    )
    write_review_document(review, review_path)
    out_png = tmp_path / "out.png"

    result = CliRunner().invoke(
        main,
        [str(input_path), "-o", str(out_png), "--from-review", str(review_path)],
    )

    assert result.exit_code == 0
    assert out_png.exists()
    assert out_png.with_suffix(".svg").exists()
    svg_text = out_png.with_suffix(".svg").read_text(encoding="utf-8")
    # Per-glyph rendering emits one <text> per char, so check each character is present.
    assert all(f">{c}<" in svg_text for c in "Edited")
