from pathlib import Path
from ai_text_sharpener.rasterize import svg_to_png


def test_svg_to_png_produces_valid_png(tmp_path):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
           '<rect width="100" height="50" fill="red"/></svg>')
    out = tmp_path / "out.png"
    svg_to_png(svg, out)
    assert out.exists()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
