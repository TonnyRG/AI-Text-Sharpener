import json
import threading
import urllib.request

from PIL import Image

from ai_text_sharpener.editor import build_editor_html, make_server
from ai_text_sharpener.project import ReviewProject, ReviewProjectItem, write_review_project
from ai_text_sharpener.review import EditableRegion, ReviewDocument, write_review_document


def _review(image_path):
    return ReviewDocument(
        source_image=str(image_path),
        image_width=120,
        image_height=60,
        regions=[
            EditableRegion(
                id="r001",
                bbox=[[20, 20], [80, 20], [80, 40], [20, 40]],
                original_text="Original",
                text="Original",
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


def test_editor_html_contains_canvas_and_api_hooks():
    html = build_editor_html()

    assert '<canvas id="canvas">' in html
    assert 'id="slideList"' in html
    assert 'id="letterSpacing"' in html
    assert "/api/state" in html
    assert "/api/review" in html


def test_editor_server_reads_and_writes_review(tmp_path):
    image_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "review.json"
    write_review_document(_review(image_path), review_path)

    server = make_server(
        image_path=image_path,
        review_path=review_path,
        output_png=None,
        output_svg=None,
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{base_url}/api/state", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["regions"][0]["text"] == "Original"

        data["regions"][0]["text"] = "Edited"
        body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/review",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with opener.open(request, timeout=5) as response:
            saved = json.loads(response.read().decode("utf-8"))
        assert saved["ok"] is True
        assert "Edited" in review_path.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_editor_server_handles_review_project(tmp_path):
    first_image = tmp_path / "slide_001.jpg"
    second_image = tmp_path / "slide_002.jpg"
    Image.new("RGB", (120, 60), "white").save(first_image)
    Image.new("RGB", (120, 60), "white").save(second_image)

    first_review = tmp_path / "slide_001_review.json"
    second_review = tmp_path / "slide_002_review.json"
    write_review_document(_review(first_image), first_review)
    second = _review(second_image)
    second.regions[0].text = "Second"
    write_review_document(second, second_review)

    project_path = tmp_path / "review_project.json"
    write_review_project(
        ReviewProject(
            items=[
                ReviewProjectItem(
                    id="slide-001",
                    name="Slide 1",
                    image_path=first_image.name,
                    review_path=first_review.name,
                ),
                ReviewProjectItem(
                    id="slide-002",
                    name="Slide 2",
                    image_path=second_image.name,
                    review_path=second_review.name,
                ),
            ]
        ),
        project_path,
    )

    server = make_server(
        image_path=None,
        review_path=None,
        output_png=None,
        output_svg=None,
        host="127.0.0.1",
        port=0,
        project_path=project_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{base_url}/api/state?slide=slide-002", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["active_slide_id"] == "slide-002"
        assert len(data["slides"]) == 2
        assert data["regions"][0]["text"] == "Second"

        data["regions"][0]["letter_spacing_px"] = 2.5
        body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/review?slide=slide-002",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with opener.open(request, timeout=5) as response:
            saved = json.loads(response.read().decode("utf-8"))
        assert saved["ok"] is True
        assert '"letter_spacing_px": 2.5' in second_review.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_editor_export_ppt_force_renders_with_fonts_dir(tmp_path, monkeypatch):
    image_path = tmp_path / "slide_001.jpg"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "slide_001_review.json"
    write_review_document(_review(image_path), review_path)
    output_png = tmp_path / "slide_001_final.png"
    Image.new("RGB", (120, 60), "white").save(output_png)
    output_svg = tmp_path / "slide_001_final.svg"
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    project_path = tmp_path / "review_project.json"
    write_review_project(
        ReviewProject(
            items=[
                ReviewProjectItem(
                    id="slide-001",
                    name="Slide 1",
                    image_path=image_path.name,
                    review_path=review_path.name,
                    output_png=output_png.name,
                    output_svg=output_svg.name,
                ),
            ]
        ),
        project_path,
    )
    calls = []

    def fake_render(image, png, svg, review, fonts_dir=None):
        calls.append((image, png, svg, fonts_dir))
        Image.new("RGB", (120, 60), "white").save(png)
        svg.write_text("<svg></svg>", encoding="utf-8")

    def fake_export(project, output):
        output.write_bytes(b"pptx")
        return output

    monkeypatch.setattr("ai_text_sharpener.editor.render_review_document", fake_render)
    monkeypatch.setattr("ai_text_sharpener.editor.export_project_to_pptx", fake_export)

    server = make_server(
        image_path=None,
        review_path=None,
        output_png=None,
        output_svg=None,
        host="127.0.0.1",
        port=0,
        project_path=project_path,
        fonts_dir=fonts_dir,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(
            f"{base_url}/api/export-ppt",
            data=b"",
            method="POST",
        )
        with opener.open(request, timeout=5) as response:
            exported = json.loads(response.read().decode("utf-8"))
        assert exported["ok"] is True
        assert calls
        assert calls[0][3] == fonts_dir
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
