"""Conservative per-glyph solid color recovery; geometry stays unchanged."""
from __future__ import annotations

import math
import re

import numpy as np

from .fidelity import crop_evidence
from .geometry import source_frame
from .typography import outline_layout


def validate_colors(region):
    mode = region.get("color_mode", "single")
    runs = region.get("color_runs", [])
    text = region.get("color_text", "")
    if mode not in {"single", "multi"} or not isinstance(text, str) or len(text) > 512:
        raise ValueError("无效多色文字配置。")
    if not isinstance(runs, list) or len(runs) > 512:
        raise ValueError("多色片段过多。")
    previous = 0
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("无效多色片段。")
        start, end, color = run.get("start"), run.get("end"), run.get("color")
        if (type(start) is not int or type(end) is not int or not previous <= start < end <= len(text)
                or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
            raise ValueError("多色片段范围或颜色无效。")
        previous = end


def region_layout(region):
    colors = []
    if region.get("color_mode") == "multi" and region.get("color_text") == region["text"]:
        colors = [None] * len(region["text"])
        for run in region.get("color_runs", []):
            colors[run["start"]:run["end"]] = [run["color"]] * (run["end"] - run["start"])
    return outline_layout(region["font_id"], region["text"], region["font_size"],
                          region.get("letter_spacing", 0), region.get("stroke_width", 0), tuple(colors))


def recover_colors(image, region):
    """Return a patch only, with no OCR, font fitting, or position changes.

    Source colors are sampled over normalized glyph columns, independent of
    the user's redrawn x/y/size. Require multiple supporting glyphs per color
    to avoid turning anti-aliasing, a border, or an isolated dot into an accent.
    """
    if region.get("kind") == "formula" or not region.get("text", "").strip():
        return {"color_note": "公式或空文字不参与多色提取。"}
    text = region["text"]
    original = region.get("original_text", "")
    if original and re.sub(r"\s", "", text) != re.sub(r"\s", "", original):
        return {"color_note": "内容已改动，无法可靠对应原字颜色，请手动设置片段颜色。"}
    if region.get("score") is not None and region["score"] < .65:
        return {"color_note": "文字拟合较弱，暂不自动分色；请先核对字体与字距。"}
    layout = outline_layout(region["font_id"], text, region["font_size"], region.get("letter_spacing", 0))
    frame, source_box, _ = source_frame(image, region)
    evidence = crop_evidence(frame, source_box)
    patch, background = evidence["patch"], evidence["background"]
    ix, iy, iw, ih = evidence["ink_box"]
    residual = np.linalg.norm(patch - background, axis=2)
    samples = []
    for glyph in layout["glyphs"]:
        x, y, w, h = glyph["box"]
        if w <= 0 or h <= 0:
            continue
        x0 = max(0, math.floor(ix + (x + w * .12) / layout["width"] * iw))
        x1 = min(patch.shape[1], math.ceil(ix + (x + w * .88) / layout["width"] * iw))
        y0 = max(0, math.floor(iy + .1 * ih))
        y1 = min(patch.shape[0], math.ceil(iy + .9 * ih))
        area, strength = patch[y0:y1, x0:x1], residual[y0:y1, x0:x1]
        if not strength.size:
            continue
        foreground = strength[strength > 35]
        if foreground.size < 6:
            continue
        peak = float(np.percentile(foreground, 80))
        strong = strength >= max(25, peak * .8)
        if np.count_nonzero(strong) < 6:
            continue
        samples.append((glyph["start"], np.median(area[strong], axis=0)))
    groups = []
    for index, color in samples:
        nearest = min(groups, key=lambda g: np.linalg.norm(color - np.median(g["colors"], axis=0)), default=None)
        if nearest is None or np.linalg.norm(color - np.median(nearest["colors"], axis=0)) > 65:
            groups.append({"colors": [color], "indices": [index]})
        else:
            nearest["colors"].append(color)
            nearest["indices"].append(index)
    valid = [g for g in groups if len(set(g["indices"])) >= 2]
    if not 2 <= len(valid) <= 4 or sum(len(g["indices"]) for g in valid) < len(samples) * .85:
        return {"color_note": "未发现可靠的多色片段，保留现有配色。"}
    palette = [np.median(g["colors"], axis=0).round().astype(int) for g in valid]
    # A grayscale brightness change is usually shading/anti-aliasing, not an accent.
    chroma = [c - c.mean() for c in palette]
    if max(np.linalg.norm(a-b) for a in chroma for b in chroma) < 35:
        return {"color_note": "颜色主要是明暗变化，保留现有配色。"}
    by_index = {idx: k for k, g in enumerate(valid) for idx in g["indices"]}
    indices = sorted(by_index)
    if not indices:
        return {"color_note": "未发现可靠的多色片段。"}
    labels = []
    for i, char in enumerate(text):
        # Spaces and punctuation inherit their nearest supported glyph.
        nearest = min(indices, key=lambda j: abs(i-j))
        labels.append(by_index.get(i, by_index[nearest]))
    runs = []
    for i, label in enumerate(labels):
        color = "#" + "".join(f"{c:02x}" for c in palette[label])
        if runs and runs[-1]["color"] == color:
            runs[-1]["end"] = i + 1
        else:
            runs.append({"start": i, "end": i + 1, "color": color})
    return {"color_mode": "multi", "color_text": text, "color_runs": runs, "color_source": "auto",
            "color_note": f"已从原图提取 {len(palette)} 种颜色，请对照原图核对分界。"}
