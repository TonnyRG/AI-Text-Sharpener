"""Scan source pixels within a user-selected area and map OCR back to the page."""
import math

import cv2
import numpy as np

from .geometry import source_frame


def _bounds(box):
    x, y, w, h = box
    return x, y, x + w, y + h


def _clip(box, limits):
    x, y, right, bottom = _bounds(box)
    left, top, end_x, end_y = limits
    x, y = max(x, left), max(y, top)
    return [x, y, min(right, end_x) - x, min(bottom, end_y) - y]


def scan_target(payload, page):
    if ('bbox' in payload) == ('region_id' in payload):
        raise ValueError('请选择一个原字范围或文字框。')
    target = None
    if 'region_id' in payload:
        target = next((r for r in page['regions'] if r['id'] == payload['region_id']), None)
        if target is None or not _editable(target):
            raise ValueError('请选择未锁定且未设为保留原图的普通文字。')
        box = target['bbox']
    else:
        box = payload['bbox']
    if (not isinstance(box, list) or len(box) != 4
            or any(type(v) not in (float, int) or abs(v) > 1e9 or not math.isfinite(v) for v in box)):
        raise ValueError('原字范围必须是四个有限的坐标和尺寸。')
    clipped = _clip(box, (0, 0, page['width'], page['height']))
    if min(clipped[2:]) < 3:
        raise ValueError('请在画面内框选至少 3 × 3 像素的范围。')
    return target, clipped


def _editable(region):
    return not (region.get('locked') or region.get('preserve_original') or region.get('kind') == 'formula')


def _contained(box, limits):
    x, y, right, bottom = _bounds(box)
    return limits[0] <= x and limits[1] <= y and right <= limits[2] and bottom <= limits[3]


def conflicts(candidate, existing):
    # OCR adds 3 px around a line. Ignore mere contact between padded edges,
    # but reject partial readings of a protected/partially selected line.
    cx, cy, cr, cb = _bounds(candidate['bbox'])
    for region in existing:
        x, y, right, bottom = _bounds(region['bbox'])
        width = min(cr, right) - max(cx, x)
        height = min(cb, bottom) - max(cy, y)
        if (width > min(3, (cr - cx) / 2, (right - x) / 2)
                and height > min(3, (cb - cy) / 2, (bottom - y) / 2)):
            return True
    return False


def _page_regions(detect, image, box, target, progress):
    x, y, right, bottom = _bounds(box)
    left, top = math.floor(x), math.floor(y)
    crop = image[top:math.ceil(bottom), left:math.ceil(right)]
    transform = None
    if target and target.get('source_rotation'):
        # A moved redraw still samples its source. Deskew inside the selected
        # crop, so neighboring page pixels can never become OCR input.
        local = dict(target, bbox=[x-left, y-top, box[2], box[3]])
        if 'source_quad' in local:
            local['source_quad'] = np.asarray(local['source_quad']) - [left, top]
        crop, _, transform = source_frame(crop, local)
    def detect_padded(margin):
        padded = cv2.copyMakeBorder(crop, margin, margin, margin, margin, cv2.BORDER_REPLICATE)
        return detect(padded, progress)

    padding = 20
    detected = detect_padded(padding)
    # A tight crop of a short label can occupy too much of the detector's
    # input even when the glyphs are clear. Give it more surrounding space
    # without introducing neighboring page pixels or scaling the source.
    short_side, long_side = sorted(crop.shape[:2])
    if (not detected and short_side <= 160 and long_side <= 1600
            and np.ptp(crop, axis=(0, 1)).max() >= 4):
        padding = max(48, short_side)
        detected = detect_padded(padding)
    limits = _bounds(box)

    def map_points(points):
        points = np.asarray(points, dtype=float) - padding
        if transform is not None:
            rotation, origin, _ = transform
            points = points @ rotation.T + origin
        return points + [left, top]

    def map_box(rect):
        a, b, c, d = _bounds(rect)
        points = map_points([[a,b], [c,b], [c,d], [a,d]])
        low = points.min(axis=0)
        return _clip([*low, *(points.max(axis=0)-low)], limits)

    result = []
    for region in detected:
        mapped = map_box(region['bbox'])
        if min(mapped[2:]) < 3:
            continue
        region['bbox'] = mapped
        if 'ocr_bbox' in region:
            region['ocr_bbox'] = map_box(region['ocr_bbox'])
        if 'recognition_boxes' in region:
            region['recognition_boxes'] = map_points(region['recognition_boxes']).tolist()
        if 'source_quad' in region:
            quad = map_points(region['source_quad'])
            quad = np.clip(quad, limits[:2], limits[2:])
            # Ignore detections supported only by the repeated border.
            if cv2.contourArea(quad.astype(np.float32)) < 1:
                continue
            region['source_quad'] = quad.tolist()
        region['x'], region['y'] = map_points([region['x'], region['y']]).tolist()
        if transform is not None:
            angle = round((region['source_rotation'] + transform[2] + 180) % 360 - 180, 2)
            region.update(source_rotation=angle, rotation=angle)
        result.append(region)
    return result


def rescan_area(detect, image, page, payload, progress):
    target, box = scan_target(payload, page)
    candidates = _page_regions(detect, image, box, target, progress)
    if not candidates:
        raise ValueError('选区内未识别到文字，请调整范围后重试。')
    limits = _bounds(box)
    page_limits = (0, 0, page['width'], page['height'])
    replaceable = {r['id'] for r in page['regions']
                   if _editable(r) and (r is target if target is not None
                                        else _contained(_clip(r['bbox'], page_limits), limits))}
    retained = [r for r in page['regions'] if r['id'] not in replaceable]
    accepted = [r for r in candidates if not conflicts(r, retained)]
    if not accepted:
        raise ValueError('选区内的文字与现有受保护或未完整选入的文字框重叠。')
    # A crop can miss an existing line while finding a new one. Preserve that
    # existing line unless an accepted detection actually replaces it.
    replaced = {r['id'] for r in page['regions'] if r['id'] in replaceable
                and (target is not None or conflicts(r, accepted))}
    insert = next((i for i, r in enumerate(page['regions']) if r['id'] in replaced), len(page['regions']))
    regions = [r for r in page['regions'] if r['id'] not in replaced]
    regions[insert:insert] = accepted
    if len(regions) > 500:
        raise ValueError('本页文字区域超过 500 个，请缩小识别范围。')
    return regions, accepted
