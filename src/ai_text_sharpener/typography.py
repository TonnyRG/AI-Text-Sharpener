"""Font discovery, HarfBuzz layout and real outline rendering for Studio.

The same SVG paths are used for fitting, preview and export. Coordinates are
visible-ink top-left, not an approximate font ascent or an OCR box center.
"""
from __future__ import annotations

import hashlib
import io
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
import resvg_py
import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image


@lru_cache(maxsize=1)
def font_catalog() -> dict[str, dict]:
    output = subprocess.check_output(
        ["fc-list", "-f", "%{file}|%{family}|%{style}|%{index}\n"], text=True,
    )
    result = {}
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        path, family, style, index = parts
        index = int(index or 0)
        # Fontconfig encodes named variable-font instances in the high bits.
        # Only expose base faces; static weight files remain distinct entries.
        if index >= 65536 or Path(path).suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            continue
        key = hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:16]
        aliases = family.split(",")
        family = aliases[0]
        style = style.split(",")[0] or "Regular"
        result[key] = {"id": key, "path": path, "index": index, "family": family, "aliases": aliases,
                       "style": style, "label": f"{family} · {style}"}
    return dict(sorted(result.items(), key=lambda kv: kv[1]["label"].lower()))


@lru_cache(maxsize=16)
def _tt(font_id: str):
    entry = font_catalog()[font_id]
    return TTFont(entry["path"], fontNumber=entry["index"], lazy=True)


@lru_cache(maxsize=8)
def _font_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


@lru_cache(maxsize=16)
def _hb(font_id: str):
    entry = font_catalog()[font_id]
    face = hb.Face(_font_bytes(entry["path"]), entry["index"])
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    hb.ot_font_set_funcs(font)
    return font


@lru_cache(maxsize=2048)
def supports(font_id: str, text: str) -> bool:
    try:
        cmap = _tt(font_id).getBestCmap()
        return all(c.isspace() or ord(c) in cmap for c in text)
    except Exception:
        return False


def candidate_fonts(text: str, limit: int = 22) -> list[str]:
    cjk = any("\u3400" <= c <= "\u9fff" for c in text)
    preferred = (["Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong",
                  "Source Han Sans CN", "Source Han Serif CN", "LXGW WenKai",
                  "FandolHei", "FandolSong", "Noto Sans CJK SC", "Noto Serif CJK SC"]
                 if cjk else ["Arial", "Times New Roman", "Calibri", "Montserrat",
                               "Ubuntu Sans", "Open Sans", "Liberation Sans",
                               "Source Sans 3", "DejaVu Sans", "Noto Sans"])
    def rank(entry):
        p = min((preferred.index(name) for name in entry.get("aliases", [entry["family"]])
                 if name in preferred), default=len(preferred) + 5)
        style = entry["style"].lower()
        return (p, "italic" in style or "oblique" in style,
                style not in {"regular", "normal", "bold", "light"}, style)
    ordered = sorted(font_catalog().values(), key=rank)
    results = []
    family_counts = {}
    for entry in ordered:
        if family_counts.get(entry["family"], 0) >= 3:
            continue
        if supports(entry["id"], text):
            results.append(entry["id"])
            family_counts[entry["family"]] = family_counts.get(entry["family"], 0) + 1
        if len(results) >= limit:
            break
    return results


def family_weight_fonts(font_ids: list[str], text: str) -> list[str]:
    """Expand shortlisted families to every installed upright static weight."""
    catalog = font_catalog()
    families = {catalog[fid]["family"] for fid in font_ids if fid in catalog}
    return [entry["id"] for entry in catalog.values()
            if entry["family"] in families
            and not any(s in entry["style"].lower() for s in ("italic", "oblique", "斜体"))
            and supports(entry["id"], text)]


@lru_cache(maxsize=8192)
def _glyph(font_id: str, gid: int):
    font = _tt(font_id)
    glyphs = font.getGlyphSet()
    name = font.getGlyphName(gid)
    glyph = glyphs[name]
    path = SVGPathPen(glyphs)
    glyph.draw(path)
    bounds = BoundsPen(glyphs)
    glyph.draw(bounds)
    return path.getCommands(), bounds.bounds


@lru_cache(maxsize=1024)
def outline_layout(font_id: str, text: str, size: float, spacing: float = 0, stroke_width: float = 0):
    if font_id not in font_catalog():
        raise ValueError("字体不存在，请重新选择本机字体。")
    if not text or len(text) > 512 or "\n" in text:
        raise ValueError("每个文字区域需为 1–512 个字符的单行文字；多行请分成多个区域。")
    if not supports(font_id, text):
        raise ValueError("所选字体缺少部分字符，请选择支持这些字符的字体。")
    if not 4 <= size <= 1000 or not math.isfinite(spacing):
        raise ValueError("字号必须在 4–1000 像素之间。")
    if not math.isfinite(stroke_width) or not 0 <= stroke_width <= 12:
        raise ValueError("笔画加粗必须在 0–12 像素之间。")
    font = _hb(font_id)
    scale = size / font.face.upem
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"liga": False, "kern": True})
    cursor_x = cursor_y = 0.0
    shapes, boxes = [], []
    infos, positions = buffer.glyph_infos, buffer.glyph_positions
    for idx, (info, pos) in enumerate(zip(infos, positions)):
        data, bounds = _glyph(font_id, info.codepoint)
        gx = cursor_x + pos.x_offset * scale
        gy = cursor_y - pos.y_offset * scale
        if bounds and data:
            x0, y0, x1, y1 = bounds
            boxes.append((gx + x0 * scale, gy - y1 * scale,
                          gx + x1 * scale, gy - y0 * scale))
            stroke = (f' stroke="currentColor" stroke-width="{stroke_width / scale:.6f}" stroke-linejoin="round"'
                      if stroke_width else '')
            shapes.append(f'<path transform="translate({gx:.5f} {gy:.5f}) scale({scale:.7f} {-scale:.7f})" d="{data}"{stroke}/>')
        cursor_x += pos.x_advance * scale
        cursor_y -= pos.y_advance * scale
        if idx + 1 < len(infos) and infos[idx + 1].cluster != info.cluster:
            cursor_x += spacing
    if not boxes:
        raise ValueError("该区域没有可见字符。")
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    inset = stroke_width / 2
    body = f'<g transform="translate({-left+inset:.5f} {-top+inset:.5f})">{"".join(shapes)}</g>'
    return {"body": body, "width": right - left + stroke_width, "height": bottom - top + stroke_width,
            "baseline": -top + inset, "advance": cursor_x}


def svg_document(width: int, height: int, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">{body}</svg>')


def render_mask(font_id: str, text: str, size: float, spacing: float = 0, stroke_width: float = 0):
    layout = outline_layout(font_id, text, round(size, 3), round(spacing, 3), round(stroke_width, 3))
    width, height = math.ceil(layout["width"]) + 2, math.ceil(layout["height"]) + 2
    if width * height > 20_000_000:
        raise ValueError("文字区域过大，请减小字号。")
    svg = svg_document(width, height, '<g fill="white" color="white">' + layout["body"] + '</g>')
    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert("RGBA")
    return np.asarray(image)[..., 3].astype(np.float32) / 255.0, layout
