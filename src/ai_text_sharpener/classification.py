"""Conservative text/formula routing using local OCR and shared image evidence.

Detector and OCR confidence values are independent hints, not interchangeable
probabilities. Only disputed crops incur a second OCR pass and two renderings.
"""
from copy import deepcopy
import io
import math
import re

import cv2
import numpy as np
import resvg_py
from PIL import Image

from .fidelity import crop_evidence, fit_region
from .formula import combine_formula_regions, overlaps, formula_layout
from .geometry import source_frame
from .typography import outline_layout, svg_document


def numeric_label(text):
    """Flat numeric labels, excluding operators and two-dimensional notation."""
    # Normalize only typography; do not turn superscript digits into digits.
    text = text.translate(str.maketrans('０１２３４５６７８９，．％＋－', '0123456789,.%+-')).strip()
    number = r'(?:\d{1,3}(?:[,\u2009\u202f ]\d{3})+|\d+)(?:\.\d+)?|\.\d+'
    return bool(re.fullmatch(r'[+−-]?\s*[$€£¥￥]?\s*(?:' + number + r')\s*(?:[%‰‱]|[$€£¥￥])?', text))


def lexical_kind(text):
    """Classify layout needs, not whether the subject matter is mathematical."""
    text = text.strip()
    if not text:
        return 'unknown'
    if numeric_label(text):
        return 'text'
    if re.search(r'[=+∑∫√≈≤≥±∂∞^_<>]|[²³⁰¹⁴⁵⁶⁷⁸⁹₀-₉]', text):
        return 'math'
    # Common labels, units, ranges and acronyms remain ordinary single-line text.
    if re.fullmatch(r'[\w\s.,，。:：;；%％/–—−\-()（）·µμ°]+', text, re.UNICODE):
        if any(c.isalpha() for c in text) or re.search(r'\d\s*[%％]', text):
            return 'text'
    return 'unknown'


