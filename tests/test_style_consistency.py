from copy import deepcopy
import io

import numpy as np
import pytest
import resvg_py
from PIL import Image

from ai_text_sharpener.classification import visual_score
from ai_text_sharpener.fidelity import fit_region_at_size
from ai_text_sharpener.style_consistency import normalize_page
from ai_text_sharpener.typography import candidate_fonts, font_catalog, outline_layout, svg_document


def sample(sizes=(32, 31, 32), source_sizes=None, words=None, positions=None, faces=None):
    catalog = font_catalog()
    fid = next((f['id'] for f in catalog.values()
                if f['family'] == 'Liberation Sans' and f['style'] == 'Regular'), candidate_fonts('soft', 1)[0])
    source_sizes = source_sizes or [32]*len(sizes)
    words = words or ['soft']*len(sizes)
    faces = faces or [fid]*len(sizes)
    parts = ['<rect width="1100" height="600" fill="white"/>']
    regions = []
    for index, (size, source_size, text, face) in enumerate(zip(sizes, source_sizes, words, faces)):
        layout = outline_layout(face, text, source_size, 0)
        x, y = positions[index] if positions else (60, 40+index*70)
        parts.append(f'<g fill="#182029" transform="translate({x} {y})">{layout["body"]}</g>')
        regions.append(dict(id=str(index), text=text, kind='text', font_id=face, font_size=size,
                            letter_spacing=0, stroke_width=0, x=x, y=y,
                            bbox=[x-8, y-8, layout['width']+16, layout['height']+16],
                            confidence=.99, score=.95, enabled=True, fit_status='fitted',
                            color='#182029', erase_mode='gradient'))
    image = np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(
        svg_string=svg_document(1100, 600, ''.join(parts))))).convert('RGB'))
    return image, regions


@pytest.mark.parametrize('positions', [None, [(40, 60), (180, 60), (320, 60)]])
def test_local_column_or_row_majority_corrects_small_size_error(positions):
    image, regions = sample(positions=positions)
    regions[1].update(color_mode='multi', color_runs=[{'start': 0, 'end': 2, 'color': '#ff0000'}])
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 1
    assert [r['font_size'] for r in regions] == [32, 32, 32]
    assert regions[0] == before[0] and regions[2] == before[2]
    r = regions[1]
    changed_keys = {'font_size', 'letter_spacing', 'x', 'y', 'score', 'size_normalization'}
    assert {key: value for key, value in r.items() if key not in changed_keys} == {
        key: value for key, value in before[1].items() if key not in changed_keys}
    assert r['size_normalization']['before']['font_size'] == 31
    assert r['size_normalization']['visual_after'] >= r['size_normalization']['visual_before']-.02
    assert normalize_page(image, regions) == 0


@pytest.mark.parametrize('change', [
    {'locked': True}, {'enabled': False}, {'preserve_original': True}, {'fit_status': 'edited'},
    {'confidence': .8}, {'score': .6}, {'kind': 'formula'}, {'rotation': 2},
    {'source_rotation': 2}, {'type_review': True}, {'text': 's'},
])
def test_ineligible_regions_are_not_normalized(change):
    image, regions = sample()
    regions[1].update(change)
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0
    assert regions == before


@pytest.mark.parametrize('sizes', [
    [32, 32, 40], [31, 32, 31, 32], [40, 41, 42], [39, 40, 40, 41, 42], [16, 17, 17],
])
def test_hierarchy_majority_ties_and_wide_or_chained_spans_are_preserved(sizes):
    image, regions = sample(sizes=sizes, source_sizes=sizes)
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0
    assert regions == before


@pytest.mark.parametrize('positions', [
    [(60, 40), (300, 110), (60, 180)],
    [(60, 40), (60, 280), (60, 520)],
])
def test_distinct_columns_or_distant_blocks_are_not_a_majority(positions):
    image, regions = sample(positions=positions)
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0
    assert regions == before


def test_different_font_faces_and_synthetic_weight_remain_separate():
    image, regions = sample()
    other = next(fid for fid in candidate_fonts('soft') if fid != regions[0]['font_id'])
    regions[1]['font_id'] = other
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0 and regions == before
    image, regions = sample()
    regions[1]['stroke_width'] = .5
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0 and regions == before


