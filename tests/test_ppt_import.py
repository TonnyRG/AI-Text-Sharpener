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


def test_create_ppt_review_project_calls_progress_callback(tmp_path):
    ppt_path = tmp_path / "deck.pptx"
    ppt_path.write_bytes(b"fake ppt")
    output_dir = tmp_path / "review"

    def fake_exporter(_p, slides_dir):
        first = slides_dir / "slide_001.jpg"
        Image.new("RGB", (160, 90), "white").save(first)
        return [first]

    def fake_renderer(_i, png, svg, _r):
        png.write_bytes(b"x"); svg.write_text("<svg/>", encoding="utf-8")

    events = []
    create_ppt_review_project(
        ppt_path=ppt_path,
        output_dir=output_dir,
        font_spec=FontSpec(title="Arial", body="Arial"),
        exporter=fake_exporter,
        analyzer=lambda p, _s: _review(p),
        renderer=fake_renderer,
        on_progress=lambda stage, cur, total, msg: events.append((stage, cur, total)),
    )

    # We expect at least: exporting (start + finish), analyzing (start), rendering, done
    stages = [e[0] for e in events]
    assert "exporting" in stages
    assert "analyzing" in stages
    assert "rendering" in stages
    assert stages[-1] == "done"
    # Last event reports total slide count
    assert events[-1][1] == 1 and events[-1][2] == 1


def test_create_ppt_review_project_silences_progress_when_callback_is_none(tmp_path):
    ppt_path = tmp_path / "deck.pptx"
    ppt_path.write_bytes(b"fake ppt")
    output_dir = tmp_path / "review"

    def fake_exporter(_p, slides_dir):
        first = slides_dir / "slide_001.jpg"
        Image.new("RGB", (160, 90), "white").save(first)
        return [first]

    def fake_renderer(_i, png, svg, _r):
        png.write_bytes(b"x"); svg.write_text("<svg/>", encoding="utf-8")

    # Just verify it doesn't crash; nothing to assert beyond completion.
    create_ppt_review_project(
        ppt_path=ppt_path,
        output_dir=output_dir,
        font_spec=FontSpec(title="Arial", body="Arial"),
        exporter=fake_exporter,
        analyzer=lambda p, _s: _review(p),
        renderer=fake_renderer,
        on_progress=None,
    )
