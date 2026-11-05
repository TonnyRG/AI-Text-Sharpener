"""Explicit LaTeX spans inside one otherwise ordinary Studio text region."""
from dataclasses import dataclass
from functools import lru_cache
import re


@dataclass(frozen=True)
class InlineSpan:
    kind: str
    start: int
    end: int
    value: str


_TOKENS = re.compile(r'\\[\[\]()]|\$\$')
_CLOSERS = {r'\[': r'\]', r'\(': r'\)', '$$': '$$'}


@lru_cache(maxsize=1024)
def split_inline_math(text):
    """Return source-indexed runs. Unpaired and escaped delimiters are literal."""
    spans = []
    plain_start = 0
    opening = None
    for match in _TOKENS.finditer(text):
        start = match.start()
        # An escaped opener such as \\[ is ordinary text.
        back = start
        while back and text[back - 1] == '\\':
            back -= 1
        if (start - back) % 2:
            continue
        token = match.group()
        if opening and token == _CLOSERS[opening.group()]:
            value = text[opening.end():start]
            if value.strip():
                if opening.start() > plain_start:
                    spans.append(InlineSpan('text', plain_start, opening.start(), text[plain_start:opening.start()]))
                spans.append(InlineSpan('math', opening.start(), match.end(), value))
                plain_start = match.end()
            opening = None
        elif token in _CLOSERS:
            opening = match
    if plain_start < len(text):
        spans.append(InlineSpan('text', plain_start, len(text), text[plain_start:]))
    return tuple(spans)


def has_inline_math(text):
    return any(span.kind == 'math' for span in split_inline_math(text))


def region_has_inline_math(region):
    """Only interpret TeX that a user typed. Re-fitting OCR must preserve literal source."""
    text = region.get('text', '')
    authored = (region.get('text_format') == 'inline_math'
                or text != region.get('original_text', text))
    return authored and has_inline_math(text)


def plain_characters(text):
    """Characters the selected body font needs to supply for a mixed line."""
    return ''.join(span.value for span in split_inline_math(text) if span.kind == 'text')


def mixed_layout(spans, colors, size, spacing, stroke, text_layout):
    from .formula import formula_layout

    cursor = 0.0
    clusters = 0
    pieces = []
    glyphs = []
    for index, span in enumerate(spans):
        if index:
            cursor += spacing
        palette = colors[span.start:span.end]
        if span.kind == 'math':
            part = formula_layout(span.value, size, stroke)
            color = next((color for color in palette if color), None)
            paint = f' fill="{color}" color="{color}"' if color else ''
            glyph_boxes = [{'start': 0, 'box': [0, 0, part['width'], part['height']]}]
            clusters += 1
        else:
            part = text_layout(span.value, palette)
            paint = ''
            glyph_boxes = part['glyphs']
            clusters += part['cluster_count']
        x = cursor + part['left']
        y = -part['baseline']
        if part['body']:
            pieces.append((x, y, part['width'], part['height'],
                           f'<g transform="translate({x:.5f} {y:.5f})"{paint}>{part["body"]}</g>'))
            for glyph in glyph_boxes:
                gx, gy, w, h = glyph['box']
                glyphs.append({'start': span.start + glyph['start'], 'box': [x + gx, y + gy, w, h]})
        cursor += part['advance']
    left = min(piece[0] for piece in pieces)
    top = min(piece[1] for piece in pieces)
    right = max(x + w for x, _, w, _, _ in pieces)
    bottom = max(y + h for _, y, _, h, _ in pieces)
    for glyph in glyphs:
        glyph['box'][0] -= left
        glyph['box'][1] -= top
    body = ''.join(piece[4] for piece in pieces)
    return {'width': right - left, 'height': bottom - top, 'baseline': -top, 'left': left,
            'advance': cursor, 'spacing_slots': max(0, clusters - 1), 'glyphs': glyphs,
            'body': f'<g transform="translate({-left:.5f} {-top:.5f})">{body}</g>'}
