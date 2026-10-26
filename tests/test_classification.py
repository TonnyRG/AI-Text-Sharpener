"""Routing and common-canvas comparisons; no model downloads needed."""
from copy import deepcopy
from types import SimpleNamespace
import io

import cv2
import numpy as np
import pytest
import resvg_py
from PIL import Image

from ai_text_sharpener import classification as c
from ai_text_sharpener.typography import candidate_fonts, font_catalog, outline_layout, svg_document


@pytest.mark.parametrize('text',['LC-MS','m/z','70%–130%','MS/MS fragments','Nature Methods','质谱 LC-MS 分析','10 mg/mL',
                                '6,738','100%','100％','12.5%','6738','6,738.50','−12.5','+12.5%',
                                '$6,738','￥６，７３８','1\u202f234.5','2‰'])
def test_labels_are_not_math_just_for_punctuation(text):
    assert c.lexical_kind(text)=='text'


@pytest.mark.parametrize('text',['E=mc²','x+y','p<0.05','x_1','∫f(x)dx'])
def test_expressions_are_proposals_not_automatic_type_decisions(text):
    assert c.lexical_kind(text)=='math'


def sample(text='p<0.05', *, font_id=None, font_size=36):
    fid=font_id or candidate_fonts(text,1)[0];layout=outline_layout(fid,text,font_size,0)
    svg=svg_document(400,120,'<rect width="400" height="120" fill="white"/><g fill="#202020" transform="translate(30 30)">'+layout['body']+'</g>')
    im=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGB'))
    r=dict(id='text',kind='text',text=text,original_text=text,confidence=.99,
           bbox=[25,25,layout['width']+10,layout['height']+10],x=30,y=30,
           font_id=fid,font_size=font_size,letter_spacing=0,enabled=True,locked=False,color='#202020',erase_mode='gradient')
    return im,r


@pytest.mark.parametrize('text', ['1/2', '1+2', '10²', '10^2', '1_2', '2×3', '6,73,8'])
def test_numeric_label_does_not_erase_formula_or_malformed_grouping(text):
    assert not c.numeric_label(text)


@pytest.mark.parametrize('text', ['6,738', '100%', '12.5%', '70%–130%'])
@pytest.mark.parametrize('size', [24, 36, 54])
def test_rendered_numeric_punctuation_does_not_create_script_structure(text, size):
    for fid in candidate_fonts(text, 7)[::3]:
        image, region = sample(text, font_id=fid, font_size=size)
        assert c.structure(image, region) == {'fraction': False, 'scripts': False}, font_catalog()[fid]['label']


def installed_face(family, style):
    matches = [f['id'] for f in font_catalog().values() if f['family'] == family and f['style'] == style]
    if not matches:
        pytest.skip(f'{family} {style} is not installed')
    return matches[0]


@pytest.mark.parametrize('family,style', [
    ('Liberation Sans', 'Bold'), ('Liberation Serif', 'Regular'), ('Liberation Serif', 'Bold Italic'),
    ('Liberation Mono', 'Regular'), ('Carlito', 'Bold'), ('Noto Sans', 'Italic'),
    ('DejaVu Sans', 'Bold'), ('DejaVu Serif', 'Bold'),
])
@pytest.mark.parametrize('size', [24, 36, 54])
def test_numeric_structure_across_explicit_system_fonts(family, style, size):
    # Candidate ranking depends on installed fonts. These explicit faces cover
    # serif comma tails, slanted stems, joined percent rings, and ring/dash joins.
    fid = installed_face(family, style)
    for text in ['6,738', '100%', '12.5%', '70%–130%']:
        image, region = sample(text, font_id=fid, font_size=size)
        assert c.structure(image, region) == {'fraction': False, 'scripts': False}, (family, style, size, text)


