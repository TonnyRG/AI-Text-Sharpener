"""Post-process OCR regions: merge bboxes that belong to the same visual line.

PaddleOCR's detector sometimes splits a single line of text into multiple
adjacent bboxes (notably when the line has mixed Latin/CJK or when an
artistic title spans a long box). Rendered separately each segment gets
its own `text-anchor="middle"`, producing visible gaps between fragments.
Merging same-row neighbours restores a single continuous text element.
"""
from typing import List, Tuple

from .detect import TextRegion


def _rect(region: TextRegion) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in region.bbox]
    ys = [p[1] for p in region.bbox]
    x, y = int(min(xs)), int(min(ys))
    return x, y, int(max(xs)) - x, int(max(ys)) - y


def _same_row(h_a: int, yc_a: float, h_b: int, yc_b: float, overlap: float = 0.6) -> bool:
    return abs(yc_a - yc_b) < min(h_a, h_b) * overlap


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "　" <= ch <= "〿"


def _join_text(left: str, right: str) -> str:
    """Concatenate two text fragments. Normalize a trailing half-width colon
    to its full-width form when the next character is CJK, so '作者:李南樽'
    becomes '作者：李南樽' to match the visual spacing of OCR-given full-width
    colons (as in '专业：制药工程')."""
    if not left or not right:
        return left + right
    if left.endswith(":") and _is_cjk(right[0]):
        return left[:-1] + "：" + right
    return left + right


def merge_horizontal_neighbors(
    regions: List[TextRegion],
    gap_ratio: float = 1.0,
) -> List[TextRegion]:
    """Merge same-row regions whose horizontal gap is < gap_ratio × min(height).

    A trailing half-width colon before CJK is normalized to full-width so the
    rendered spacing matches OCR-given full-width colons. Default gap_ratio=1.0
    is conservative; raise it if OCR splits a line with visibly larger gaps."""
    if not regions:
        return []

    # Decorate each region with its rect.
    items = [(r, *_rect(r)) for r in regions]  # (region, x, y, w, h)
    items.sort(key=lambda it: it[2] + it[4] / 2)  # by y-center

    # Cluster into rows.
    rows: List[List[Tuple]] = []
    for it in items:
        _, _, y, _, h = it
        yc = y + h / 2
        for row in rows:
            ry0 = min(rt[2] for rt in row)
            ry1 = max(rt[2] + rt[4] for rt in row)
            rh = ry1 - ry0
            ryc = (ry0 + ry1) / 2
            if _same_row(h, yc, rh, ryc):
                row.append(it)
                break
        else:
            rows.append([it])

    # Within each row, merge horizontally adjacent regions.
    merged: List[TextRegion] = []
    for row in rows:
        row.sort(key=lambda it: it[1])  # by x
        cur = None
        for it in row:
            r, x, y, w, h = it
            if cur is None:
                cur = it
                continue
            cr, cx, cy, cw, ch = cur
            gap = x - (cx + cw)
            if gap < min(h, ch) * gap_ratio:
                nx0, ny0 = min(cx, x), min(cy, y)
                nx1, ny1 = max(cx + cw, x + w), max(cy + ch, y + h)
                new_bbox = [[nx0, ny0], [nx1, ny0], [nx1, ny1], [nx0, ny1]]
                new_region = TextRegion(
                    bbox=new_bbox,
                    text=_join_text(cr.text, r.text),
                    confidence=min(cr.confidence, r.confidence),
                )
                cur = (new_region, nx0, ny0, nx1 - nx0, ny1 - ny0)
            else:
                merged.append(cur[0])
                cur = it
        if cur is not None:
            merged.append(cur[0])

    merged.sort(key=lambda r: (min(p[1] for p in r.bbox), min(p[0] for p in r.bbox)))
    return merged