def test_real_long_line_with_intentionally_smaller_size_is_rejected_by_pixels():
    image, regions = sample(source_sizes=[32, 31, 32],
                            words=['soft', 'A relatively long line of ordinary words', 'soft'])
    before = deepcopy(regions)
    original = visual_score(image, regions[1]['bbox'], [regions[1]])
    candidate = fit_region_at_size(image, regions[1], 32)
    assert original >= .95
    assert visual_score(image, regions[1]['bbox'], [candidate]) < original-.02
    assert normalize_page(image, regions) == 0
    assert regions == before


def test_rejected_group_does_not_partially_change_earlier_minority():
    image, regions = sample(sizes=[32, 31, 32, 31, 32], source_sizes=[32, 32, 32, 31, 32])
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0
    assert regions == before


def test_stale_fit_score_does_not_replace_current_pixel_validation():
    image, regions = sample(words=['soft', 'A relatively long line of ordinary words', 'soft'])
    before = deepcopy(regions)
    assert visual_score(image, regions[1]['bbox'], [regions[1]]) < .65
    assert normalize_page(image, regions) == 0 and regions == before


def test_clipped_source_crop_is_not_normalized():
    image, regions = sample()
    regions[1]['bbox'][0] += 8
    regions[1]['bbox'][2] -= 8
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0 and regions == before


def test_normalization_will_not_create_collision_with_preserved_source():
    image, regions = sample()
    r = regions[1]
    old_width = outline_layout(r['font_id'], r['text'], r['font_size'])['width']
    regions.append(dict(id='original', enabled=False,
                        bbox=[r['x']+old_width+.1, r['y'], 2, 24]))
    before = deepcopy(regions)
    assert normalize_page(image, regions) == 0 and regions == before


def test_fixed_size_fit_keeps_exact_size_and_font_face():
    image, regions = sample()
    result = fit_region_at_size(image, regions[1], 32)
    assert result['font_size'] == 32 and result['font_id'] == regions[1]['font_id']
    assert visual_score(image, regions[1]['bbox'], [result]) > .95
    with pytest.raises(ValueError):
        fit_region_at_size(image, regions[1], 31.5)


def test_current_font_alternative_follows_accepted_size_without_changing_other_faces():
    image, regions = sample()
    r = regions[1]
    other = next(fid for fid in candidate_fonts('soft') if fid != r['font_id'])
    r['alternatives'] = [dict(font_id=r['font_id'], font_size=31, letter_spacing=0, x=60, y=110, score=.95),
                         dict(font_id=other, font_size=30, score=.9)]
    before_other = deepcopy(r['alternatives'][1])
    assert normalize_page(image, regions) == 1
    assert r['alternatives'][0]['font_size'] == r['font_size'] == 32
    assert r['alternatives'][0]['score'] == r['score']
    assert r['alternatives'][1] == before_other


def test_fresh_scan_normalizes_but_manual_font_fit_keeps_peer_sizes(tmp_path, monkeypatch):
    from ai_text_sharpener import studio
    image, regions = sample()
    app = studio.Studio(tmp_path)
    project = app.store.create('size consensus test')
    app.store.add_images(project, [('page', Image.fromarray(image))])
    page = project['pages'][0]
    monkeypatch.setattr(studio, 'detect_regions', lambda *args: deepcopy(regions))
    monkeypatch.setattr(studio, 'fit_region', lambda image, r, *args: r)
    monkeypatch.setattr(studio, 'recover_colors', lambda *args: {})
    try:
        app._fit_page({'kind': 'analyze'}, app.store.directory(project['id']), page, lambda *args: None)
        assert page['regions'][1]['size_normalization']['before']['font_size'] == 31
        assert [r['font_size'] for r in page['regions']] == [32, 32, 32]
        page['regions'] = deepcopy(regions)
        app._fit_page({'kind': 'fit'}, app.store.directory(project['id']), page, lambda *args: None)
        assert page['regions'] == regions
    finally:
        app.executor.shutdown()
