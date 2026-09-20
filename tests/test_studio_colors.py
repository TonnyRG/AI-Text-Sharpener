"""Color rendering, recovery, and explicit source preservation regressions."""
from copy import deepcopy
import io

import numpy as np
import pytest
import resvg_py
from PIL import Image

from ai_text_sharpener.colors import recover_colors, region_layout, validate_colors
from ai_text_sharpener.studio import create_server
from ai_text_sharpener.studio_project import compose_page, render_page, StudioStore, validate_regions, export_pages
from ai_text_sharpener.typography import candidate_fonts, outline_layout, svg_document


@pytest.fixture
def sample():
    ids = candidate_fonts('BLUE GOLD BLUE')
    if not ids:
        pytest.skip('No fonts')
    r = dict(id='abc',text='BLUE GOLD BLUE',original_text='BLUE GOLD BLUE',font_id=ids[0],
             font_size=48,letter_spacing=2,stroke_width=.5,color='#102850',x=20,y=20,
             enabled=True,locked=False,score=.9,fit_status='fitted',erase_mode='gradient')
    layout = outline_layout(ids[0],r['text'],48,2,.5)
    r['bbox']=[16,16,layout['width']+8,layout['height']+8]
    colors=tuple('#bc7610' if 5<=i<9 else '#102850' for i in range(len(r['text'])))
    colored=outline_layout(ids[0],r['text'],48,2,.5,colors)
    svg=svg_document(700,160,'<rect width="700" height="160" fill="#fffdf7"/><g transform="translate(20 20)" fill="#102850" color="#102850">'+colored['body']+'</g>')
    image=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGB'))
    return image,r


def make_project(root,image,regions):
    store=StudioStore(root);p=store.create('test');store.add_images(p,[('test',Image.fromarray(image))])
    p['pages'][0]['regions']=regions;store.save(p)
    return store,p,store.directory(p['id'])


def test_recovers_accent_without_changing_geometry(sample):
    image,r=sample;before=deepcopy(r);patch=recover_colors(image,r)
    assert r==before and patch['color_mode']=='multi'
    colors={i:c['color'] for c in patch['color_runs'] for i in range(c['start'],c['end'])}
    assert all(colors[i]==colors[5] for i in range(5,9))
    assert colors[0]!=colors[5] and colors[10]==colors[0]
    assert set(patch)<= {'color_mode','color_text','color_runs','color_source','color_note'}
    validate_colors(dict(r,**patch))


def test_colors_follow_glyphs_with_same_geometry_and_stroke(sample):
    _,r=sample;plain=region_layout(r)
    r.update(color_mode='multi',color_text=r['text'],color_runs=[dict(start=5,end=9,color='#bc7610')])
    colored=region_layout(r)
    assert colored['width']==plain['width'] and colored['height']==plain['height']
    assert colored['glyphs']==plain['glyphs']
    assert colored['body'].count('fill="#bc7610" color="#bc7610"')==4
    assert 'stroke="currentColor"' in colored['body']
    r['text']='CHANGED'
    assert '#bc7610' not in region_layout(r)['body']


def test_low_fit_and_changed_content_do_not_guess_colors(sample):
    image,r=sample;r['score']=.4
    assert 'color_runs' not in recover_colors(image,r)
    r['score']=.9;r['text']='OTHER TEXT'
    assert 'color_runs' not in recover_colors(image,r)


def test_monochrome_source_does_not_acquire_false_accents(sample):
    image,r=sample
    # Remove hue differences while retaining anti-aliasing and brightness changes.
    gray=np.mean(image,axis=2).astype(np.uint8);gray=np.repeat(gray[:,:,None],3,axis=2)
    assert 'color_runs' not in recover_colors(gray,r)


@pytest.mark.parametrize('runs',[[dict(start=0,end=99,color='#ffffff')],
    [dict(start=1,end=3,color='url(x)')],[dict(start=0,end=3,color='#ffffff'),dict(start=2,end=4,color='#000000')],
    [dict(start=True,end=3,color='#ffffff')]])
