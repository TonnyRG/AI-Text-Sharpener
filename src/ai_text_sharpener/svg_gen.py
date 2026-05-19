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


_SVG_ANCHOR = {"center": "middle", "left": "start", "right": "end"}


_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
    '  <image x="0" y="0" width="{w}" height="{h}" '
    'xlink:href="data:image/png;base64,{bg}"/>\n'
    '{texts}'
    '</svg>\n'
)


def _text_tag(t: TextElement) -> str:
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


def generate_svg(width: int, height: int, background_b64: str,
                 texts: List[TextElement]) -> str:
    return _SVG_TEMPLATE.format(
        w=width, h=height, bg=background_b64,
        texts="".join(_text_tag(t) for t in texts),
    )
