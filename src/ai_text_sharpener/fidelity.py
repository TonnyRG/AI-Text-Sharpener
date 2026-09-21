"""Local, image-evidenced font/size/spacing/position fitting.

Scores rank candidate renderings; they are not calibrated OCR probabilities.
Complex artwork and multiple styles in one box should be reviewed/split.
"""
from __future__ import annotations

import math
from copy import deepcopy

import cv2
import numpy as np

from .typography import candidate_fonts, family_weight_fonts, font_catalog, outline_layout, render_mask, supports
from .geometry import round_style, rotated_bounds, source_frame, source_position


def _single_line_mask(binary):
    """Discard small, detached fragments clipped by the top/bottom crop edge.

    OCR line boxes can include the descenders of the preceding line. Keep
    interior islands (accents, i-dots and punctuation), and require a generous
    gap before removing an edge band. This is deliberately not a general
    largest-component filter: Chinese glyphs often have disconnected strokes.
    """
    rows = np.flatnonzero(binary.any(axis=1))
    if not len(rows):
        return binary
    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    main = max(bands, key=lambda band: np.count_nonzero(binary[band]))
    mass = np.count_nonzero(binary[main])
    height = len(main)
    clean = binary.copy()
    for band in bands:
        if band[0] > 1 and band[-1] < len(binary) - 2:
            continue
        gap = max(main[0] - band[-1] - 1, band[0] - main[-1] - 1)
        if (len(band) < height * .35 and gap >= max(3, height * .18)
                and np.count_nonzero(binary[band]) < mass * .15):
            clean[band] = 0
    return clean


