"""Small, image-supported alignment corrections after a fresh page scan.

Source ink establishes the groups, not the positions of independently fitted
fonts. Three nearby peers are required; indentation and large drift are left
for manual alignment. Source erase boxes and manually edited regions stay put.
"""
from copy import deepcopy

import numpy as np

from .classification import visual_score
from .fidelity import crop_evidence
from .geometry import rotated_bounds
from .typography import outline_layout


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax+aw, bx+bw)-max(ax, bx))*max(0, min(ay+ah, by+bh)-max(ay, by))


def _groups(items, axis, factor):
    """Complete-span clusters prevent a chain of small indents becoming a group."""
    cross = 1-axis
    anchor = lambda item: item['source'][axis]+factor*item['source'][axis+2]
    ordered = sorted(items, key=anchor)
    clusters = []
    for item in ordered:
        if not clusters or anchor(item)-anchor(clusters[-1][0]) > 1.5:
            clusters.append([])
        clusters[-1].append(item)
    for cluster in clusters:
        neighbors = []
        for item in sorted(cluster, key=lambda i: i['source'][cross]):
            if neighbors:
                previous = neighbors[-1]
                gap = item['source'][cross]-previous['source'][cross]-previous['source'][cross+2]
                height = min(item['source'][3], previous['source'][3])
                if gap > height*(6 if axis == 0 else 10):
                    if len(neighbors) >= 3:
                        yield neighbors
                    neighbors = []
            neighbors.append(item)
        if len(neighbors) >= 3:
            yield neighbors


def align_page(image, regions):
    """Mutate only accepted output x/y values; return the corrected region count."""
    items = []
    boxes = {}
    baseline = {}
    for r in regions:
        if not r.get('enabled'):
            if r.get('bbox'):
                boxes[r['id']] = tuple(r['bbox'])
            continue
        if r.get('enabled'):
            try:
                layout = outline_layout(r['font_id'], r['text'], r['font_size'],
                                        r.get('letter_spacing', 0), r.get('stroke_width', 0)) if r.get('kind') != 'formula' else None
                w = layout['width'] if layout else r.get('ink_width', 0)
                h = layout['height'] if layout else r.get('ink_height', 0)
                boxes[r['id']] = rotated_bounds(r['x'], r['y'], w, h, r.get('rotation', 0))
            except (ValueError, KeyError):
                continue
        else:
            continue
        if (r.get('locked') or r.get('kind') == 'formula' or r.get('fit_status') != 'fitted'
                or (r.get('confidence') or 0) < .92 or (r.get('score') or 0) < .65
                or abs(r.get('rotation', 0)) > .01 or abs(r.get('source_rotation', 0)) > .01
                or len(r.get('text', '').strip()) < 2):
            continue
        try:
            ev = crop_evidence(image, r['bbox'], single_line=True)
            ix, iy, iw, ih = ev['ink_box']
            source = (ev['x']+ix, ev['y']+iy, iw, ih)
            # A clipped crop or a substantially wrong font is not alignment noise.
            if (ix < 1 or iy < 1 or ix+iw >= ev['mask'].shape[1]-1 or iy+ih >= ev['mask'].shape[0]-1
                    or not .8 < h/ih < 1.25 or not .8 < w/iw < 1.25):
                continue
            items.append({'region': r, 'source': source, 'size': (w, h)})
        except ValueError:
            continue
    original = {i['region']['id']: deepcopy(i['region']) for i in items}
    changed = set()
    for axis in (0, 1):
        key = 'x' if axis == 0 else 'y'
        proposals = []
        for factor in (0, .5, 1):
            for group in _groups(items, axis, factor):
                heights = [i['source'][3] for i in group]
                if max(heights) > min(heights)*1.25:
                    continue
                anchors = [i['source'][axis]+factor*i['source'][axis+2] for i in group]
                target = float(np.median(anchors))
                proposals.append((-len(group), max(anchors)-min(anchors), factor, target, group))
        used = set()
        for _, _, factor, target, group in sorted(proposals, key=lambda p: p[:3]):
            ids = {i['region']['id'] for i in group}
            if ids & used:
                continue
            cross = 1-axis
            peers = sorted(group, key=lambda i: i['source'][cross])
            if any(a['source'][cross]+a['source'][cross+2] > b['source'][cross]
                   for a, b in zip(peers, peers[1:])):
                continue
            updates = {}
            for item in group:
                r = item['region']
                value = round(target-factor*item['size'][axis], 2)
                if abs(value-r[key]) > min(4, max(1.5, r['font_size']*.1)):
                    break
                candidate = dict(r, **{key: value})
                try:
                    if r['id'] not in baseline:
                        baseline[r['id']] = visual_score(image, r['bbox'], [original[r['id']]])
                    score = visual_score(image, r['bbox'], [candidate])
                except ValueError:
                    break
                if score < .65 or score < baseline[r['id']]-.025:
                    break
                updates[r['id']] = (candidate, (candidate['x'], candidate['y'], *item['size']))
            else:
                # Do not introduce a collision with a neighboring text/formula.
                if any(_overlap(newbox, updates.get(other, (None, oldbox))[1]) > _overlap(boxes[rid], oldbox)+1
                       for rid, (_, newbox) in updates.items() for other, oldbox in boxes.items() if rid != other):
                    continue
                for item in group:
                    r = item['region']; candidate, box = updates[r['id']]
                    boxes[r['id']] = box
                    if abs(candidate[key]-r[key]) >= .01:
                        r[key] = candidate[key]
                        before = original[r['id']]
                        r['alignment_adjustment'] = {'before': [before['x'], before['y']],
                                                     'delta': [round(r['x']-before['x'], 2), round(r['y']-before['y'], 2)]}
                        changed.add(r['id'])
                used.update(ids)
    return len(changed)