def _punctuation_parts(labels, parts, text):
    """Identify comma tails and percent rings before looking for script glyphs.

    OCR punctuation alone is insufficient: a percent must have two rings and a
    rising slash in the source, and a comma must sit just below the main baseline.
    Fractions are checked separately against the complete, unfiltered image.
    """
    ignored = set()
    if '%' in text or '％' in text:
        holes = {}
        for label, (x, y, w, h, _) in parts:
            mask = np.uint8(labels[y:y+h, x:x+w] == label)
            _, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            holes[label] = hierarchy is not None and np.any(hierarchy[0, :, 3] >= 0)
            # At small sizes antialias thresholding can open a ring by one row.
            center = mask[h//4:max(h//4+1,3*h//4), w//3:max(w//3+1,2*w//3)]
            sides = mask[h//4:max(h//4+1,3*h//4)]
            if w >= 4 and h >= 5 and center.mean() < .35:
                holes[label] |= bool(sides[:, :max(1,w//3)].any(axis=1).mean() > .7
                                     and sides[:, max(1,2*w//3):].any(axis=1).mean() > .7)
        remaining = text.count('%') + text.count('％')
        for slash, (x, y, w, h, area) in parts:
            if not remaining or slash in ignored or holes[slash] or not (.15*h <= w <= .9*h and area < .45*w*h):
                continue
            sy, sx = np.nonzero(labels[y:y+h, x:x+w] == slash)
            if len(sx) < 4 or np.std(sx) < 1 or np.std(sy) < 1 or np.corrcoef(sx, sy)[0, 1] > -.7:
                continue
            upper, lower = [], []
            for ring, (rx, ry, rw, rh, _) in parts:
                if ring in ignored or not holes[ring] or not (.28*h <= rh <= .65*h and .5*rh <= rw <= 1.6*rh):
                    continue
                cx, cy = rx+rw/2, ry+rh/2
                if x-.4*h <= cx < x+w/2 and abs(ry-y) <= .2*h and cy < y+h*.5:
                    upper.append(ring)
                if x+w/2 < cx <= x+w+.4*h and abs(ry+rh-y-h) <= .2*h and cy > y+h*.5:
                    lower.append(ring)
            if len(upper) == len(lower) == 1:
                # Keep the full-height slash as an anchor for a genuine script
                # immediately after the percent sign.
                ignored.update((upper[0], lower[0]))
                remaining -= 1
    commas = text.count(',') + text.count('，')
    if commas:
        body = [s for label, s in parts if label not in ignored]
        if body:
            height = float(np.percentile([s[3] for s in body], 75))
            baseline = float(np.median([s[1]+s[3] for s in body if s[3] >= height*.8]))
            tails = [label for label, (x, y, w, h, area) in parts if label not in ignored
                     and .15*height <= h <= .52*height and w <= .32*height
                     and y >= baseline-.3*height and baseline+.05*height <= y+h <= baseline+.3*height]
            # More candidates than OCR commas means the glyph mapping is unclear.
            if len(tails) <= commas:
                ignored.update(tails)
    return ignored


def structure(image, region):
    """Look for fractions and side-by-side glyphs on different baselines."""
    try:
        frame, box, _ = source_frame(image, region)
        ev = crop_evidence(frame, box)
    except ValueError:
        return {'fraction': False, 'scripts': False}
    binary = ev['binary']
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    indexed = [(label, s) for label, s in enumerate(stats[1:], 1) if s[4] >= 4]
    parts = [s for _, s in indexed]
    fraction = False
    for x, y, w, h, area in parts:
        if w < 12 or w < 4*h or h > binary.shape[0]*.12:
            continue
        # A rule/underline has no numerator AND denominator within its span.
        above = binary[:max(0,y-2), x:x+w]
        below = binary[y+h+2:, x:x+w]
        if np.count_nonzero(above) > w*.3 and np.count_nonzero(below) > w*.3:
            fraction = True
    scripts = False
    # Connected components of Chinese glyphs do not correspond to letters.
    if not re.search(r'[\u3400-\u9fff]', region.get('text', '')):
        ignored = _punctuation_parts(labels, indexed, region.get('text', ''))
        parts = [s for label, s in indexed if label not in ignored]
        for x, y, w, h, area in parts:
            for bx, by, bw, bh, ba in parts:
                gap = max(x-bx-bw, bx-x-w)
                if (.3*bh <= h <= .7*bh and area >= 6 and 0 <= gap <= bh*.6
                        and (y+h < by+bh*.6 or y > by+bh*.75)):
                    scripts = True
    return {'fraction': bool(fraction), 'scripts': bool(scripts)}


def _covers(region, box):
    x,y,w,h = region.get('ocr_bbox',region['bbox']);a,b,c,d = box
    area = max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b))
    return area >= .65*c*d


def _safe_text_proposal(image, region, box):
    if region.get('confidence', 0) < .92 or lexical_kind(region.get('text', '')) != 'text':
        return False
    if any(structure(image, region).values()):
        return False
    # OCR may omit a small exponent or denominator outside its own box. Check
    # the detector's full extent before dismissing it as a numeric/text label.
    x, y, w, h = region['bbox']; a, b, c, d = box
    extent = [min(x,a), min(y,b), max(x+w,a+c)-min(x,a), max(y+h,b+d)-min(y,b)]
    return not any(structure(image, dict(text=region.get('text', ''), bbox=extent)).values())


def local_retry(image, box, engine, detect, *, single_line=False):
    """Re-read an enlarged original crop; return page coordinates, never crop ones."""
    x,y,w,h = box
    margin = max(8,min(32,round(h*.2)))
    x0,y0 = max(0,math.floor(x)-margin),max(0,math.floor(y)-margin)
    x1,y1 = min(image.shape[1],math.ceil(x+w)+margin),min(image.shape[0],math.ceil(y+h)+margin)
    patch = image[y0:y1,x0:x1]
    if not patch.size:
        return [], []
    scale = min(2.,1600/max(patch.shape[:2]))
    enlarged = cv2.resize(patch,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    # Use actual ratios: rounded resize dimensions are not exactly scale.
    sx,sy = enlarged.shape[1]/patch.shape[1],enlarged.shape[0]/patch.shape[0]
    result = engine(cv2.cvtColor(enlarged,cv2.COLOR_RGB2BGR),use_det=True,use_cls=True,use_rec=True)
    lines = []
    if getattr(result,'boxes',None) is not None:
        for points,text,confidence in zip(result.boxes,result.txts,result.scores):
            points=np.asarray(points,dtype=float)/[sx,sy]+[x0,y0]
            low,high=points.min(axis=0),points.max(axis=0)
            bbox=[*low,*(high-low)]
            if text.strip() and overlaps(bbox,box):
                lines.append({'text':text.strip(),'confidence':float(confidence),'bbox':list(map(float,bbox))})
    if not lines and single_line:
        # A detector can reject an already-tight line crop. Recognition-only
        # retries are allowed only for a known single line, never a fraction.
        a,b=max(0,math.floor(x)),max(0,math.floor(y))
        raw=image[b:min(image.shape[0],math.ceil(y+h)),a:min(image.shape[1],math.ceil(x+w))]
        retry=cv2.resize(raw,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
        direct=engine(cv2.cvtColor(retry,cv2.COLOR_RGB2BGR),use_det=False,use_cls=True,use_rec=True)
        texts=getattr(direct,'txts',None)
        scores=getattr(direct,'scores',None)
        if texts and scores is not None and len(texts)==1 and texts[0].strip():
            lines.append({'text':texts[0].strip(),'confidence':float(scores[0]),'bbox':list(box)})
    detections=[]
    for item in detect(enlarged):
        a,b,c,d=item['bbox'];bbox=[x0+a/sx,y0+b/sy,c/sx,d/sy]
        if overlaps(bbox,box):
            detections.append(dict(item,bbox=bbox))
    return lines,detections


def visual_score(image, box, regions):
    """Compare both paths on the SAME crop/scale and without realigning results."""
    ev = crop_evidence(image,box)
    height,width=ev['mask'].shape
    pieces=[]
    for r in regions:
        if r.get('kind')=='formula':
            layout=formula_layout(r['latex'],r['font_size'],r.get('stroke_width',0))
        else:
            layout=outline_layout(r['font_id'],r['text'],r['font_size'],r.get('letter_spacing',0),r.get('stroke_width',0))
        angle=r.get('rotation',0)
        pieces.append(f'<g transform="translate({r["x"]-ev["x"]} {r["y"]-ev["y"]}) rotate({angle} {layout["width"]/2} {layout["height"]/2})">{layout["body"]}</g>')
    svg=svg_document(width,height,'<g fill="white" color="white">'+''.join(pieces)+'</g>')
    candidate=np.asarray(Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert('RGBA'))[:,:,3].astype(np.float32)/255
    target=ev['mask']
    scale=min(1.,1000/width,240/height)
    if scale<1:
        target=cv2.resize(target,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
        candidate=cv2.resize(candidate,(target.shape[1],target.shape[0]),interpolation=cv2.INTER_AREA)
    t=cv2.GaussianBlur(target,(0,0),.65);c=cv2.GaussianBlur(candidate,(0,0),.65)
    score=2*float((t*c).sum())/max(1e-6,float((t*t).sum()+(c*c).sum()))
    ink_error=abs(math.log(max(1e-6,float(candidate.sum()))/max(1e-6,float(target.sum()))))
    return round(max(0.,score-.18*min(1.,ink_error)),4)


def choose_type(text_score, formula_score, *, complex_layout=False, reliable_text=False):
    """An absolute floor and a margin prevent choosing the lesser of two bad fits."""
    if (reliable_text and not complex_layout and text_score is not None and text_score>=.75
            and (formula_score is None or text_score>=formula_score+.06)):
        return 'text'
    if formula_score is not None and formula_score>=.72 and (text_score is None or formula_score>=text_score+.06):
        return 'formula'
    return 'uncertain'


def resolve_types(image, regions, detections, *, engine, detect, recognize, fit_math, progress=None):
    """Keep reliable prose; compare disputed regions and preserve close decisions."""
    # Start with all detector proposals. Restore raw OCR lines only after a
    # layout-aware decision, rather than unconditionally trusting mixed prose.
    proposals=[]
    for detection in detections:
        members=[r for r in regions if _covers(r,detection['bbox'])]
        safe=any(_safe_text_proposal(image, r, detection['bbox']) for r in members)
        if not safe:
            proposals.append(detection)
    # OCR can expose small expressions missed by the whole-slide detector.
    for r in regions:
        text=r.get('text','')
        suspect=lexical_kind(text)=='math'
        if not suspect and not re.search(r'[\u3400-\u9fff]',text) and (r.get('confidence',0)<.92 or len(text)<24):
            suspect=any(structure(image,r).values())
        if suspect and not any(overlaps(r['bbox'],d['bbox']) for d in proposals):
            proposals.append({'bbox':r['bbox'][:],'confidence':0.,'origin':'ocr'})
    # Bypass combine_formula_regions' legacy prose shortcut here: it has no
    # image evidence and cannot distinguish a real superscript from a flat line.
    combined=combine_formula_regions(regions,proposals,protect_prose=False)
    output=[r for r in combined if r.get('kind')!='formula']
    disputed=[r for r in combined if r.get('kind')=='formula']
    for index,region in enumerate(disputed):
        if progress:progress(f'复核文字／公式 {index+1}/{len(disputed)}')
        members=[deepcopy(r) for r in regions if overlaps(r.get('ocr_bbox',r['bbox']),region['bbox'])]
        # A line spanning multiple candidates belongs to neither comparison.
        members=[r for r in members if sum(overlaps(r['bbox'],f['bbox']) for f in disputed)==1]
        notes=[]
        try:
            evidence=structure(image,dict(region,text=region.get('original_text','')))
            local_lines,local_formulas=local_retry(image,region['bbox'],engine,detect,
                single_line=len(members)==1 and not any(evidence.values()))
        except (ValueError,RuntimeError):
            local_lines,local_formulas=[],[];notes.append('局部复查失败')
        # Local detections can recover a clipped superscript/fraction boundary.
        # Expand only a little, and never absorb a neighboring OCR line.
        for detection in local_formulas:
            a,b,c,d=detection['bbox'];x,y,w,h=region['bbox']
            candidate=[min(x,a),min(y,b),max(x+w,a+c)-min(x,a),max(y+h,b+d)-min(y,b)]
            outsiders=[r for r in regions if r['id'] not in {m['id'] for m in members}]
            if (detection.get('confidence',0)>=.75 and candidate[2]*candidate[3]<=w*h*1.5
                    and not any(overlaps(candidate,r['bbox']) for r in outsiders)):
                region['bbox']=candidate
        # Keep page OCR as an alternative: a second pass is not automatically
        # more correct. Do not concatenate multiple rows into ordinary text.
        variants=[members] if members else []
        if local_lines:
            local_members=[]
            for i,line in enumerate(local_lines):
                x,y,w,h=line['bbox']
                base=dict(id=f'{region["id"]}-text-{i}',kind='text',original_text=line['text'],
                          x=x,y=y,font_id='',font_size=max(4,round(h)),letter_spacing=0,
                          enabled=True,locked=False,color='#182029',erase_mode='gradient',**line)
                local_members.append(base)
            variants.append(local_members)
        text_fit=None;text_score=None
        for variant in variants:
            if not variant or any(r.get('confidence',0)<.8 for r in variant):continue
            try:
                fitted=[fit_region(image,dict(r,kind='text',enabled=True)) for r in variant]
                if not all(r.get('enabled') for r in fitted):continue
                score=visual_score(image,region['bbox'],fitted)
                if text_score is None or score>text_score:text_fit,text_score=fitted,score
            except ValueError:
                continue
        math_fit=None;math_score=None
        try:
            math_fit=fit_math(image,dict(region,latex=recognize(image,region)))
            math_score=visual_score(image,region['bbox'],[math_fit])
        except ValueError:
            notes.append('公式候选不可用')
        evidence=structure(image,dict(region,text=region.get('original_text','')))
        reliable=bool(text_fit) and all(r.get('confidence',0)>=.92 for r in text_fit)
        decision=choose_type(text_score,math_score,complex_layout=any(evidence.values()),reliable_text=reliable)
        details={'choice':decision,'text_score':text_score,'formula_score':math_score,
                 'local_ocr_lines':len(local_lines),'local_formula_detections':len(local_formulas),
                 'structure':evidence,'notes':notes}
        if decision=='text':
            for r in text_fit:
                r['type_decision']=details
                output.append(r)
        else:
            if math_fit:region.update(math_fit)
            region.update(type_decision=details,enabled=False,fit_status='preserved',preserve_original=True,
                          type_review='文字／公式待确认' if decision=='uncertain' else '公式结构需核对')
            region['fit_note']=region['type_review']
            output.append(region)
    return sorted(output,key=lambda r:(r['bbox'][1]//30,r['bbox'][0]))