def _single_glyph_mask(binary):
    """Exclude disconnected corner background around a digit in a round badge.

    Only peripheral components separated from an interior glyph are eligible;
    never discard arbitrary small components such as dots or Chinese strokes.
    """
    count, labels, stats, centers = cv2.connectedComponentsWithStats(binary, 8)
    height, width = binary.shape
    def at_edge(s):
        x, y, w, h, _ = s
        return x <= 1 or y <= 1 or x+w >= width-1 or y+h >= height-1
    interior = [i for i in range(1, count) if not at_edge(stats[i])
                and width*.2 < centers[i][0] < width*.8
                and height*.2 < centers[i][1] < height*.8]
    if not interior:
        return binary
    main = max(interior, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    mx, my, mw, mh, area = stats[main]
    clean = binary.copy()
    for i in range(1, count):
        x, y, w, h, a = stats[i]
        cx, _ = centers[i]
        separated = (max(mx-cx, cx-mx-mw) > max(2, mw*.1)
                     or max(my-y-h, y-my-mh) > max(3, mh*.18))
        if at_edge(stats[i]) and a < area and separated:
            clean[labels == i] = 0
    return clean


def crop_evidence(image: np.ndarray, bbox: list[float], *, single_line=False, single_glyph=False):
    height, width = image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(width, int(math.ceil(x + w))), min(height, int(math.ceil(y + h)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise ValueError("文字框太小或超出图片范围。")
    patch = image[y0:y1, x0:x1].astype(np.float32)
    ph, pw = patch.shape[:2]
    yy, xx = np.mgrid[:ph, :pw]
    ring = (xx < 2) | (xx >= pw - 2) | (yy < 2) | (yy >= ph - 2)
    design = np.stack([np.ones_like(xx), xx / max(1, pw), yy / max(1, ph)], -1).astype(np.float32)
    # Robust plane fit preserves a simple gradient instead of flattening it.
    # A single digit's crop can straddle a circular badge: the outer ring then
    # samples the page, not the digit's actual background. Use the dominant
    # crop color for these small regions, with a stricter outlier rejection.
    samples = patch.reshape(-1, 3) if single_glyph else patch[ring]
    sample_design = design.reshape(-1, 3) if single_glyph else design[ring]
    med = np.median(samples, axis=0)
    distances = np.linalg.norm(samples - med, axis=1)
    keep = distances <= max(15, float(np.percentile(distances, 50 if single_glyph else 85)))
    coeff = np.linalg.lstsq(sample_design[keep], samples[keep], rcond=None)[0]
    background = np.clip(design @ coeff, 0, 255)
    residual = np.linalg.norm(patch - background, axis=2)
    strength = float(np.percentile(residual, 99))
    if strength < 12:
        raise ValueError("区域内文字对比度太低，请调整文字框或手动设置。")
    normalized = np.clip(residual / strength, 0, 1)
    _, binary = cv2.threshold((normalized * 255).astype(np.uint8), 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    clean = np.zeros_like(binary)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= max(2, ph * pw * 0.000015):
            clean[labels == label] = 255
    if single_line:
        clean = _single_line_mask(clean)
    if single_glyph:
        clean = _single_glyph_mask(clean)
    points = cv2.findNonZero(clean)
    if points is None:
        raise ValueError("未找到稳定的文字笔画，请手动画框。")
    ix, iy, iw, ih = cv2.boundingRect(points)
    strong = (clean > 0) & (residual >= np.percentile(residual[clean > 0], 65))
    color = np.median(patch[strong], axis=0).round().astype(int).tolist()
    # Remove weak background variation without hard-thresholding anti-aliasing.
    ink = np.where(cv2.dilate(clean, np.ones((3, 3), np.uint8)) > 0, normalized, 0)
    return {"x": x0, "y": y0, "patch": patch, "background": background,
            "mask": ink.astype(np.float32), "binary": clean,
            "ink_box": (ix, iy, iw, ih), "color": color}


def _match(target: np.ndarray, candidate: np.ndarray):
    # Compare softened masks at a common scale; final export stays sharp.
    if candidate.shape[0] > target.shape[0] or candidate.shape[1] > target.shape[1]:
        return 0.0, (0, 0)
    t = cv2.GaussianBlur(target, (0, 0), 0.65)
    c = cv2.GaussianBlur(candidate, (0, 0), 0.65)
    correlation = cv2.matchTemplate(t, c, cv2.TM_CCORR)
    _, best, _, loc = cv2.minMaxLoc(correlation)
    score = 2 * best / (float((t * t).sum()) + float((c * c).sum()) + 1e-8)
    return float(np.clip(score, 0, 1)), loc


def fit_region(image: np.ndarray, region: dict, font_ids=None, progress=None) -> dict:
    """Verify isolated-character orientation instead of trusting its OCR box."""
    angle = float(region.get("source_rotation", 0))
    if len(region["text"].strip()) != 1 or abs(angle) < .01:
        return _fit_at_angle(image, region, font_ids, progress)
    # A narrow upright digit can acquire either a small tilt or a quarter-turn
    # from OCR. Compare the original angle with upright, retaining real rotated
    # glyphs when their image fit is materially better.
    results = []
    for candidate_angle in (0, angle):
        candidate = dict(region, source_rotation=candidate_angle)
        try:
            results.append(_fit_at_angle(image, candidate, font_ids, progress))
        except ValueError:
            continue
    if not results:
        raise ValueError("单字拟合失败，请调整原字范围。")
    upright = next((r for r in results if not r["source_rotation"]), None)
    best = max(results, key=lambda r: r["score"])
    if upright is not None and upright["score"] >= best["score"] - .015:
        best = upright
    best["ocr_rotation"] = region.get("ocr_rotation", angle)
    return best


def _fit_at_angle(image: np.ndarray, region: dict, font_ids=None, progress=None) -> dict:
    result = deepcopy(region)
    text = region["text"].strip()
    if not text:
        raise ValueError("请先输入正确的文字。")
    frame, source_box, transform = source_frame(image, region)
    evidence = crop_evidence(frame, source_box, single_line=True, single_glyph=len(text) == 1)
    ix, iy, iw, ih = evidence["ink_box"]
    ids = font_ids or candidate_fonts(text)
    ids = [fid for fid in ids if fid in font_catalog() and supports(fid, text)]
    if not ids:
        raise ValueError("没有找到覆盖这些字符的字体，请先在系统安装字体。")
    scale = min(1.0, 64 / max(1, ih), 1000 / max(1, iw))
    # Padding permits small OCR-box errors while preserving original coordinates.
    pad = max(5, int(ih * .22))
    source = np.pad(evidence["mask"], pad)
    target = cv2.resize(source, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    target_ink = float(target.sum())
    candidates = []
    stroke_width = float(region.get("stroke_width", 0))
    # After coarse family selection, evaluate ALL weights of the strongest
    # families. The initial font budget must not exclude Regular or Medium.
    initial_count = len(ids)
    for index, fid in enumerate(ids):
        if progress:
            progress(f"匹配字体 {index + 1}/{len(ids)} · {font_catalog()[fid]['label']}")
        try:
            base = outline_layout(fid, text, 64.0, 0.0)
            estimated_size = max(4, min(1000, (ih-stroke_width) * 64 / max(1, base["height"])))
            best = None
            # Estimate spacing from the actual glyph geometry, then refine size.
            sizes = {max(4,min(1000,round_style(estimated_size*factor)+offset))
                     for factor in (.92,.97,1.0,1.035,1.08) for offset in (-1,0,1)}
            for size in sorted(sizes):
                natural = outline_layout(fid, text, round(size, 3), 0.0, stroke_width)
                spacing = (iw - natural["width"]) / max(1, len(text) - 1)
                spacing = float(np.clip(spacing, -size * .12, size * .35)) if len(text) > 1 else 0.0
                size, spacing = round_style(size), round_style(spacing)
                mask, _ = render_mask(fid, text, size * scale, spacing * scale, stroke_width * scale)
                score, (dx, dy) = _match(target, mask)
                # Overlap alone can prefer a smaller bold face over a regular
                # face with slightly different glyph proportions. Compare soft
                # ink coverage too, symmetrically penalizing heavier AND lighter
                # strokes; no hard-coded preference for Regular or thin fonts.
                ink_error = abs(math.log(max(float(mask.sum()), 1e-6) / max(target_ink, 1e-6)))
                score = max(0.0, score - .18 * min(ink_error, 1.0))
                layout = outline_layout(fid, text, size, spacing, stroke_width)
                item = {"font_id": fid, "font_label": font_catalog()[fid]["label"],
                        "font_size": round(size, 2), "letter_spacing": round(spacing, 2), "stroke_width": stroke_width,
                        **source_position(evidence["x"]-pad+dx/scale, evidence["y"]-pad+dy/scale,
                                          layout["width"], layout["height"], transform),
                        "score": round(score, 4)}
                if best is None or item["score"] > best["score"]:
                    best = item
            if best:
                candidates.append(best)
        except (ValueError, KeyError, RuntimeError):
            pass
        if index + 1 == initial_count and not font_ids:
            leaders = sorted(candidates, key=lambda c: c["score"], reverse=True)
            families, shortlisted = set(), []
            for item in leaders:
                family = font_catalog()[item["font_id"]]["family"]
                if family not in families:
                    families.add(family)
                    shortlisted.append(item["font_id"])
                if len(shortlisted) == 3:
                    break
            ids.extend(fid for fid in family_weight_fonts(shortlisted, text) if fid not in ids)
    if not candidates:
        raise ValueError("候选字体渲染失败，请尝试另一种字体。")
    candidates.sort(key=lambda c: c["score"], reverse=True)
    result.update(candidates[0])
    result["color"] = "#" + "".join(f"{c:02x}" for c in evidence["color"])
    result["alternatives"] = candidates[:5]
    result["fit_status"] = "review" if candidates[0]["score"] < .65 else "fitted"
    result["fit_note"] = "拟合分数衡量候选与原图的接近程度，不代表文字识别正确率。"
    layout = outline_layout(result["font_id"], text, result["font_size"], result["letter_spacing"], stroke_width)
    reason = automatic_fit_failure(result, layout)
    if reason:
        result.update(enabled=False, fit_status="preserved", fit_note=reason)
    return result


def automatic_fit_failure(region, layout):
    """Reject broken automatic fits, including results saved by older versions.

    Manual edits intentionally may move or enlarge text outside the source box.
    The score is a visual ranking, not a calibrated recognition probability.
    """
    if region.get("fit_status") not in {"fitted", "review", "preserved"}:
        return None
    score = region.get("score")
    if score is not None and score < .35:
        return "拟合与原图差异过大，已保留原图。可校正内容或改为公式区域。"
    x, y, w, h = region["bbox"]
    tolerance = max(5, h * .22)
    rx, ry, rw, rh = rotated_bounds(region["x"], region["y"], layout["width"], layout["height"], region.get("rotation", 0))
    if (rx < x-tolerance or ry < y-tolerance or rx+rw > x+w+tolerance or ry+rh > y+h+tolerance):
        return "自动拟合超出原字范围，已保留原图。"
    return None


def erase_regions(image: np.ndarray, regions: list[dict]) -> np.ndarray:
    output = image.copy()
    for region in regions:
        if not region.get("enabled", True):
            continue
        mode = region.get("erase_mode", "gradient")
        if mode == "none":
            continue
        try:
            frame, source_box, transform = source_frame(image, region)
            ordinary = region.get("kind") != "formula"
            ev = crop_evidence(frame, source_box, single_line=ordinary,
                               single_glyph=ordinary and len(region.get("original_text", region.get("text", "")).strip()) == 1)
        except ValueError:
            continue
        ph, pw = ev["patch"].shape[:2]
        x, y = ev["x"], ev["y"]
        radius = max(1, int(round(ph * .045)))
        mask = cv2.dilate(ev["binary"], np.ones((radius * 2 + 1, radius * 2 + 1), np.uint8))
        background = ev["background"].round().astype(np.uint8)
        if transform is not None:
            rotation, origin, _ = transform
            origin = origin + rotation @ np.array([x,y])
            corners = np.array([[0,0],[pw,0],[pw,ph],[0,ph]]) @ rotation.T + origin
            low = np.maximum(0, np.floor(corners.min(axis=0)).astype(int))
            high = np.minimum([image.shape[1],image.shape[0]], np.ceil(corners.max(axis=0)).astype(int))
            x,y = map(int,low);pw,ph = map(int,high-low)
            if pw<=0 or ph<=0:
                continue
            matrix = np.column_stack((rotation,origin-low))
            mask = cv2.warpAffine(mask,matrix,(pw,ph),flags=cv2.INTER_NEAREST)
            background = cv2.warpAffine(background,matrix,(pw,ph),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        if mode == "inpaint":
            # Include context outside the OCR box to reconstruct strokes near edges.
            margin = max(8, radius * 3)
            ax, ay = max(0, x - margin), max(0, y - margin)
            bx, by = min(image.shape[1], x + pw + margin), min(image.shape[0], y + ph + margin)
            local_mask = np.zeros((by - ay, bx - ax), np.uint8)
            local_mask[y-ay:y-ay+ph, x-ax:x-ax+pw] = mask
            repaired = cv2.inpaint(image[ay:by, ax:bx], local_mask, max(3, radius), cv2.INPAINT_TELEA)
            roi = output[ay:by, ax:bx]
            roi[local_mask > 0] = repaired[local_mask > 0]
        else:
            roi = output[y:y+ph, x:x+pw]
            repaired = background
            roi[mask > 0] = repaired[mask > 0]
    return output
