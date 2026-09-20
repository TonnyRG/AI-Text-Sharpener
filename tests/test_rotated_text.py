"""Rotation must agree across source fitting, erasure, vector output and persistence."""
import io
import math
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
import resvg_py
from PIL import Image

from ai_text_sharpener.fidelity import fit_region, erase_regions
from ai_text_sharpener.geometry import round_style
from ai_text_sharpener.studio_project import StudioStore, compose_page, validate_regions, export_vector_pptx
from ai_text_sharpener.typography import candidate_fonts, outline_layout, svg_document


def rotated_sample(angle=27):
    text='Rotation sample'
    fid=candidate_fonts(text,1)[0]
    layout=outline_layout(fid,text,42,1)
    x,y,w,h=220,200,layout['width'],layout['height']
    theta=math.radians(angle);rotation=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    quad=(np.array([[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]])@rotation.T+np.array([x+w/2,y+h/2]))
    low,high=quad.min(axis=0)-3,quad.max(axis=0)+3
    svg=svg_document(900,650,f'<rect width="900" height="650" fill="white"/><g fill="#182029" transform="translate({x} {y}) rotate({angle} {w/2} {h/2})">{layout["body"]}</g>')
    image=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGB'))
    region=dict(id='rotation',text=text,original_text=text,font_id=fid,font_size=42,letter_spacing=1,
        x=x,y=y,rotation=angle,source_rotation=angle,source_quad=quad.tolist(),
        bbox=[*low,*(high-low)],enabled=True,color='#182029',erase_mode='gradient',stroke_width=0)
    return image,region,layout


@pytest.mark.parametrize('angle',[-25,27,90,-90,180])
def test_deskewed_fitting_recovers_angle_size_and_center(angle):
    image,region,layout=rotated_sample(angle)
    result=fit_region(image,region,[region['font_id']])
    assert result['enabled']
    assert result['rotation']==angle
    assert result['score']>.82
    assert abs(result['font_size']-42)<2
    fitted=outline_layout(result['font_id'],result['text'],result['font_size'],result['letter_spacing'])
    assert abs(result['x']+fitted['width']/2-(region['x']+layout['width']/2))<2
    assert abs(result['y']+fitted['height']/2-(region['y']+layout['height']/2))<2
    assert result['source_quad']==region['source_quad']
    assert all(c['rotation']==angle for c in result['alternatives'])


@pytest.mark.parametrize('mode',['gradient','inpaint'])
def test_rotated_erasure_keeps_art_outside_the_original_line(mode):
    image,r,_=rotated_sample();image=image.copy();r['erase_mode']=mode
    # Inside the diagonal line's bounding box, outside the actual rotated line.
    x,y=int(r['bbox'][0])+4,int(r['bbox'][1])+4
    image[y:y+7,x:x+7]=(220,20,20)
    moved=dict(r,x=20,y=30,rotation=-60)
    erased=erase_regions(image,[moved])
    assert np.array_equal(erased[y:y+7,x:x+7],image[y:y+7,x:x+7])
    dark=(image[:,:,0]<100)
    assert np.mean(erased[dark])>248


def test_export_rotates_outline_and_preserves_source_parameters(tmp_path):
    image,r,layout=rotated_sample(90)
    store=StudioStore(tmp_path);project=store.create('rotation');store.add_images(project,[('one',Image.fromarray(image))])
    page=project['pages'][0];page['regions']=[r]
    svg=compose_page(store.directory(project['id']),page)
    assert 'rotate(90 ' in svg and '<path ' in svg
    path=export_vector_pptx(store.directory(project['id']),project)
    with zipfile.ZipFile(path) as package:
        exported=package.read('ppt/media/image_vector_1.svg').decode()
        assert 'rotate(90 ' in exported
    rendered=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGB'))
    assert np.mean(np.abs(rendered.astype(float)-image))<.3
    store.save(project);saved=store.load(project['id'])['pages'][0]['regions'][0]
    assert saved['rotation']==90 and saved['source_quad']==r['source_quad']


@pytest.mark.parametrize('value',[float('nan'),float('inf'),181,'30'])
def test_invalid_rotation_is_rejected(value):
    _,r,_=rotated_sample();r['rotation']=value
    with pytest.raises(ValueError,match='角度'):
        validate_regions([r],900,650)


def test_half_up_style_rounding():
    assert [round_style(v) for v in [12.49,12.5,-1.5,-1.49,0]]==[12,13,-2,-1,0]


@pytest.mark.parametrize('angle,vertical,flip',[(27,False,False),(90,True,False),(-90,True,True),(180,False,True)])
def test_detection_keeps_line_direction_and_enables_rotated_text(monkeypatch,tmp_path,angle,vertical,flip):
    from ai_text_sharpener import studio
    image,r,_=rotated_sample(angle)
    points=np.array(r['source_quad'])
    if flip:points=points[[2,3,0,1]]
    if vertical:points=points[[3,0,1,2]]
    def recognize(*args,**kwargs):
        return SimpleNamespace(boxes=np.array([points]),txts=[r['text']],scores=[.99],word_results=())
    recognize.text_cls=lambda crops:SimpleNamespace(cls_res=[('180' if flip else '0',.99)])
    recognize.text_cls.cls_thresh=.9
    monkeypatch.setattr(studio,'ocr_engine',lambda:recognize)
    monkeypatch.setattr(studio,'detect_formulas',lambda im:[])
    path=tmp_path/'input.png';Image.fromarray(image).save(path)
    result=studio.detect_regions(path)[0]
    assert result['enabled']
    assert abs((result['source_rotation']-angle+180)%360-180)<.1
    assert result['rotation']==result['source_rotation']
