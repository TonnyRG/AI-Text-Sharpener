"""Explicit LaTeX inside one editable ordinary text region, from preview to export."""
import io
import math
import zipfile
from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
import pytest
import resvg_py
from lxml import etree
from PIL import Image

from ai_text_sharpener import formula
from ai_text_sharpener.colors import region_layout
from ai_text_sharpener.inline_math import split_inline_math
from ai_text_sharpener.studio_project import StudioStore, compose_page, export_pages, render_page
from ai_text_sharpener.typography import candidate_fonts, outline_layout, svg_document


@pytest.fixture(scope='module')
def face():
    return candidate_fonts('中H文', limit=1)[0]


def text_region(face, text):
    return dict(id='caption', kind='text', text=text, original_text='OCR source',
                bbox=[16, 14, 560, 85], x=20, y=18, font_id=face, font_size=32,
                letter_spacing=0, stroke_width=0, color='#000000', enabled=True,
                fit_status='edited', erase_mode='none')


@pytest.fixture
def math_renderer(monkeypatch):
    """Ink above and below a known baseline without requiring MathJax in CI."""
    calls = []

    def layout(latex, size, stroke_width=0):
        calls.append(latex)
        if latex == r'\badCommand':
            raise ValueError('公式排版失败')
        scale = size / 32
        # Base rectangle ends at the baseline. Its separate subscript descends 6 px.
        return {'body': f'<path transform="scale({scale})" d="M0 0H18V18H0Z M21 15H29V24H21Z"/>',
                'width': 29 * scale, 'height': 24 * scale, 'baseline': 18 * scale,
                'left': 0, 'advance': 31 * scale}

    monkeypatch.setattr(formula, 'formula_layout', layout)
    outline_layout.cache_clear()
    yield calls
    outline_layout.cache_clear()


def raster(layout):
    svg = svg_document(math.ceil(layout['width']) + 2, math.ceil(layout['height']) + 2,
                       '<g color="#000000" fill="#000000">' + layout['body'] + '</g>')
    return np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGBA'))


def test_explicit_delimiters_preserve_original_character_offsets():
    source = r'🧪 中\[w_C\]文\(a^2\) $$\frac{1}{2}$$，$100'
    spans = split_inline_math(source)
    assert ''.join(source[s.start:s.end] for s in spans) == source
    math_spans = [s for s in spans if s.kind == 'math']
    assert [s.value for s in math_spans] == ['w_C', 'a^2', r'\frac{1}{2}']
    assert [source[s.start:s.end] for s in math_spans] == [r'\[w_C\]', r'\(a^2\)', r'$$\frac{1}{2}$$']


@pytest.mark.parametrize('source', ['6,738 100% x_2', '$100 and $200', r'\[w_C', r'\[  \]'])
def test_plain_or_unfinished_input_uses_the_plain_layout(face, source, math_renderer):
    region = text_region(face, source)
    assert region_layout(region) == outline_layout(face, source, 32)
    assert math_renderer == []


def test_identical_ocr_source_requires_an_explicit_edit_to_compile(tmp_path, face, math_renderer):
    source = r'\[w_C\]'
    region = text_region(face, source)
    region['original_text'] = source
    literal = region_layout(region)
    assert [glyph['start'] for glyph in literal['glyphs']] == list(range(len(source)))
    legacy = dict(region)
    del legacy['original_text']
    assert region_layout(legacy) == literal
    assert not math_renderer

    # A user can type the same visible string as the original OCR. Their
    # explicit format must survive saving and apply even after reopening.
    region['text_format'] = 'inline_math'
    store = StudioStore(tmp_path)
    project = store.create('identical source')
    store.add_images(project, [('page', Image.new('RGB', (600, 180), 'white'))])
    project['pages'][0]['regions'] = [region]
    store.save(project)
    [reopened] = store.load(project['id'])['pages'][0]['regions']
    compiled = region_layout(reopened)
    assert math_renderer == ['w_C']
    assert len(compiled['glyphs']) == 1 and compiled['body'] != literal['body']
    # Previously saved manual edits may have no explicit format field.
    edited = dict(legacy, original_text='OCR')
    assert region_layout(edited) == compiled
    # Caching a formula rendering must not alter a literal of the same text.
    assert region_layout(dict(legacy, original_text=source)) == literal


