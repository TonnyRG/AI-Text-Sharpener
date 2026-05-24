import json
import threading
import urllib.error
import urllib.request

from PIL import Image

from ai_text_sharpener.editor import build_editor_html, list_projects, make_server
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


def _make_fake_project(root, name, source_ppt_name, slide_count, mtime_offset=0):
    """Create a project dir with a review_project.json under ``root/name/``.

    ``mtime_offset`` is added to the manifest's mtime so tests can pin order.
    """
    import time
    proj = root / name
    proj.mkdir(parents=True)
    items = [{"id": f"slide-{i:03d}", "name": f"Slide {i}", "image_path": "",
              "review_path": "", "output_png": "", "output_svg": ""}
             for i in range(1, slide_count + 1)]
    manifest = proj / "review_project.json"
    manifest.write_text(
        json.dumps({"source_ppt": str(proj / source_ppt_name), "items": items}),
        encoding="utf-8",
    )
    if mtime_offset:
        target = time.time() + mtime_offset
        import os
        os.utime(manifest, (target, target))
    return manifest


def test_list_projects_returns_empty_when_root_missing(tmp_path):
    assert list_projects(projects_root=tmp_path / "absent") == []


def test_list_projects_sorted_by_mtime_descending(tmp_path):
    _make_fake_project(tmp_path, "older", "deck1.pptx", 3, mtime_offset=-100)
    _make_fake_project(tmp_path, "newer", "deck2.pptx", 5, mtime_offset=0)

    projects = list_projects(projects_root=tmp_path)

    assert [p["name"] for p in projects] == ["newer", "older"]
    assert projects[0]["slide_count"] == 5
    assert projects[0]["source_ppt"] == "deck2.pptx"
    assert "T" in projects[0]["modified_iso"]  # ISO 8601 sentinel


def test_list_projects_marks_active(tmp_path):
    active_manifest = _make_fake_project(tmp_path, "active", "a.pptx", 2)
    _make_fake_project(tmp_path, "other", "b.pptx", 4)

    projects = list_projects(projects_root=tmp_path, active_path=active_manifest)
    by_name = {p["name"]: p for p in projects}
    assert by_name["active"]["is_active"] is True
    assert by_name["other"]["is_active"] is False


def test_list_projects_skips_dirs_without_manifest_or_with_bad_json(tmp_path):
    (tmp_path / "no_manifest").mkdir()
    bad = tmp_path / "bad_json"
    bad.mkdir()
    (bad / "review_project.json").write_text("{not valid", encoding="utf-8")
    _make_fake_project(tmp_path, "good", "x.pptx", 1)

    names = [p["name"] for p in list_projects(projects_root=tmp_path)]
    assert names == ["good"]


def _start_server(image_path, review_path=None, project_path=None):
    server = make_server(
        image_path=image_path, review_path=review_path,
        output_png=None, output_svg=None,
        host="127.0.0.1", port=0, project_path=project_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_switch_project_changes_active_project(tmp_path, monkeypatch):
    # Set up two fake projects under cwd/examples/ppt_reviews/
    monkeypatch.chdir(tmp_path)
    projects_root = tmp_path / "examples" / "ppt_reviews"
    projects_root.mkdir(parents=True)
    first = _make_fake_project(projects_root, "alpha", "a.pptx", 1)
    second = _make_fake_project(projects_root, "beta", "b.pptx", 2)
    image_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "review.json"
    write_review_document(_review(image_path), review_path)

    server, thread = _start_server(image_path, review_path, project_path=first)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        body = json.dumps({"project_path": str(second)}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/switch-project", data=body,
            headers={"content-type": "application/json"}, method="POST",
        )
        with opener.open(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        assert result["ok"] is True
        assert result["project_path"] == str(second.resolve())

        # After switching, /api/projects should mark beta as active
        with opener.open(f"{base}/api/projects", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        by_name = {p["name"]: p for p in data["projects"]}
        assert by_name["beta"]["is_active"] is True
        assert by_name["alpha"]["is_active"] is False
    finally:
        _stop_server(server, thread)


def test_switch_project_rejects_path_outside_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "examples" / "ppt_reviews").mkdir(parents=True)
    # Drop a manifest OUTSIDE the projects root
    outside = tmp_path / "rogue"
    outside.mkdir()
    bad = outside / "review_project.json"
    bad.write_text('{"items": []}', encoding="utf-8")
    image_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "review.json"
    write_review_document(_review(image_path), review_path)

    server, thread = _start_server(image_path, review_path)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        body = json.dumps({"project_path": str(bad)}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/switch-project", data=body,
            headers={"content-type": "application/json"}, method="POST",
        )
        try:
            opener.open(req, timeout=5)
            raised = False
        except urllib.error.HTTPError as exc:
            raised = True
            assert exc.code == 400
        assert raised, "expected HTTP 400 for out-of-root path"
    finally:
        _stop_server(server, thread)


def test_delete_project_removes_dir_but_not_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    projects_root = tmp_path / "examples" / "ppt_reviews"
    projects_root.mkdir(parents=True)
    active = _make_fake_project(projects_root, "current", "a.pptx", 1)
    inactive = _make_fake_project(projects_root, "old", "b.pptx", 1)
    image_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "review.json"
    write_review_document(_review(image_path), review_path)

    server, thread = _start_server(image_path, review_path, project_path=active)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # Deleting the inactive project succeeds
        body = json.dumps({"project_path": str(inactive)}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/project", data=body,
            headers={"content-type": "application/json"}, method="DELETE",
        )
        with opener.open(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        assert result["ok"] is True
        assert not (projects_root / "old").exists()
        assert (projects_root / "current").exists()  # untouched

        # Deleting the active project must fail
        body = json.dumps({"project_path": str(active)}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/project", data=body,
            headers={"content-type": "application/json"}, method="DELETE",
        )
        try:
            opener.open(req, timeout=5)
            raised = False
        except urllib.error.HTTPError as exc:
            raised = True
            assert exc.code == 400
        assert raised, "expected HTTP 400 when deleting the active project"
        assert (projects_root / "current").exists()
    finally:
        _stop_server(server, thread)


def test_editor_html_response_disables_browser_cache(tmp_path):
    """Editor HTML must be served with Cache-Control: no-store so package
    upgrades take effect on a plain browser refresh (regression for the
    stale-cache pain encountered after pushing canvas-click bugfix)."""
    image_path = tmp_path / "input.png"
    Image.new("RGB", (120, 60), "white").save(image_path)
    review_path = tmp_path / "review.json"
    write_review_document(_review(image_path), review_path)

    server = make_server(
        image_path=image_path, review_path=review_path,
        output_png=None, output_svg=None, host="127.0.0.1", port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            cc = response.headers.get("cache-control", "")
        assert "no-store" in cc.lower(), f"expected no-store, got {cc!r}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
