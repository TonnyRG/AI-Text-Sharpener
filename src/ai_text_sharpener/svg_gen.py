"""Generate SVG with embedded image background and overlaid text elements."""
from dataclasses import dataclass, field
from html import escape
from typing import List, Optional, Tuple


@dataclass
class TextSpan:
    """One styled run within a TextElement.  None fields inherit from the parent element."""
    text: str
    color: Optional[Tuple[int, int, int]] = None
    font_size_px: Optional[int] = None
    font_family: Optional[str] = None
    font_weight: Optional[str] = None
    vertical_align: Optional[str] = None  # None | "super" | "sub"


@dataclass
class TextElement:
    x: int                     # anchor x (interpretation depends on text_anchor)
    y: int                     # baseline y
    text: str
    font_family: str
    font_size_px: int
    color: Tuple[int, int, int]
    font_weight: str = "normal"
    letter_spacing_px: float = 0.0
    text_anchor: str = "center"  # "center" | "left" | "right"
    spans: List[TextSpan] = field(default_factory=list)
    glyph_xs: Optional[List[int]] = None


_SVG_ANCHOR = {"center": "middle", "left": "start", "right": "end"}


def _estimate_width(text: str, font_size_px: int) -> float:
    """Heuristic width: CJK / full-width ≈ 1.0em, Latin ≈ 0.55em."""
    width = 0.0
    for ch in text or "":
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3000 <= cp <= 0x33FF) or \
           (0x3400 <= cp <= 0x4DBF) or (0xAC00 <= cp <= 0xD7AF) or \
           (0xFF00 <= cp <= 0xFFEF):
            width += font_size_px * 1.0
        elif ch == " ":
            width += font_size_px * 0.3
        else:
            width += font_size_px * 0.55
    return width


def _span_effective_family(span: TextSpan, parent: TextElement) -> str:
    return span.font_family or parent.font_family


def _spans_have_mixed_families(t: TextElement) -> bool:
    families = {_span_effective_family(s, t) for s in t.spans if s.text}
    return len(families) > 1


_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
    '  <image x="0" y="0" width="{w}" height="{h}" '
    'xlink:href="data:image/png;base64,{bg}"/>\n'
    '{texts}'
    '</svg>\n'
)


def _per_glyph_tags(t: TextElement) -> str:
    """Emit one <text> per character at its measured x.  Used when the caller
    has measured per-glyph centers from the source image; bypassed when text
    is empty or spans are present (spans path stays as-is in this iteration).
    """
    parts: List[str] = []
    for ch, gx in zip(t.text, t.glyph_xs or []):
        attrs = (
            f'x="{int(gx)}" y="{t.y}" '
            f'font-family="{escape(t.font_family)}" '
            f'font-size="{t.font_size_px}" '
            f'font-weight="{t.font_weight}" '
            f'fill="rgb({t.color[0]},{t.color[1]},{t.color[2]})" '
            f'text-anchor="middle" dominant-baseline="middle"'
        )
        parts.append(f'  <text {attrs}>{escape(ch)}</text>\n')
    return "".join(parts)


def _text_tag(t: TextElement) -> str:
    if not t.text and not t.spans:
        return ""
    if (
        t.glyph_xs is not None
        and not t.spans
        and t.text
        and len(t.glyph_xs) == len(t.text)
    ):
        return _per_glyph_tags(t)

    anchor = _SVG_ANCHOR.get(t.text_anchor, "middle")
    common = (
        f'x="{t.x}" y="{t.y}" '
        f'font-family="{escape(t.font_family)}" '
        f'font-size="{t.font_size_px}" '
        f'font-weight="{t.font_weight}" '
        f'letter-spacing="{t.letter_spacing_px}px" '
        f'fill="rgb({t.color[0]},{t.color[1]},{t.color[2]})" '
        f'text-anchor="{anchor}" dominant-baseline="middle"'
    )
    if not t.spans:
        return f'  <text {common}>{escape(t.text)}</text>\n'

    # resvg loses per-tspan font-family when families alternate within one
    # <text>; emit each run as its own <text> with computed x in that case.
    if _spans_have_mixed_families(t):
        return _mixed_family_tags(t)

    parts: List[str] = []
    for span in t.spans:
        attrs = ""
        if span.color is not None:
            attrs += f' fill="rgb({span.color[0]},{span.color[1]},{span.color[2]})"'
        # Auto-shrink to 65% for super/sub when user hasn't pinned a size.
        if span.font_size_px is not None:
            attrs += f' font-size="{span.font_size_px}"'
        elif span.vertical_align in ("super", "sub"):
            attrs += f' font-size="{max(8, int(t.font_size_px * 0.65))}"'
        if span.font_family is not None:
            attrs += f' font-family="{escape(span.font_family)}"'
        if span.font_weight is not None:
            attrs += f' font-weight="{span.font_weight}"'
        if span.vertical_align in ("super", "sub"):
            attrs += f' baseline-shift="{span.vertical_align}"'
        parts.append(f'<tspan{attrs}>{escape(span.text)}</tspan>')
    return f'  <text {common}>{"".join(parts)}</text>\n'


def _mixed_family_tags(t: TextElement) -> str:
    """Emit one <text> per span with computed x, working around the resvg
    multi-family-tspan rendering bug.  Centering is approximate (uses
    heuristic widths), but each span gets the right font.
    """
    seg_widths: List[float] = []
    for span in t.spans:
        if not span.text:
            seg_widths.append(0.0)
            continue
        size = span.font_size_px if span.font_size_px is not None else (
            max(8, int(t.font_size_px * 0.65))
            if span.vertical_align in ("super", "sub") else t.font_size_px
        )
        seg_widths.append(_estimate_width(span.text, size))
    total = sum(seg_widths)
    if t.text_anchor == "left":
        cursor = t.x
    elif t.text_anchor == "right":
        cursor = t.x - total
    else:  # center
        cursor = t.x - total / 2

    parts: List[str] = []
    for span, w in zip(t.spans, seg_widths):
        if not span.text:
            continue
        size = span.font_size_px if span.font_size_px is not None else (
            max(8, int(t.font_size_px * 0.65))
            if span.vertical_align in ("super", "sub") else t.font_size_px
        )
        family = span.font_family or t.font_family
        weight = span.font_weight or t.font_weight
        color = span.color or t.color
        attrs = (
            f'x="{int(cursor)}" y="{t.y}" '
            f'font-family="{escape(family)}" '
            f'font-size="{size}" '
            f'font-weight="{weight}" '
            f'letter-spacing="{t.letter_spacing_px}px" '
            f'fill="rgb({color[0]},{color[1]},{color[2]})" '
            f'text-anchor="start" dominant-baseline="middle"'
        )
        if span.vertical_align in ("super", "sub"):
            attrs += f' baseline-shift="{span.vertical_align}"'
        parts.append(f'  <text {attrs}>{escape(span.text)}</text>\n')
        cursor += w
    return "".join(parts)


def generate_svg(width: int, height: int, background_b64: str,
                 texts: List[TextElement]) -> str:
    return _SVG_TEMPLATE.format(
        w=width, h=height, bg=background_b64,
        texts="".join(_text_tag(t) for t in texts),
    )