@pytest.mark.parametrize('text', ['6,738', '100%', '100％', '$6,738', '−12.5', '6738'])
def test_confident_numeric_labels_bypass_both_recognizers(text):
    image, region = sample(text)
    def unexpected(*args, **kwargs):
        raise AssertionError('A flat numeric label should not need formula recognition')
    result = c.resolve_types(image, [region], [{'bbox': region['bbox'], 'confidence': .99}],
                             engine=unexpected, detect=unexpected, recognize=unexpected, fit_math=unexpected)
    assert result == [region]


def script_sample(text='100%', *, subscript=False, font_id=None):
    image, region = sample(text, font_id=font_id)
    base = outline_layout(region['font_id'], text, 36, 0)
    script = outline_layout(region['font_id'], '2', 18, 0)
    script_x, script_y = 30+base['width']+2, 30+(base['height']-3 if subscript else -5)
    body = ('<rect width="400" height="120" fill="white"/>'
            f'<g fill="#202020" transform="translate(30 30)">{base["body"]}</g>'
            f'<g fill="#202020" transform="translate({script_x} {script_y})">{script["body"]}</g>')
    image = np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg_document(400,120,body)))).convert('RGB'))
    # Simulate OCR flattening the layout and retaining only the digit transcript.
    region.update(text=text+'2', original_text=text+'2',
                  bbox=[25, min(25,script_y-5), base['width']+script['width']+12,
                        max(30+base['height'],script_y+script['height'])-min(25,script_y-5)+5])
    return image, region


@pytest.mark.parametrize('text', ['100%', '6,738', '10'])
@pytest.mark.parametrize('subscript', [False, True])
def test_real_rendered_scripts_remain_structural_even_with_numeric_ocr(text, subscript):
    image, region = script_sample(text, subscript=subscript)
    assert c.structure(image, region)['scripts']


def test_percent_transcript_without_percent_ink_does_not_hide_a_script():
    image, region = script_sample('100')
    region['text'] = '100%'
    assert c.structure(image, region)['scripts']


@pytest.mark.parametrize('family,style', [('Noto Sans', 'Italic'), ('DejaVu Serif', 'Bold')])
@pytest.mark.parametrize('subscript', [False, True])
def test_joined_percent_ring_preserves_genuine_script_anchor(family, style, subscript):
    image, region = script_sample('100%', subscript=subscript, font_id=installed_face(family, style))
    assert c.structure(image, region)['scripts'], (family, style, subscript)


def test_numeric_ocr_does_not_hide_stacked_fraction():
    fid = candidate_fonts('12',1)[0]
    one = outline_layout(fid,'1',32,0); two = outline_layout(fid,'2',32,0)
    body = ('<rect width="160" height="120" fill="white"/>'
            f'<g transform="translate(50 12)">{one["body"]}</g>'
            f'<g transform="translate(50 68)">{two["body"]}</g>'
            '<rect x="38" y="50" width="45" height="2"/>')
    image = np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg_document(160,120,body)))).convert('RGB'))
    region = dict(text='12',bbox=[30,5,65,100])
    assert c.lexical_kind(region['text']) == 'text'
    assert c.structure(image,region)['fraction']
    assert not c._safe_text_proposal(image, dict(region,confidence=.99), region['bbox'])


def test_detector_extent_keeps_script_omitted_by_numeric_ocr():
    image, full = script_sample('6738')
    _, ocr = sample('6738')
    # A tight OCR box covers most of the detector but omits the top-right script.
    ocr['bbox'][2] -= 5
    ocr['bbox'][0] += 3
    assert c._covers(ocr, full['bbox'])
    assert not c.structure(image,ocr)['scripts']
    assert not c._safe_text_proposal(image,ocr,full['bbox'])


@pytest.mark.parametrize('confidence', [.7, .9])
def test_low_confidence_numeric_ocr_still_requires_review(monkeypatch, confidence):
    image, region = sample('100%')
    region['confidence'] = confidence
    monkeypatch.setattr(c,'local_retry',lambda *args,**kwargs:([],[]))
    def unavailable(*args):
        raise ValueError('No reliable formula candidate')
    result = c.resolve_types(image,[region],[dict(bbox=region['bbox'],confidence=.99)],
                             engine=None,detect=None,recognize=unavailable,fit_math=None)
    assert len(result) == 1 and result[0]['preserve_original']
    assert result[0]['type_decision']['choice'] == 'uncertain'


