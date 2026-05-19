import base64
import re
from ai_text_sharpener.svg_gen import generate_svg, TextElement


def test_generate_svg_embeds_background_image():
    bg_b64 = base64.b64encode(b"fake-png-bytes").decode()
    svg = generate_svg(width=800, height=600, background_b64=bg_b64, texts=[])
    assert '<svg' in svg
    assert 'width="800"' in svg
    assert 'height="600"' in svg
    assert bg_b64 in svg
    assert 'xlink:href="data:image/png;base64,' in svg


def test_generate_svg_adds_text_elements():
    texts = [
        TextElement(x=100, y=200, text="Hello", font_family="Arial",
                    font_size_px=24, color=(255, 0, 0), font_weight="normal"),
        TextElement(x=300, y=400, text="标题", font_family="Microsoft YaHei",
                    font_size_px=48, color=(0, 0, 0), font_weight="bold"),
    ]
    svg = generate_svg(width=800, height=600, background_b64="x", texts=texts)
    assert "Hello" in svg
    assert "标题" in svg
    assert 'font-family="Arial"' in svg
    assert 'font-family="Microsoft YaHei"' in svg
    assert 'font-weight="bold"' in svg
    assert 'fill="rgb(255,0,0)"' in svg


def test_text_x_is_center_anchored():
    """Text x should be the horizontal center of bbox, with text-anchor=middle."""
    texts = [TextElement(x=400, y=100, text="X", font_family="Arial",
                         font_size_px=20, color=(0, 0, 0), font_weight="normal")]
    svg = generate_svg(width=800, height=600, background_b64="x", texts=texts)
    assert 'text-anchor="middle"' in svg


def test_generate_svg_adds_letter_spacing():
    texts = [TextElement(x=100, y=100, text="ABC", font_family="Arial",
                         font_size_px=20, color=(0, 0, 0),
                         letter_spacing_px=2.5)]
    svg = generate_svg(width=200, height=100, background_b64="x", texts=texts)
    assert 'letter-spacing="2.5px"' in svg
