"""Local formula detection, isolated recognition and two-dimensional SVG layout.

Models are optional assets installed explicitly by scripts/install-formulas.py.
No network requests occur while opening, previewing or processing a project.
"""
from __future__ import annotations
import io
import json
import os
import subprocess
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import resvg_py
from lxml import etree
from PIL import Image

from .fidelity import crop_evidence, _match
from .typography import svg_document


def formula_root():
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'ai-text-sharpener/formula'


def formula_available():
    return (formula_root() / 'mfd.onnx').is_file()


@lru_cache(maxsize=1)
def detector():
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(formula_root()/'mfd.onnx'), options, providers=['CPUExecutionProvider'])


def detect_formulas(image):
    """MFD 1.5 YOLO ONNX: RGB letterbox, cx/cy/w/h + 2 class probabilities."""
    if not formula_available():
        return []
    h, w = image.shape[:2]
    scale = min(768/w, 768/h)
    nw, nh = round(w*scale), round(h*scale)
    px, py = (768-nw)//2, (768-nh)//2
    canvas = np.full((768,768,3), 114, np.uint8)
    canvas[py:py+nh,px:px+nw] = cv2.resize(image,(nw,nh))
    session = detector()
    output = session.run(None, {session.get_inputs()[0].name:canvas.transpose(2,0,1)[None].astype(np.float32)/255})[0][0].T
    if output.shape[1] != 6:
        raise ValueError('公式检测模型格式不兼容。')
    scores = output[:,4:].max(axis=1)
    keep = scores >= .35
    pred, scores = output[keep].copy(), scores[keep]
    pred[:,:2] -= pred[:,2:4]/2
    indices = cv2.dnn.NMSBoxes(pred[:,:4].tolist(), scores.tolist(), .35, .4)
    boxes = []
    for i in np.asarray(indices).reshape(-1):
        x, y, bw, bh = pred[i,:4]
        x0, y0 = max(0, int((x-px)/scale)-5), max(0, int((y-py)/scale)-5)
        x1, y1 = min(w, int(np.ceil((x+bw-px)/scale))+5), min(h, int(np.ceil((y+bh-py)/scale))+5)
        if x1-x0 < 3 or y1-y0 < 3:
            continue
        boxes.append({'bbox':[x0,y0,x1-x0,y1-y0], 'confidence':round(float(scores[i]),4)})
    return sorted(boxes, key=lambda b:(b['bbox'][1]//30,b['bbox'][0]))


def overlaps(box, other):
    x,y,w,h=box; a,b,c,d=other
    area=max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b))
    return area > .5 * min(w*h,c*d)


