from copy import deepcopy
import io

import numpy as np
import pytest
import resvg_py
from PIL import Image

from ai_text_sharpener.alignment import align_page
from ai_text_sharpener.typography import candidate_fonts, outline_layout, svg_document


def sample(axis=0, factor=0):
    fid = candidate_fonts('Sample line', 1)[0]
    parts = ['<rect width="900" height="420" fill="white"/>']
    regions = []
    for index, text in enumerate(['Sample line', 'Simple', 'Second line']):
        layout = outline_layout(fid, text, 32, 0)
        w, h = layout['width'], layout['height']
        x, y = (250-factor*w, 60+index*90) if axis == 0 else (40+index*260, 180-factor*h)
        parts.append(f'<g fill="#182029" transform="translate({x} {y})">{layout["body"]}</g>')
        r = dict(id=str(index), text=text, kind='text', font_id=fid, font_size=32, letter_spacing=0,
                 bbox=[x-8, y-8, w+16, h+16], x=x, y=y, confidence=.99, score=.95,
                 enabled=True, fit_status='fitted', color='#182029', erase_mode='gradient')
        r['x' if axis == 0 else 'y'] += [1.2, -1.3, .8][index]
        regions.append(r)
    image = np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg_document(900,420,''.join(parts))))).convert('RGB'))
    return image, regions


@pytest.mark.parametrize('axis,factor',[(0,0),(0,.5),(0,1),(1,0)])
def test_source_alignment_restored_without_changing_text_or_erase_bounds(axis,factor):
    image, regions = sample(axis, factor);before = deepcopy(regions)
    assert align_page(image, regions) >= 2
    positions=[]
    for r, old in zip(regions, before):
        layout=outline_layout(r['font_id'],r['text'],r['font_size'],0)
        positions.append(r['x' if axis==0 else 'y']+factor*layout['width' if axis==0 else 'height'])
        for key in ('bbox','text','font_id','font_size','enabled','color'):
            assert r[key]==old[key]
        assert abs(r['x']-old['x'])<=3.2 and abs(r['y']-old['y'])<=3.2
    assert max(positions)-min(positions)<.02


@pytest.mark.parametrize('change',[
    {'locked':True}, {'enabled':False}, {'fit_status':'edited'}, {'confidence':.7},
    {'score':.5}, {'rotation':2}, {'source_rotation':2}, {'kind':'formula'},
])
def test_uncertain_rotated_locked_preserved_and_manual_regions_are_not_aligned(change):
    image, regions=sample();regions[0].update(change);before=deepcopy(regions)
    assert align_page(image,regions)==0 and regions==before


def test_indentation_and_large_fit_drift_are_not_flattened():
    image,regions=sample();regions[0]['x']+=20;before=deepcopy(regions)
    assert align_page(image,regions)==0 and regions==before
    image,regions=sample();image=image.copy();image[40:100]=np.roll(image[40:100],8,axis=1);regions[0]['bbox'][0]+=8;regions[0]['x']+=8
    before=deepcopy(regions)
    assert align_page(image,regions)==0 and regions==before


def test_comparison_rejects_alignment_when_original_fidelity_deteriorates(monkeypatch):
    image,regions=sample();before=deepcopy(regions)
    def score(image,box,items):
        r=items[0];old=before[int(r['id'])]
        return .95 if r['x']==old['x'] and r['y']==old['y'] else .8
    monkeypatch.setattr('ai_text_sharpener.alignment.visual_score',score)
    assert align_page(image,regions)==0 and regions==before


def test_alignment_will_not_create_collision_with_preserved_source(monkeypatch):
    image,regions=sample()
    regions.append(dict(id='protected',enabled=False,bbox=[248,60,3,24]))
    before=deepcopy(regions)
    monkeypatch.setattr('ai_text_sharpener.alignment.visual_score',lambda *args:.95)
    assert align_page(image,regions)==0 and regions==before


def test_fresh_scan_aligns_but_manual_font_fit_does_not_relayout_page(tmp_path,monkeypatch):
    from ai_text_sharpener import studio
    image,regions=sample();app=studio.Studio(tmp_path)
    project=app.store.create('alignment test')
    app.store.add_images(project,[('page',Image.fromarray(image))]);page=project['pages'][0]
    monkeypatch.setattr(studio,'detect_regions',lambda *args:deepcopy(regions))
    monkeypatch.setattr(studio,'fit_region',lambda image,r,*args:r)
    monkeypatch.setattr(studio,'recover_colors',lambda *args:{})
    try:
        app._fit_page({'kind':'analyze'},app.store.directory(project['id']),page,lambda *args:None)
        assert any(r.get('alignment_adjustment') for r in page['regions'])
        page['regions']=deepcopy(regions)
        app._fit_page({'kind':'fit'},app.store.directory(project['id']),page,lambda *args:None)
        assert page['regions']==regions
    finally:
        app.executor.shutdown()
