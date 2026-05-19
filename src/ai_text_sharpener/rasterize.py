"""Rasterize SVG to PNG using resvg."""
from pathlib import Path
from typing import Iterable, Optional

import resvg_py


def svg_to_png(
    svg_text: str,
    output_path: Path,
    font_dirs: Optional[Iterable[Path]] = None,
) -> None:
    kwargs: dict = {"svg_string": svg_text}
    if font_dirs:
        dirs = [str(Path(d)) for d in font_dirs if d and Path(d).exists()]
        if dirs:
            kwargs["font_dirs"] = dirs
    png_bytes = resvg_py.svg_to_bytes(**kwargs)
    Path(output_path).write_bytes(bytes(png_bytes))
