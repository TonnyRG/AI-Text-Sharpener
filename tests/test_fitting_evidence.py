"""Image-based regressions for line contamination, digit direction and weight."""
import io
import math

import numpy as np
import pytest
import resvg_py
from PIL import Image, ImageFilter

from ai_text_sharpener.fidelity import crop_evidence, erase_regions, fit_region
from ai_text_sharpener.typography import font_catalog, outline_layout, svg_document


@pytest.fixture(scope="module")
def faces():
    for family in ("Liberation Sans", "Arial", "DejaVu Sans"):
        fonts = {f['style']: f['id'] for f in font_catalog().values()
                 if family in f.get('aliases', [f['family']])}
        if 'Regular' in fonts and 'Bold' in fonts:
            return fonts
    pytest.skip('An installed Regular/Bold Latin font pair is required')


def scene(fid, text, size=44, angle=0, badge=False):
    layout = outline_layout(fid, text, size, 0)
    w, h = layout['width'], layout['height']
    x, y = 100, 80
    matrix = np.array([[math.cos(math.radians(angle)), -math.sin(math.radians(angle))],
                       [math.sin(math.radians(angle)), math.cos(math.radians(angle))]])
    quad = np.array([[-w/2, -h/2], [w/2, -h/2], [w/2, h/2], [-w/2, h/2]]) @ matrix.T + [x+w/2, y+h/2]
    low, high = quad.min(axis=0)-5, quad.max(axis=0)+5
    background = '<rect width="800" height="220" fill="#eeeeee"/>'
    if badge:
        background += f'<circle cx="{x+w/2}" cy="{y+h/2}" r="{h*.8}" fill="#b41a26"/>'
    svg = svg_document(800, 220, background +
        f'<g fill="{"white" if badge else "#202020"}" transform="translate({x} {y}) rotate({angle} {w/2} {h/2})">{layout["body"]}</g>')
    image = np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGB'))
    region = dict(id='sample', text=text, original_text=text, bbox=[*low, *(high-low)],
                  x=x, y=y, font_id=fid, font_size=size, letter_spacing=0, color='#202020',
                  source_rotation=angle, rotation=angle, source_quad=quad.tolist(),
                  enabled=True, erase_mode='gradient')
    return image, region, layout


@pytest.mark.parametrize('edge', ['top', 'bottom'])
def test_neighbor_line_fragments_do_not_enlarge_or_erase_current_line(faces, edge):
    image, region, layout = scene(faces['Regular'], 'a guide for annotation')
    image = image.copy()
    # A preceding descender or following ascender barely intrudes into the crop.
    region['bbox'] = [90, 60, layout['width']+20, layout['height']+40]
    row = 60 if edge == 'top' else math.ceil(60+region['bbox'][3])-3
    image[row:row+3, 160:170] = 32
    fitted = fit_region(image, region, [faces['Regular']])
    assert abs(fitted['font_size']-44) <= 1
    assert abs(fitted['letter_spacing']) <= 1
    assert abs(fitted['y']-80) < 2
    erased = erase_regions(image, [fitted])
    assert np.array_equal(erased[row:row+3, 160:170], image[row:row+3, 160:170])
    assert erased[80:100, 110:150].mean() > image[80:100, 110:150].mean()


def test_line_filter_retains_dots_accents_and_punctuation(faces):
    image, r, _ = scene(faces['Regular'], 'ï i : j, café')
    plain = crop_evidence(image, r['bbox'])
    filtered = crop_evidence(image, r['bbox'], single_line=True)
    assert np.array_equal(plain['binary'], filtered['binary'])
    assert np.array_equal(plain['mask'], filtered['mask'])


@pytest.mark.parametrize('angle', [-4, 14, 90])
def test_isolated_upright_digit_rejects_noisy_ocr_angle(faces, angle):
    image, region, layout = scene(faces['Regular'], '4', badge=True)
    region['source_rotation'] = region['rotation'] = angle
    result = fit_region(image, region, [faces['Regular'], faces['Bold']])
    assert result['rotation'] == result['source_rotation'] == 0
    assert result['ocr_rotation'] == angle
    assert result['source_quad'] == region['source_quad']
    assert abs(result['font_size']-44) <= 2
    assert abs(result['x']-100) < 2 and abs(result['y']-80) < 2


@pytest.mark.parametrize('angle', [-25, 14, 90, -90, 180])
def test_genuinely_rotated_single_character_keeps_its_direction(faces, angle):
    image, region, _ = scene(faces['Regular'], 'R', angle=angle)
    result = fit_region(image, region, [faces['Regular']])
    assert result['rotation'] == angle
    assert result['source_rotation'] == angle
    assert abs(result['font_size']-44) <= 2


def test_badge_corners_are_not_counted_as_digit_ink_or_erased(faces):
    image, region, layout = scene(faces['Regular'], '4', badge=True)
    x, y, w, h = region['bbox']
    # Widen the OCR crop until its corners extend outside the circle.
    region['bbox'] = [x-8, y-2, w+16, h+4]
    result = fit_region(image, region, [faces['Regular']])
    assert abs(result['font_size']-44) <= 2
    erased = erase_regions(image, [result])
    x, y, w, h = map(int, region['bbox'])
    assert np.array_equal(erased[y:y+2, x:x+2], image[y:y+2, x:x+2])


@pytest.mark.parametrize('style', ['Regular', 'Bold'])
@pytest.mark.parametrize('blur', [.3, .7])
def test_weight_matching_preserves_both_regular_and_bold(faces, style, blur):
    image, region, _ = scene(faces[style], 'MS/MS 123 annotation', size=34)
    image = np.asarray(Image.fromarray(image).filter(ImageFilter.GaussianBlur(blur)))
    result = fit_region(image, region, [faces['Bold'], faces['Regular']])
    assert result['font_id'] == faces[style]
    assert result['score'] > .8
    assert result['font_size'].is_integer() and result['letter_spacing'].is_integer()