def test_rejects_invalid_color_spans(sample,runs):
    _,r=sample;r.update(color_mode='multi',color_text=r['text'],color_runs=runs)
    with pytest.raises(ValueError):validate_regions([r],700,160)


def test_explicit_preservation_survives_neighbor_erasure_and_export(sample,tmp_path):
    image,r=sample;r.update(enabled=False,preserve_original=True)
    neighbor=deepcopy(r);neighbor.update(id='other',enabled=True,preserve_original=False,fit_status='edited',text='REPLACED',x=25,y=25)
    store,p,d=make_project(tmp_path,image,[r,neighbor]);_,png=render_page(d,p['pages'][0])
    out=np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))
    x,y,w,h=map(int,r['bbox'])
    assert np.array_equal(out[y:y+h,x:x+w],image[y:y+h,x:x+w])
    # Undo restores the prior enabled state and resumes vector drawing.
    r.update(enabled=True,preserve_original=False)
    assert 'data-region-id="abc"' in compose_page(d,p['pages'][0])


def test_png_svg_and_pptx_share_multicolor_outlines(sample,tmp_path):
    import zipfile
    image,r=sample;r.update(recover_colors(image,r))
    store,p,d=make_project(tmp_path,image,[r]);svg,png=render_page(d,p['pages'][0])
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(png))),np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg)))))
    target=export_pages(d,p,scope='all',format='pptx')
    with zipfile.ZipFile(target) as z:
        vectors=[n for n in z.namelist() if n.endswith('.svg')]
        assert len(vectors)==1
        for run in r['color_runs']:assert run['color'].encode() in z.read(vectors[0])


def test_color_job_preserves_manual_locked_and_disabled_regions_and_revision(sample,tmp_path):
    image,r=sample;server=create_server(tmp_path,0);app=server.app
    try:
        p=app.store.create('colors');app.store.add_images(p,[('a',Image.fromarray(image)),('b',Image.fromarray(image))])
        for page in p['pages']:
            page['regions']=[deepcopy(r),dict(deepcopy(r),id='locked',locked=True),dict(deepcopy(r),id='manual',color_source='manual'),dict(deepcopy(r),id='off',enabled=False)]
        app.store.save(p)
        app.start_job(dict(kind='colors',scope='all',project_id=p['id'],page_id=p['pages'][0]['id'],revision=p['revision']))
        app.executor.submit(lambda:None).result(timeout=20)
        assert app.job['status']=='done',app.job
        saved=app.store.load(p['id']);assert saved['revision']==p['revision']+1
        for page in saved['pages']:
            assert page['regions'][0]['color_mode']=='multi'
            assert all('color_mode' not in r for r in page['regions'][1:])
        with pytest.raises(RuntimeError):app.start_job(dict(kind='colors',scope='all',project_id=p['id'],page_id=p['pages'][0]['id'],revision=p['revision']))
    finally:server.server_close();app.executor.shutdown()


def test_cancelling_color_job_leaves_saved_project_unchanged(sample,tmp_path,monkeypatch):
    import ai_text_sharpener.studio as studio
    image,r=sample;server=create_server(tmp_path,0);app=server.app
    try:
        p=app.store.create('cancel');app.store.add_images(p,[('a',Image.fromarray(image))]);p['pages'][0]['regions']=[r,dict(r,id='second')];app.store.save(p)
        real=studio.recover_colors
        def cancel_after_first(*args):
            result=real(*args);app.cancelled.set();return result
        monkeypatch.setattr(studio,'recover_colors',cancel_after_first)
        app.start_job(dict(kind='colors',scope='all',project_id=p['id'],page_id=p['pages'][0]['id'],revision=p['revision']))
        app.executor.submit(lambda:None).result(timeout=20)
        assert app.job['status']=='cancelled';assert app.store.load(p['id'])==p
    finally:server.server_close();app.executor.shutdown()
