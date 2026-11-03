"""Scanning is plain OCR; formula work requires an explicitly selected region."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from ai_text_sharpener import classification, formula, studio


@pytest.fixture
def no_automatic_formula(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Ordinary OCR must not detect or recognize formulas')

    for module, name in ((formula, 'detect_formulas'), (classification, 'resolve_types'),
                         (studio, 'detect_formulas'), (studio, 'resolve_types'),
                         (studio, 'recognize_formula'), (studio, 'fit_formula')):
        # Also guard the old imported aliases if a regression restores them.
        monkeypatch.setattr(module, name, forbidden, raising=False)
    return calls


def mock_ocr(monkeypatch, texts, scores=None):
    calls = []
    boxes = np.array([[[20, 20 + i * 40], [300, 20 + i * 40],
                       [300, 45 + i * 40], [20, 45 + i * 40]]
                      for i in range(len(texts))], dtype=np.float32)

    def recognize(path, **kwargs):
        calls.append(path)
        return SimpleNamespace(boxes=boxes if texts else None, txts=texts,
                               scores=scores if scores is not None else [.99] * len(texts),
                               word_results=())

    recognize.text_cls = lambda crops: SimpleNamespace(cls_res=[('0', .99)] * len(crops))
    recognize.text_cls.cls_thresh = .9
    monkeypatch.setattr(studio, 'ocr_engine', lambda: recognize)
    monkeypatch.setattr(studio, 'candidate_fonts', lambda *args, **kwargs: ['test-face'])
    return calls


@pytest.mark.parametrize('text,confidence', [
    ('6,738', .99), ('100%', .99), ('中文 English 混排', .99),
    ('x=2', .99), ('E=mc²', .99), ('6,738', .6),
])
def test_ocr_content_never_changes_the_default_type(tmp_path, monkeypatch,
                                                   no_automatic_formula, text, confidence):
    calls = mock_ocr(monkeypatch, [text], [confidence])
    path = tmp_path / 'slide.png'
    Image.new('RGB', (400, 300), 'white').save(path)
    regions = studio.detect_regions(path)
    assert len(calls) == 1 and not no_automatic_formula
    assert len(regions) == 1
    region = regions[0]
    assert region['kind'] == 'text'
    assert region['text'] == region['original_text'] == text
    assert region['enabled'] == (confidence >= .8)
    assert not any(key in region for key in ('latex', 'type_decision', 'type_review'))


def test_empty_ocr_does_not_trigger_formula_detection(tmp_path, monkeypatch, no_automatic_formula):
    mock_ocr(monkeypatch, [])
    path = tmp_path / 'empty.png'
    Image.new('RGB', (400, 300), 'white').save(path)
    assert studio.detect_regions(path) == []
    assert not no_automatic_formula


@pytest.fixture
def app_project(tmp_path, monkeypatch):
    app = studio.Studio(tmp_path)
    project = app.store.create('manual formula routing')
    app.store.add_images(project, [(f'page {i}', Image.new('RGB', (400, 300), 'white'))
                                  for i in range(2)])
    # Exercise the real scan and job persistence paths without font fitting or
    # optional formula runtimes. Those renderers have their own coverage.
    monkeypatch.setattr(studio, 'fit_region', lambda image, region, *args: dict(region, fit_status='fitted'))
    monkeypatch.setattr(studio, 'recover_colors', lambda *args: {})
    monkeypatch.setattr(studio, 'normalize_page', lambda *args: None)
    monkeypatch.setattr(studio, 'align_page', lambda *args: None)
    monkeypatch.setattr(studio, 'render_page', lambda *args: None)
    try:
        yield app, project
    finally:
        app.executor.shutdown()


def run_job(app, project, kind, **extra):
    app.start_job(dict(kind=kind, project_id=project['id'], revision=project['revision'],
                       page_id=project['pages'][0]['id'], **extra))
    app.executor.submit(lambda: None).result(timeout=20)
    return app.store.load(project['id'])


def formula_region(**updates):
    return dict(dict(id='math', kind='formula', text='x=2', original_text='x=2',
                     bbox=[20, 20, 280, 25], x=20, y=20, font_id='', font_size=25,
                     letter_spacing=0, stroke_width=0, rotation=0, latex='x=2',
                     enabled=False, locked=False, fit_status='edited'), **updates)


@pytest.mark.parametrize('kind', ['analyze', 'analyze_all'])
@pytest.mark.parametrize('reset', [False, True])
def test_single_and_batch_scans_use_plain_text_even_on_rescan(
        app_project, monkeypatch, no_automatic_formula, kind, reset):
    app, project = app_project
    texts = ['6,738', '100%', '中文 English', 'x=2']
    calls = mock_ocr(monkeypatch, texts)
    if reset:
        for page in project['pages']:
            page.update(regions=[formula_region()], status='review')
        app.store.save(project)
    saved = run_job(app, project, kind, reset=reset)
    assert app.job['status'] == 'done', app.job['message']
    expected_pages = saved['pages'] if kind == 'analyze_all' else saved['pages'][:1]
    assert len(calls) == len(expected_pages) and not no_automatic_formula
    for page in expected_pages:
        assert [region['text'] for region in page['regions']] == texts
        assert all(region['kind'] == 'text' for region in page['regions'])
        assert all('type_decision' not in region for region in page['regions'])


def test_regular_fit_keeps_existing_formula_choice(app_project, no_automatic_formula):
    app, project = app_project
    original = formula_region()
    project['pages'][0]['regions'] = [deepcopy(original)]
    app.store.save(project)
    saved = run_job(app, project, 'fit')
    assert app.job['status'] == 'done', app.job['message']
    assert saved['pages'][0]['regions'] == [original]
    assert not no_automatic_formula


@pytest.mark.parametrize('kind', ['formula_recognize', 'formula_fit'])
@pytest.mark.parametrize('region_kind,locked', [('text', False), ('formula', True)])
def test_formula_jobs_require_an_unlocked_formula_region(
        app_project, no_automatic_formula, kind, region_kind, locked):
    app, project = app_project
    original = formula_region(kind=region_kind, locked=locked)
    project['pages'][0]['regions'] = [deepcopy(original)]
    app.store.save(project)
    saved = run_job(app, project, kind, region_id=original['id'])
    assert app.job['status'] == 'error'
    assert '请选择未锁定的公式区域' in app.job['message']
    assert saved['pages'][0]['regions'] == [original]
    assert not no_automatic_formula


@pytest.mark.parametrize('kind', ['formula_recognize', 'formula_fit'])
def test_explicit_formula_jobs_still_work(app_project, monkeypatch, kind):
    app, project = app_project
    original = formula_region()
    project['pages'][0]['regions'] = [deepcopy(original)]
    app.store.save(project)
    calls = []

    def recognize(image, region):
        calls.append('recognize')
        return 'x=3'

    def fit(image, region):
        calls.append('fit')
        return dict(region, fit_status='formula_review', font_size=30)

    monkeypatch.setattr(studio, 'recognize_formula', recognize)
    monkeypatch.setattr(studio, 'fit_formula', fit)
    saved = run_job(app, project, kind, region_id=original['id'])
    assert app.job['status'] == 'done', app.job['message']
    assert calls == (['recognize', 'fit'] if kind == 'formula_recognize' else ['fit'])
    region = saved['pages'][0]['regions'][0]
    assert region['kind'] == 'formula' and region['font_size'] == 30
    assert region['latex'] == ('x=3' if kind == 'formula_recognize' else original['latex'])
    assert region['enabled'] is False
