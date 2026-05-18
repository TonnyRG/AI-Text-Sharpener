"""Rasterize SVG to PNG using resvg."""
from pathlib import Path

import resvg_py


def svg_to_png(svg_text: str, output_path: Path) -> None:
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_text)
    Path(output_path).write_bytes(bytes(png_bytes))