def combine_formula_regions(regions, detections):
    """Replace OCR fragments with a single preserved region per detected formula."""
    expanded = []
    for f in detections:
        box = f['bbox']
        members = [r.get('ocr_bbox', r['bbox']) for r in regions
                   if overlaps(r.get('ocr_bbox', r['bbox']), box)]
        # A detector may clip a leading symbol. Include intersecting OCR lines
        # only when they do not span a second detected formula.
        members = [b for b in members if sum(overlaps(b, d['bbox']) for d in detections) == 1]
        boxes = [box] + members
        x,y=min(b[0] for b in boxes),min(b[1] for b in boxes)
        right,bottom=max(b[0]+b[2] for b in boxes),max(b[1]+b[3] for b in boxes)
        expanded.append(dict(f,bbox=[x,y,right-x,bottom-y]))
    detections = expanded
    result = [r for r in regions if not any(overlaps(r.get('ocr_bbox',r['bbox']), f['bbox']) for f in detections)]
    for f in detections:
        x,y,w,h=f['bbox']
        result.append({'id':uuid.uuid4().hex[:12], 'kind':'formula', 'text':'', 'original_text':'',
                       'latex':'', 'bbox':f['bbox'], 'x':x, 'y':y, 'font_id':'',
                       'font_size':48, 'letter_spacing':0, 'stroke_width':0, 'color':'#182029',
                       'enabled':False,'locked':False,'confidence':f['confidence'],'score':None,
                       'erase_mode':'gradient','fit_status':'preserved',
                       'fit_note':'已检测为完整公式并保留原图。点击「识别公式」，核对 LaTeX 后可启用重绘。'})
    return sorted(result,key=lambda r:(r['bbox'][1]//30,r['bbox'][0]))


def runtime_config():
    try:
        return json.loads((formula_root()/'runtime.json').read_text())
    except (OSError, ValueError) as exc:
        raise ValueError('公式组件未安装，请运行 scripts/install-formulas.py。') from exc


@lru_cache(maxsize=128)
def formula_base(latex):
    if not isinstance(latex,str) or not latex.strip() or len(latex)>2048:
        raise ValueError('请输入不超过 2048 字符的 LaTeX 公式。')
    conf=runtime_config()
    try:
        result=subprocess.run([conf['node'], str(Path(__file__).with_name('mathjax-render.cjs')),
                               str(formula_root()/'mathjax/package')],
                              input=json.dumps({'latex':latex}), text=True, capture_output=True, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('公式排版失败或超时，请检查公式组件和 LaTeX。') from exc
    if result.returncode:
        raise ValueError('公式排版失败：'+result.stderr[-300:])
    root=etree.fromstring(result.stdout.encode())
    if root.xpath('.//*[local-name()="text" or local-name()="image" or local-name()="script" or local-name()="foreignObject"]'):
        raise ValueError('公式包含无法矢量化的内容。')
    vx,vy,vw,vh=map(float,root.attrib['viewBox'].split())
    # One TeX em is 1000 units; rasterize once to find actual ink bounds.
    factor=64/1000
    width,height=vw*factor,vh*factor
    if width*height>8_000_000 or max(width,height)>16000:
        raise ValueError('公式尺寸过大，请拆分公式。')
    inner=''.join(etree.tostring(c,encoding='unicode') for c in root)
    body=f'<g transform="scale({factor}) translate({-vx} {-vy})">{inner}</g>'
    svg=svg_document(width,height,body)
    image=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGBA'))
    points=cv2.findNonZero(image[:,:,3])
    if points is None:raise ValueError('公式没有可绘制的内容。')
    x,y,w,h=cv2.boundingRect(points)
    return {'width':w,'height':h,'body':f'<g transform="translate({-x} {-y})">{body}</g>'}


def formula_layout(latex, size, stroke_width=0):
    base=formula_base(latex)
    scale=size/64
    # Stroke is in output pixels; translate to keep the ink origin consistent.
    inner = base["body"].replace('stroke-width="0"', "")
    body=f'<g transform="translate({stroke_width/2} {stroke_width/2}) scale({scale})" stroke="currentColor" stroke-width="{stroke_width*1000/size}" stroke-linejoin="round">{inner}</g>'
    return {'width':base['width']*scale+stroke_width, 'height':base['height']*scale+stroke_width,'body':body}


def recognize_formula(image, region):
    ev=crop_evidence(image,region['bbox'])
    # Normalize colored/dark-slide ink without changing its two-dimensional layout.
    mask=np.pad(ev['mask'],12)
    normalized=np.uint8(np.clip((1-mask)*255,0,255))
    conf=runtime_config()
    with tempfile.TemporaryDirectory(prefix='sharpener-formula-') as td:
        path=Path(td)/'formula.png';Image.fromarray(normalized).save(path)
        try:
            run=subprocess.run([conf['python'],str(Path(__file__).with_name('formula_worker.py')),str(formula_root()),str(path)],capture_output=True,text=True,timeout=90)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ValueError('本地公式识别失败或超时，原图已保留。') from exc
    if run.returncode:raise ValueError('本地公式识别失败：'+run.stderr[-300:])
    result=json.loads(run.stdout.strip().splitlines()[-1])
    return result['latex']


def fit_formula(image, region):
    result=dict(region)
    ev=crop_evidence(image,region['bbox'])
    ix,iy,iw,ih=ev['ink_box']
    base=formula_base(region.get('latex',''))
    max_size=min(iw/base['width'],ih/base['height'])*64
    scale=min(1,100/ih,1000/iw)
    pad=max(5,round(ih*.1))
    target=cv2.resize(np.pad(ev['mask'],pad),None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    candidates=[]
    for factor in (.9,.95,1,1.025,1.05):
        size=min(1000,max(4,max_size*factor))
        layout=formula_layout(region['latex'],size*scale,region.get('stroke_width',0)*scale)
        svg=svg_document(layout['width']+1,layout['height']+1,layout['body'])
        rgba=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGBA'))
        score,(dx,dy)=_match(target,rgba[:,:,3].astype(np.float32)/255)
        candidates.append({'font_size':round(size,3),'score':round(score,4),'x':round(ev['x']-pad+dx/scale,2),'y':round(ev['y']-pad+dy/scale,2)})
    result.update(max(candidates,key=lambda c:c['score']))
    result.update(color='#'+''.join(f'{v:02x}' for v in ev['color']),fit_status='formula_review',
                  fit_note='公式已按二维结构排版；相似度不保证符号正确。请核对 LaTeX，勾选「重绘此区域」查看对比。')
    return result
