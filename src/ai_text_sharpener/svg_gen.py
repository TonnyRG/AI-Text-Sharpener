"""Generate SVG with embedded image background and overlaid text elements."""
from dataclasses import dataclass
from html import escape
from typing import List, Tuple


@dataclass
class TextElement:
    x: int                     # center x (text-anchor=middle)
    y: int                     # baseline y
    text: str
    font_family: str
    font_size_px: int
    color: Tuple[int, int, int]
    font_weight: str = "normal"


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
    return (
        f'  <text x="{t.x}" y="{t.y}" '
        f'font-family="{escape(t.font_family)}" '
        f'font-size="{t.font_size_px}" '
        f'font-weight="{t.font_weight}" '
        f'fill="rgb({t.color[0]},{t.color[1]},{t.color[2]})" '
        f'text-anchor="middle" dominant-baseline="middle">'
        f'{escape(t.text)}</text>\n'
    )


def generate_svg(width: int, height: int, background_b64: str,
                 texts: List[TextElement]) -> str:
    return _SVG_TEMPLATE.format(
        w=width, h=height, bg=background_b64,
        texts="".join(_text_tag(t) for t in texts),
    )
