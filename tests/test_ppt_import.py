from PIL import Image

from ai_text_sharpener.fonts import FontSpec
from ai_text_sharpener.ppt_import import create_ppt_review_project
from ai_text_sharpener.project import load_review_project, resolve_project_path
from ai_text_sharpener.review import EditableRegion, ReviewDocument


def _review(image_path):
    return ReviewDocument(
        source_image=str(image_path),
        image_width=160,
        image_height=90,
        regions=[
            EditableRegion(
                id="r001",
                bbox=[[10, 10], [80, 10], [80, 30], [10, 30]],
                original_text="Slide",
                text="Slide",
                confidence=0.95,
                replace=True,
                x=45,
                y=20,
                font_family="Arial",
                font_size_px=18,
                font_weight="normal",
                color=(0, 0, 0),
                background=(255, 255, 255),
            )
        ],
    )


def test_create_ppt_review_project_with_injected_exporter(tmp_path):
    ppt_path = tmp_path / "deck.pptx"
    ppt_path.write_bytes(b"fake ppt")
    output_dir = tmp_path / "review"

    def fake_exporter(_ppt_path, slides_dir):
        first = slides_dir / "slide_001.jpg"
        second = slides_dir / "slide_002.jpg"
        Image.new("RGB", (160, 90), "white").save(first)
        Image.new("RGB", (160, 90), "white").save(second)
        return [first, second]

    def fake_renderer(_image_path, output_png, output_svg, _review):
        output_png.write_bytes(b"png")
        output_svg.write_text("<svg></svg>", encoding="utf-8")

    project_path = create_ppt_review_project(
        ppt_path=ppt_path,
        output_dir=output_dir,
        font_spec=FontSpec(title="Arial Bold", body="Arial", title_min_px=40),
        exporter=fake_exporter,
        analyzer=lambda image_path, _spec: _review(image_path),
        renderer=fake_renderer,
    )

    project = load_review_project(project_path)

    assert len(project.items) == 2
    assert project.items[0].id == "slide-001"
    assert project.items[0].image_path == "slides\\slide_001.jpg"
    assert resolve_project_path(project_path, project.items[1].review_path).exists()
    assert resolve_project_path(project_path, project.items[1].draft_svg).exists()
