import base64
import re
from ai_text_sharpener.svg_gen import generate_svg, TextElement, TextSpan


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


def test_generate_svg_adds_span_font_family():
    """Mixed-family spans are emitted as separate <text> elements to work
    around resvg's failure to render alternating font-families inside one
    <text>/<tspan> group."""
    texts = [
        TextElement(
            x=100, y=100, text="2026 年",
            font_family="Noto Sans SC", font_size_px=20,
            color=(0, 0, 0), spans=[
                TextSpan(text="2026", font_family="Times New Roman"),
                TextSpan(text=" 年", font_family="Noto Sans SC"),
            ],
        )
    ]

    svg = generate_svg(width=200, height=100, background_b64="x", texts=texts)

    # Each family ends up on its own <text> element.
    assert svg.count('<text ') == 2
    times_runs = re.findall(r'<text[^>]*font-family="Times New Roman"[^>]*>2026</text>', svg)
    yahei_runs = re.findall(r'<text[^>]*font-family="Noto Sans SC"[^>]*> 年</text>', svg)
    assert len(times_runs) == 1
    assert len(yahei_runs) == 1
    # Both are anchored at start (we pre-compute x) so resvg renders correctly.
    assert 'text-anchor="start"' in times_runs[0]
    assert 'text-anchor="start"' in yahei_runs[0]


def test_generate_svg_uses_tspans_when_family_uniform():
    """When all spans share the same font-family, keep the compact
    single-text + tspans output."""
    texts = [
        TextElement(
            x=100, y=100, text="ABC", font_family="Arial", font_size_px=20,
            color=(0, 0, 0), spans=[
                TextSpan(text="A", color=(255, 0, 0)),
                TextSpan(text="B", font_weight="bold"),
                TextSpan(text="C"),
            ],
        )
    ]
    svg = generate_svg(width=200, height=100, background_b64="x", texts=texts)
    assert svg.count('<text ') == 1
    assert '<tspan' in svg


def test_glyph_xs_emits_one_text_per_char():
    t = TextElement(
        x=100, y=50, text="ABC", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 50, 90],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert svg.count("<text ") == 3
    assert 'x="10"' in svg and 'x="50"' in svg and 'x="90"' in svg
    assert svg.count('>A<') == 1
    assert svg.count('>B<') == 1
    assert svg.count('>C<') == 1
    assert svg.count('y="50"') == 3
    assert svg.count('font-family="Arial"') == 3


def test_glyph_xs_ignored_when_spans_present():
    """Spans path is unchanged; per-glyph not applied to span runs in this iteration."""
    t = TextElement(
        x=100, y=50, text="AB", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 90],
        spans=[TextSpan(text="A"), TextSpan(text="B")],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert svg.count("<text ") == 1
    assert "<tspan" in svg


def test_glyph_xs_length_mismatch_falls_back_to_single_text():
    """If glyph_xs length != len(text), don't try per-glyph; render the old way."""
    t = TextElement(
        x=100, y=50, text="ABC", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[10, 50],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert svg.count("<text ") == 1
    assert ">ABC<" in svg


def test_glyph_xs_empty_text_no_output():
    t = TextElement(
        x=100, y=50, text="", font_family="Arial",
        font_size_px=20, color=(0, 0, 0), font_weight="normal",
        glyph_xs=[],
    )
    svg = generate_svg(width=200, height=100, background_b64="x", texts=[t])
    assert "<text " not in svg
