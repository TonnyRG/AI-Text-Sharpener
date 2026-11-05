"""Local OCR reads the original crop and commits its edits as a single page change."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from ai_text_sharpener import studio


@pytest.fixture
def scene(tmp_path, monkeypatch):
    app = studio.Studio(tmp_path)
    font_id = studio.candidate_fonts('x=2', limit=1)[0]
    fit_calls = []
    ocr_shapes = []

    def make(lines, existing=()):
        # Each colored rectangle stands for one OCR line. Locating it in the
        # supplied pixels exercises cropping, channel order and page coordinates.
        image = np.full((190, 320, 3), 245, dtype=np.uint8)
        colors = {}
        for i, (text, (x, y, width, height)) in enumerate(lines, start=1):
            color = (208, i * 20, 17)
            colors[color] = text
            image[y:y + height, x:x + width] = color

        def recognize(source, **kwargs):
            bgr = (np.asarray(Image.open(source).convert('RGB'))[:, :, ::-1]
                   if isinstance(source, (str, Path)) else np.asarray(source))
            ocr_shapes.append(bgr.shape[:2])
            boxes, texts = [], []
            for rgb, text in colors.items():
                yy, xx = np.where(np.all(bgr == rgb[::-1], axis=2))
                if xx.size:
                    x0, x1, y0, y1 = xx.min(), xx.max() + 1, yy.min(), yy.max() + 1
                    boxes.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
                    texts.append(text)
            return SimpleNamespace(boxes=np.array(boxes, dtype=np.float32) if boxes else None,
                                   txts=texts, scores=[.99] * len(texts), word_results=())

        recognize.text_cls = lambda crops: SimpleNamespace(cls_res=[('0', 1.)] * len(crops))
        recognize.text_cls.cls_thresh = .9
        monkeypatch.setattr(studio, 'ocr_engine', lambda: recognize)
        project = app.store.create('local OCR')
        app.store.add_images(project, [('page', Image.fromarray(image))])
        page = project['pages'][0]
        for key, box, attrs in existing:
            region = dict(id=key, kind='text', text=key, original_text=key, bbox=list(box),
                          x=box[0], y=box[1], font_id=font_id, font_size=15,
                          letter_spacing=0, color='#226677', enabled=True, fit_status='edited')
            region.update(attrs)
            page['regions'].append(region)
        if existing:
            page['status'] = 'review'
            studio.render_page(app.store.directory(project['id']), page)
            app.store.save(project)
        return project

    def fit(image, region, *args):
        fit_calls.append(region['text'])
        assert image.shape[:2] == (190, 320)
        return dict(fit_status='fitted', score=.95)

    monkeypatch.setattr(studio, 'fit_region', fit)
    monkeypatch.setattr(studio, 'candidate_fonts', lambda *args, **kwargs: [font_id])
    monkeypatch.setattr(studio, 'recover_colors', lambda *args: {})
    try:
        yield app, make, ocr_shapes, fit_calls
    finally:
        app.executor.shutdown()


def run_job(app, project, kind='analyze_area', **options):
    app.start_job(dict(kind=kind, project_id=project['id'], page_id=project['pages'][0]['id'],
                       revision=project['revision'], **options))
    app.executor.submit(lambda: None).result(timeout=15)
    return app.store.load(project['id'])


def test_drag_area_replaces_editable_rows_and_protects_neighbors(scene):
    app, make, ocr_shapes, fit_calls = scene
    lines = [('6,738', (55, 29, 31, 14)), ('x=2', (63, 60, 32, 14)),
             ('locked', (128, 32, 38, 15)), ('preserved', (128, 67, 39, 14)),
             ('formula', (125, 99, 40, 15)), ('crossing', (189, 130, 40, 15))]
    existing = [('outdated', lines[0][1], {}), ('locked', lines[2][1], {'locked': True}),
                ('preserved', lines[3][1], {'enabled': False, 'preserve_original': True}),
                ('formula', lines[4][1], {'kind': 'formula', 'enabled': False, 'latex': 'x=1'}),
                ('crossing', lines[5][1], {})]
    project = make(lines, existing)
    expected_neighbors = project['pages'][0]['regions'][1:]
    saved = run_job(app, project, bbox=[40, 20, 168, 143])
    assert app.job['status'] == 'done', app.job['message']
    page = saved['pages'][0]
    result_ids = set(app.job['result_region_ids'])
    fresh = {r['text']: r for r in page['regions'] if r['id'] in result_ids}
    assert set(fresh) == {'6,738', 'x=2'}
    assert [r for r in page['regions'] if r['id'] not in result_ids] == expected_neighbors
    assert set(fit_calls) == set(fresh)
    assert len(ocr_shapes) == 1 and np.prod(ocr_shapes[0]) < 190 * 320
    assert all(r['kind'] == 'text' for r in fresh.values())
    assert fresh['6,738']['source_quad'] == [[55, 29], [86, 29], [86, 43], [55, 43]]
    assert fresh['x=2']['bbox'] == [60, 57, 38, 20]
    assert saved['revision'] == project['revision'] + 1 == page['render_revision']


def test_rescan_moved_text_reads_its_source_box_and_can_split_lines(scene):
    app, make, _, _ = scene
    lines = [('100%', (44, 26, 35, 13)), ('row two', (44, 52, 49, 13)),
             ('at moved position', (230, 132, 56, 13))]
    project = make(lines, [('old', (38, 20, 70, 55), {'x': 229, 'y': 130, 'original_text': 'stale'})])
    saved = run_job(app, project, region_id='old')
    assert app.job['status'] == 'done', app.job['message']
    regions = saved['pages'][0]['regions']
    assert {r['original_text'] for r in regions} == {'100%', 'row two'}
    assert {r['id'] for r in regions} == set(app.job['result_region_ids'])
    assert sorted(r['source_quad'][0] for r in regions) == [[44, 26], [44, 52]]


def test_partially_scanned_page_can_resume_full_ocr_and_keep_user_edit(scene):
    app, make, _, fit_calls = scene
    lines = [('first row', (44, 26, 55, 13)), ('second row', (200, 132, 61, 13))]
    project = run_job(app, make(lines), bbox=[35, 18, 80, 38])
    assert app.job['status'] == 'done', app.job['message']
    page = project['pages'][0]
    assert page['status'] == 'partial'
    first = page['regions'][0]
    first.update(text='correction', x=114, fit_status='edited')
    studio.render_page(app.store.directory(project['id']), page)
    app.store.save(project)
    saved = run_job(app, project, kind='analyze_all')
    assert app.job['completed'] == 1 and app.job['failed'] == 0
    assert saved['pages'][0]['status'] == 'review'
    by_text = {r['text']: r for r in saved['pages'][0]['regions']}
    assert set(by_text) == {'correction', 'second row'}
    assert by_text['correction'] == first
    assert fit_calls == ['first row', 'second row']


def test_rescan_rotated_source_maps_the_local_line_back_to_the_page(scene):
    app, make, _, _ = scene
    quad = [[106, 40], [106, 100], [90, 100], [90, 40]]
    original = ('sideways', (86, 36, 24, 68), dict(source_rotation=90, source_quad=quad))
    project = make([('rotated', (90, 40, 16, 60))], [original])
    saved = run_job(app, project, region_id='sideways')
    assert app.job['status'] == 'done', app.job['message']
    [region] = saved['pages'][0]['regions']
    assert region['text'] == 'rotated'
    assert region['source_rotation'] == pytest.approx(90, abs=1)
    np.testing.assert_allclose(region['source_quad'], quad, atol=2)


def test_small_ink_crop_retries_with_more_context_and_maps_back_once(scene, monkeypatch):
    app, make, _, _ = scene
    project = make([('6,738', (90, 45, 72, 22))])
    recognize = studio.ocr_engine()
    shapes = []

    def detect(source, **kwargs):
        shapes.append(source.shape[:2])
        if len(shapes) == 1:
            return SimpleNamespace(boxes=None, txts=[], scores=[])
        return recognize(source, **kwargs)

    detect.text_cls = recognize.text_cls
    monkeypatch.setattr(studio, 'ocr_engine', lambda: detect)
    saved = run_job(app, project, bbox=[42, 20, 160, 87])
    assert app.job['status'] == 'done', app.job['message']
    first, retry = shapes
    assert retry[0] > first[0] and retry[1] > first[1]
    [region] = saved['pages'][0]['regions']
    assert region['source_quad'] == [[90, 45], [162, 45], [162, 67], [90, 67]]


@pytest.mark.parametrize('failure', ['empty', 'cancel', 'render'])
def test_failed_local_job_does_not_publish_partial_results(scene, monkeypatch, failure):
    app, make, ocr_shapes, _ = scene
    lines = [] if failure == 'empty' else [('replacement', (48, 32, 60, 12))]
    project = make(lines, [('old', (40, 20, 80, 44), {})])
    directory = app.store.directory(project['id'])
    render = studio.render_page
    result_files = list(directory.glob('*-result.*')) + [directory / 'project.json']
    before = {path: path.read_bytes() for path in result_files}
    if failure == 'render':
        def fail_render(*args, **kwargs):
            raise ValueError('renderer failed')
        monkeypatch.setattr(studio, 'render_page', fail_render)
    if failure == 'cancel':
        def cancel_render(*args, **kwargs):
            out = render(*args, **kwargs)
            app.cancelled.set()
            return out
        monkeypatch.setattr(studio, 'render_page', cancel_render)
    run_job(app, project, region_id='old')
    assert app.job['status'] == ('cancelled' if failure == 'cancel' else 'error')
    assert {path: path.read_bytes() for path in result_files} == before
    if failure == 'empty':
        assert len(ocr_shapes) == 1  # A blank crop does not need a second pass.


@pytest.mark.parametrize('request_options', [
    {}, {'region_id': 'locked', 'bbox': [30, 30, 50, 20]}, {'bbox': [30, 30, 0, 20]},
    {'bbox': [350, 100, 25, 10]}, {'region_id': 'locked'},
    {'region_id': 'preserved'}, {'region_id': 'formula'},
])
def test_invalid_or_protected_target_is_rejected_before_ocr(scene, request_options):
    app, make, ocr_shapes, _ = scene
    rows = [('locked', (40, 20, 45, 15), {'locked': True}),
            ('preserved', (40, 50, 45, 15), {'enabled': False, 'preserve_original': True}),
            ('formula', (40, 80, 45, 15), {'enabled': False, 'kind': 'formula', 'latex': 'x'})]
    project = make([], rows)
    try:
        saved = run_job(app, project, **request_options)
    except ValueError:
        saved = app.store.load(project['id'])
    else:
        assert app.job['status'] == 'error'
    assert saved == project
    assert not ocr_shapes
