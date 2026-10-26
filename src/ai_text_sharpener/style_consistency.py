"""Conservative, pixel-checked size consensus for freshly scanned text peers.

Exact font faces remain separate, including different weights of one family.
Only a local majority can propose a size; the original image decides whether
the small correction is acceptable. Source erase bounds are never changed.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from .classification import visual_score
from .fidelity import crop_evidence, fit_region_at_size
from .geometry import rotated_bounds, round_style
from .typography import outline_layout


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax+aw, bx+bw)-max(ax, bx))*max(0, min(ay+ah, by+bh)-max(ay, by))


def _peer_groups(items):
    """Local source-ink rows/columns, with complete-span rather than chain grouping."""
    seen = set()
    for axis in (0, 1):
        cross = 1-axis
        for factor in (0, .5, 1):
            anchor = lambda item: item['source'][axis]+factor*item['source'][axis+2]
            clusters = []
            for item in sorted(items, key=anchor):
                if not clusters or anchor(item)-anchor(clusters[-1][0]) > 2:
                    clusters.append([])
                clusters[-1].append(item)
            for cluster in clusters:
                nearby = []
                chunks = []
                for item in sorted(cluster, key=lambda i: i['source'][cross]):
                    if nearby:
                        previous = nearby[-1]
                        gap = item['source'][cross]-previous['source'][cross]-previous['source'][cross+2]
                        if gap < 0 or gap > min(item['source'][3], previous['source'][3])*(3 if axis == 0 else 6):
                            chunks.append(nearby)
                            nearby = []
                    nearby.append(item)
                chunks.append(nearby)
                for group in chunks:
                    key = tuple(sorted(i['region']['id'] for i in group))
                    if len(group) >= 3 and key not in seen:
                        seen.add(key)
                        yield group


def normalize_page(image, regions):
    """Apply safe local size consensus in place and return the changed region count."""
    families = defaultdict(list)
    boxes = {}
    height, width = image.shape[:2]
    for r in regions:
        try:
            layout = (outline_layout(r['font_id'], r['text'], r['font_size'],
                                     r.get('letter_spacing', 0), r.get('stroke_width', 0))
                      if r.get('enabled') and r.get('kind') != 'formula' else None)
            boxes[r['id']] = (rotated_bounds(r['x'], r['y'], layout['width'], layout['height'], r.get('rotation', 0))
                              if layout else tuple(r['bbox']))
        except (KeyError, ValueError):
            if r.get('bbox'):
                boxes[r['id']] = tuple(r['bbox'])
            continue
        if (not layout or r.get('locked') or r.get('preserve_original') or r.get('kind') == 'formula'
                or r.get('fit_status') != 'fitted' or (r.get('confidence') or 0) < .92
                or (r.get('score') or 0) < .65 or r.get('type_review')
                or abs(r.get('rotation', 0)) > .01 or abs(r.get('source_rotation', 0)) > .01
                or len(r.get('text', '').strip()) < 2 or r['font_size'] != round_style(r['font_size'])):
            continue
        x, y, w, h = r['bbox']
        if x < 0 or y < 0 or x+w > width or y+h > height:
            continue
        try:
            ev = crop_evidence(image, r['bbox'], single_line=True)
            ix, iy, iw, ih = ev['ink_box']
            if (ix < 1 or iy < 1 or ix+iw >= ev['mask'].shape[1]-1 or iy+ih >= ev['mask'].shape[0]-1
                    or not .8 < layout['width']/iw < 1.25 or not .8 < layout['height']/ih < 1.25):
                continue
            families[(r['font_id'], r.get('stroke_width', 0))].append(
                {'region': r, 'source': (ev['x']+ix, ev['y']+iy, iw, ih)})
        except ValueError:
            continue
    proposals = []
    for items in families.values():
        for group in _peer_groups(items):
            sizes = [i['region']['font_size'] for i in group]
            counts = Counter(sizes)
            target, count = counts.most_common(1)[0]
            if (len(counts) == 1 or count <= len(group)/2 or max(sizes)-min(sizes) > min(2, min(sizes)*.06)
                    or max(i['source'][3] for i in group) > min(i['source'][3] for i in group)*1.25):
                continue
            proposals.append((-len(group), max(sizes)-min(sizes), target, group))
    changed = 0
    used = set()
    for _, _, target, group in sorted(proposals, key=lambda p: p[:3]):
        ids = {i['region']['id'] for i in group}
        if ids & used:
            continue
        updates = {}
        for item in group:
            r = item['region']
            if r['font_size'] == target:
                continue
            try:
                baseline = visual_score(image, r['bbox'], [r])
                if baseline < .65:
                    break
                candidate = fit_region_at_size(image, r, target)
                limit = min(2, target*.05)
                if (not candidate.get('enabled') or candidate.get('fit_status') != 'fitted'
                        or abs(candidate['x']-r['x']) > limit or abs(candidate['y']-r['y']) > limit
                        or abs(candidate['letter_spacing']-r.get('letter_spacing', 0)) > 1):
                    break
                layout = outline_layout(r['font_id'], r['text'], target,
                                        candidate['letter_spacing'], r.get('stroke_width', 0))
                box = (candidate['x'], candidate['y'], layout['width'], layout['height'])
                x, y, w, h = r['bbox']
                if box[0] < x or box[1] < y or box[0]+box[2] > x+w or box[1]+box[3] > y+h:
                    break
                # Evaluate precisely the properties we will keep; color and all
                # source metadata remain the user's original values.
                patch = {key: candidate[key] for key in ('font_size', 'letter_spacing', 'x', 'y')}
                score = visual_score(image, r['bbox'], [dict(r, **patch)])
                if score < .65 or score < baseline-.02:
                    break
                updates[r['id']] = (patch, box, baseline, score, candidate['score'])
            except (KeyError, ValueError, RuntimeError):
                break
        else:
            if any(_overlap(box, updates.get(other, (None, oldbox))[1]) > _overlap(boxes[rid], oldbox)+.5
                   for rid, (_, box, *_) in updates.items() for other, oldbox in boxes.items() if rid != other):
                continue
            for item in group:
                r = item['region']
                if r['id'] not in updates:
                    continue
                patch, box, baseline, score, fit_score = updates[r['id']]
                before = {key: deepcopy(r.get(key, 0)) for key in patch}
                r.update(patch, score=fit_score)
                for alternative in r.get('alternatives', []):
                    if alternative.get('font_id') == r['font_id']:
                        alternative.update(patch, score=fit_score)
                r['size_normalization'] = {'before': before, 'after': dict(patch),
                                           'visual_before': baseline, 'visual_after': score}
                boxes[r['id']] = box
                changed += 1
            used.update(ids)
    return changed