def test_mixed_spans_share_the_text_baseline_and_follow_source_colors(face, math_renderer):
    source = r'中\[w_C\]H\[x^2\]文'
    region = text_region(face, source)
    runs = [dict(start=source.index(char), end=source.index(char) + 1, color=color)
            for char, color in [('w', '#ff0000'), ('H', '#00ff00'), ('x', '#0000ff')]]
    region.update(color_text=source, color_mode='multi', color_runs=runs)
    rgba = raster(region_layout(region))
    masks = [np.all(rgba[:, :, :3] == rgb, axis=2) & (rgba[:, :, 3] > 200)
             for rgb in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    red, green, blue = [np.where(mask) for mask in masks]
    assert all(len(y) for y, x in (red, green, blue))
    assert red[1].max() < green[1].min() < green[1].max() < blue[1].min()
    # Inspect solid colored glyph pixels. The upper red glyph and H share a
    # baseline, and the red subscript sits lower and to the right of its base.
    base_y = red[0][red[1] < red[1].min() + 18]
    sub_y = red[0][red[1] > red[1].min() + 19]
    assert abs(int(base_y.max()) - int(green[0].max())) <= 2
    assert sub_y.min() >= base_y.min() + 12 and sub_y.max() >= base_y.max() + 4
    assert set(math_renderer) == {'w_C', 'x^2'}
    assert region['text'] == source and region['kind'] == 'text'


def test_inline_preview_and_export_keep_one_region_and_the_editable_source(tmp_path, face, math_renderer):
    store = StudioStore(tmp_path)
    project = store.create('inline')
    store.add_images(project, [('page', Image.new('RGB', (600, 180), 'white'))])
    directory = store.directory(project['id'])
    page = project['pages'][0]
    source = r'中文 \[w_C\]'
    region = text_region(face, source)
    page['regions'] = [region]
    preview = compose_page(directory, deepcopy(page))
    svg = export_pages(directory, project, format='svg', scope='current', page_id=page['id'])
    assert svg.read_text() == preview
    _, preview_png = render_page(directory, page)
    pptx = export_pages(directory, project, format='pptx')
    with zipfile.ZipFile(pptx) as package:
        assert package.read('ppt/media/image_vector_1.svg') == preview.encode()
        assert package.read('ppt/media/image1.png') == preview_png
        notes = etree.fromstring(package.read('ppt/notesSlides/notesSlide1.xml'))
        assert source in notes.xpath('.//*[local-name()="t"]/text()')
    store.save(project)
    [saved] = store.load(project['id'])['pages'][0]['regions']
    assert saved['text'] == source and saved['kind'] == 'text'
    assert saved['original_text'] == 'OCR source'
    assert preview.count('data-region-id="caption"') == 1
    assert 'w_C' in math_renderer

    # A typo can be corrected in the same text box, and the last successful
    # preview remains available until the corrected source has rendered.
    old_png = directory / f"{page['id']}-result.png"
    region['text'] = r'中\[\badCommand\]'
    with pytest.raises(ValueError):
        render_page(directory, page)
    assert old_png.read_bytes() == preview_png
    region['text'] = r'中\[x^2\]'
    render_page(directory, page)
    assert 'x^2' in math_renderer


def test_mathjax_renders_real_w_subscript_c_as_paths_in_one_plain_region(face):
    try:
        config = formula.runtime_config()
    except ValueError:
        pytest.skip('optional MathJax runtime is not installed')
    if not Path(config['node']).is_file() or not (formula.formula_root() / 'mathjax/package/js/mathjax.js').is_file():
        pytest.skip('optional MathJax runtime is not installed')
    region = text_region(face, r'\[w_C\]')
    region['font_size'] = 64
    layout = region_layout(region)
    assert 'data-mml-node="msub"' in layout['body']
    ink = (raster(layout)[:, :, 3] >= 100).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    base, sub = sorted(stats[1:], key=lambda box: box[0])
    assert sub[0] > base[0] and sub[2] < base[2]
    assert sub[1] > base[1] and sub[1] + sub[3] > base[1] + base[3]