def test_structure_distinguishes_fraction_from_underline():
    im=np.full((100,160,3),255,np.uint8)
    cv2.rectangle(im,(35,48),(110,50),(0,0,0),-1)
    cv2.rectangle(im,(55,15),(70,38),(0,0,0),-1)
    region=dict(text='x/y',bbox=[20,5,110,90])
    assert not c.structure(im,region)['fraction']
    cv2.rectangle(im,(60,65),(75,86),(0,0,0),-1)
    assert c.structure(im,region)['fraction']


def test_structure_distinguishes_superscript_from_same_baseline():
    im=np.full((90,130,3),255,np.uint8)
    cv2.rectangle(im,(20,35),(35,65),(0,0,0),-1)
    cv2.rectangle(im,(40,20),(47,35),(0,0,0),-1)
    r=dict(text='x2',bbox=[5,5,90,75])
    assert c.structure(im,r)['scripts']
    im[20:36,40:48]=255;im[50:66,40:48]=0
    assert not c.structure(im,r)['scripts']


def test_local_retry_maps_scaled_boxes_and_excludes_context():
    im=np.full((140,280,3),255,np.uint8);seen=[]
    def engine(crop,**kwargs):
        seen.append(crop.shape)
        # Original context starts at (42,32); expected glyph (55,45)-(105,65).
        return SimpleNamespace(boxes=np.array([[[26,26],[126,26],[126,66],[26,66]],[[0,0],[8,0],[8,8],[0,8]]]),txts=['LC-MS','noise'],scores=[.99,.99])
    lines,formula=c.local_retry(im,[50,40,100,30],engine,lambda a:[dict(bbox=[26,26,100,40],confidence=.9)])
    assert seen==[(92,232,3)]
    assert len(lines)==1 and lines[0]['bbox']==[55,45,50,20]
    assert formula[0]['bbox']==[55,45,50,20]


@pytest.mark.parametrize('a,b,complex_layout,reliable,expected',[
    (.95,.65,False,True,'text'),(.85,.84,False,True,'uncertain'),
    (.45,.5,False,True,'uncertain'),(.94,None,False,True,'text'),
    (.94,.8,True,True,'uncertain'),(.6,.9,True,True,'formula'),
    (.94,.6,False,False,'uncertain'),(None,None,False,False,'uncertain'),
])
def test_routing_requires_absolute_quality_and_clear_margin(a,b,complex_layout,reliable,expected):
    assert c.choose_type(a,b,complex_layout=complex_layout,reliable_text=reliable)==expected


def test_visual_score_penalizes_missing_ink_and_wrong_position():
    im,r=sample('Sample text')
    good=c.visual_score(im,r['bbox'],[r])
    wrong=c.visual_score(im,r['bbox'],[dict(r,x=r['x']+12)])
    missing=c.visual_score(im,r['bbox'],[dict(r,text='Sample')])
    assert good>.95 and wrong<good-.15 and missing<good-.15


def test_text_and_formula_are_scored_on_identical_canvas(monkeypatch):
    im,r=sample('Sample')
    monkeypatch.setattr(c,'formula_layout',lambda latex,size,stroke:outline_layout(r['font_id'],'Sample',size,0,stroke))
    assert c.visual_score(im,r['bbox'],[r])==c.visual_score(im,r['bbox'],[dict(r,kind='formula',latex='Sample')])


def test_confident_prose_ignores_spurious_formula_proposal(monkeypatch):
    im,r=sample('LC-MS analysis')
    def unexpected(*a,**k):raise AssertionError('Reliable prose should not call either recognizer')
    result=c.resolve_types(im,[r],[dict(bbox=r['bbox'],confidence=.99)],engine=unexpected,detect=unexpected,recognize=unexpected,fit_math=unexpected)
    assert result==[r]


