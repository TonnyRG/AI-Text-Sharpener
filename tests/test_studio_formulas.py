"""Formula structure and preservation regressions; optional runtime tests skip offline."""
import io
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from lxml import etree
from ai_text_sharpener.fidelity import automatic_fit_failure, fit_region
from ai_text_sharpener.formula import combine_formula_regions, formula_layout, runtime_config
from ai_text_sharpener.studio_project import StudioStore, compose_page, render_page, validate_regions
from ai_text_sharpener.typography import candidate_fonts, render_mask


def text_sample():
    ids=candidate_fonts('Sample',1)
    if not ids:pytest.skip('fontconfig fonts required')
    mask,layout=render_mask(ids[0],'Sample',40,0)
    image=np.full((160,500,3),245,np.uint8)
    h,w=mask.shape;image[50:50+h,50:50+w]=(245-220*mask[:,:,None]).astype(np.uint8)
    r=dict(id='t',text='Sample',bbox=[45,45,w+10,h+10],x=50,y=50,font_id=ids[0],font_size=40,
           color='#191919',enabled=True,letter_spacing=0,erase_mode='gradient',fit_status='review',score=0)
    return image,r


def project_for(tmp_path,image,regions):
    store=StudioStore(tmp_path);p=store.create('test');store.add_images(p,[('test',Image.fromarray(image))]);page=p['pages'][0];page['regions']=regions
    return store.directory(p['id']),page


def test_oversize_and_zero_score_automatic_fits_are_rejected():
    _,r=text_sample()
    assert automatic_fit_failure(r,{'width':100,'height':40})
    r['score']=.85
    assert automatic_fit_failure(r,{'width':800,'height':40})
    r['fit_status']='edited'
    assert automatic_fit_failure(r,{'width':800,'height':40}) is None


def test_actual_fit_with_no_matching_template_preserves_source(monkeypatch):
    import ai_text_sharpener.fidelity as f
    im,r=text_sample();monkeypatch.setattr(f,'_match',lambda *a:(0.,(0,0)))
    result=fit_region(im,r,[r['font_id']])
    assert result['enabled'] is False and result['fit_status']=='preserved'


def test_old_zero_score_project_exports_unchanged_pixels(tmp_path):
    im,r=text_sample();directory,page=project_for(tmp_path,im,[r]);_,png=render_page(directory,page)
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')),im)


def test_formula_owns_full_ocr_line_and_retains_nearby_caption():
    a=dict(id='a',bbox=[10,30,280,50]);b=dict(id='b',bbox=[10,3,100,15])
    result=combine_formula_regions([a,b],[{'bbox':[40,25,250,70],'confidence':.8}])
    assert len(result)==2 and result[0]['id']=='b'
    f=result[1];assert f['kind']=='formula' and not f['enabled'] and f['bbox']==[10,25,280,70]


def test_disabled_formula_survives_other_text_moved_over_it(tmp_path):
    im,r=text_sample();r.update(score=None,fit_status='edited',bbox=[300,80,100,50],x=50,y=50)
    f=combine_formula_regions([], [{'bbox':[40,40,190,60],'confidence':.9}])[0]
    directory,page=project_for(tmp_path,im,[r,f]);_,png=render_page(directory,page)
    out=np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))
    assert np.array_equal(out[40:100,40:230],im[40:100,40:230])


def test_formula_validation_does_not_require_text_font():
    f=combine_formula_regions([], [{'bbox':[20,20,100,60],'confidence':.9}])[0]
    f.update(enabled=True,latex='x^2')
    validate_regions([f],500,160)
    f['latex']=None
    with pytest.raises(ValueError):validate_regions([f],500,160)


@pytest.fixture
def math_runtime():
    try:
        config=runtime_config()
        if not Path(config['node']).is_file():pytest.skip('optional Node runtime not installed')
        formula_layout('x^2',32)
    except ValueError:pytest.skip('optional MathJax runtime not installed')


@pytest.mark.parametrize('latex',[r'x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}',r'\begin{bmatrix}a_{11}&a_{12}\\a_{21}&a_{22}\end{bmatrix}',r'f(x)=\begin{cases}x^2&x\geq0\\-x&x<0\end{cases}'])
def test_multidimensional_formula_exports_paths(math_runtime,tmp_path,latex):
    image=np.full((300,700,3),255,np.uint8)
    f=combine_formula_regions([], [{'bbox':[10,10,500,200],'confidence':.9}])[0]
    f.update(enabled=True,latex=latex,font_size=48,x=20,y=20)
    directory,page=project_for(tmp_path,image,[f]);svg,png=render_page(directory,page)
    root=etree.fromstring(svg.encode())
    assert len(root.xpath('.//*[local-name()="path"]'))>5
    assert not root.xpath('.//*[local-name()="text"]')
    assert f['ink_width']>60 and f['ink_height']>40
    assert np.asarray(Image.open(io.BytesIO(png))).min()<100
    assert compose_page(directory,deepcopy(page))==svg


def test_bad_latex_leaves_previous_export_intact(math_runtime,tmp_path):
    im,r=text_sample();f=combine_formula_regions([], [{'bbox':[40,40,190,60],'confidence':.9}])[0]
    d,p=project_for(tmp_path,im,[f]);_,png=render_page(d,p)
    f.update(enabled=True,latex=r'\notACommand{x}')
    with pytest.raises(ValueError):render_page(d,p)
    assert (d/f"{p['id']}-result.png").read_bytes()==png


def test_formula_stroke_changes_actual_rendering(math_runtime):
    import resvg_py
    from ai_text_sharpener.typography import svg_document
    masks=[]
    for stroke in [0,1.5]:
        layout=formula_layout('E=mc^2',48,stroke)
        png=resvg_py.svg_to_bytes(svg_string=svg_document(400,100,layout['body']))
        masks.append(np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))[:,:,3].sum())
    assert masks[1]>masks[0]*1.15


def test_detector_padding_does_not_absorb_caption_above_formula():
    caption=dict(id='caption',text='嵌套分式',bbox=[1003,545,164,50])
    part=dict(id='part',text='1',bbox=[1343,593,53,77])
    formula={'bbox':[1063,583,489,274],'confidence':.9}
    result=combine_formula_regions([caption,part],[formula])
    assert result[0]['id']=='caption'
    assert result[1]['bbox']==formula['bbox']