def test_disputed_region_recovers_text_without_losing_original(monkeypatch):
    im,r=sample();before=deepcopy(r)
    monkeypatch.setattr(c,'local_retry',lambda *args,**kwargs:([dict(text=r['text'],confidence=.99,bbox=r['bbox'])],[]))
    def unavailable(*args):raise ValueError('optional runtime absent')
    result=c.resolve_types(im,[r],[],engine=None,detect=None,recognize=unavailable,fit_math=None)
    assert r==before
    assert len(result)==1 and result[0]['kind']=='text' and result[0]['enabled']
    assert result[0]['text']==r['text'] and result[0]['type_decision']['text_score']>.78


def test_close_candidates_preserve_source_and_queue_review(monkeypatch):
    im,r=sample()
    monkeypatch.setattr(c,'local_retry',lambda *args,**kwargs:([],[]))
    monkeypatch.setattr(c,'visual_score',lambda *args:.85)
    result=c.resolve_types(im,[r],[],engine=None,detect=None,recognize=lambda *args:'p<0.05',fit_math=lambda im,r:dict(r,font_size=36))
    assert len(result)==1 and not result[0]['enabled'] and result[0]['preserve_original']
    assert result[0]['type_decision']['choice']=='uncertain' and result[0]['type_review']
    assert result[0]['original_text']==r['text']


def test_cancellation_is_not_swallowed(monkeypatch):
    im,r=sample()
    def cancelled(*args):raise InterruptedError('stop')
    with pytest.raises(InterruptedError):
        c.resolve_types(im,[r],[],engine=None,detect=None,recognize=None,fit_math=None,progress=cancelled)


@pytest.mark.parametrize('single_line',[True,False])
def test_recognition_only_fallback_is_limited_to_known_single_line(single_line):
    calls=[]
    def engine(crop,**kwargs):
        calls.append(kwargs['use_det'])
        return SimpleNamespace(boxes=None,txts=['x + y'] if not kwargs['use_det'] else None,scores=[.99])
    box=[30,20,100,25]
    lines,_=c.local_retry(np.full((100,200,3),255,np.uint8),box,engine,lambda _:[],single_line=single_line)
    assert calls==([True,False] if single_line else [True])
    assert lines==([dict(text='x + y',confidence=.99,bbox=box)] if single_line else [])


@pytest.mark.parametrize('neighbor',[False,True])
def test_local_formula_bounds_expand_without_swallowing_neighbor(monkeypatch,neighbor):
    im,r=sample()
    x,y,w,h=r['bbox'];expanded=[x,y,w+8,h]
    extra=dict(r,id='neighbor',text='正文',bbox=[x+w+1,y,6,h],ocr_bbox=[x+w+1,y,6,h])
    monkeypatch.setattr(c,'structure',lambda *args:dict(fraction=False,scripts=False))
    monkeypatch.setattr(c,'local_retry',lambda *args,**kwargs:([],[dict(bbox=expanded,confidence=.99)]))
    monkeypatch.setattr(c,'visual_score',lambda *args:.85)
    result=c.resolve_types(im,[r,extra] if neighbor else [r],[],engine=None,detect=None,
                           recognize=lambda *args:'p<0.05',fit_math=lambda im,r:r)
    formula=next(item for item in result if item['kind']=='formula')
    assert formula['bbox']==(r['bbox'] if neighbor else expanded)


def test_formula_without_any_page_ocr_still_gets_candidate_and_review(monkeypatch):
    im,r=sample()
    monkeypatch.setattr(c,'local_retry',lambda *args,**kwargs:([],[]))
    monkeypatch.setattr(c,'visual_score',lambda *args:.9)
    result=c.resolve_types(im,[],[dict(bbox=r['bbox'],confidence=.99)],engine=None,detect=None,
                           recognize=lambda *args:'p<0.05',fit_math=lambda im,r:r)
    assert len(result)==1 and result[0]['type_decision']['choice']=='formula'
    assert result[0]['latex']=='p<0.05' and result[0]['preserve_original']
    assert result[0]['type_review']=='公式结构需核对'
