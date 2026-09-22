"""Linux-first local application: python -m ai_text_sharpener.studio."""
from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import re
import secrets
import threading
import time
import traceback
import uuid
import webbrowser
import cv2
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
import resvg_py
from PIL import Image, ImageFilter

from .colors import recover_colors
from .alignment import align_page
from .classification import resolve_types
from .geometry import source_frame
from .fidelity import crop_evidence, fit_region
from .formula import detect_formulas, fit_formula, recognize_formula, formula_available
from .studio_project import StudioStore, compose_page, export_pages, image_inputs, render_page, validate_regions
from .studio_files import default_export_directory, directory_contents, export_destination, save_export, remember_directory
from .typography import candidate_fonts, font_catalog, outline_layout, svg_document

WEB = Path(__file__).parent / "web"


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 4,
                            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                            "Det.limit_side_len": 1600, "Global.max_side_len": 3000,
                            "Global.log_level": "warning"})


def detect_regions(image_path: Path, progress=None):
    if progress:
        progress("正在本机识别中英文文字…")
    engine = ocr_engine()
    result = engine(str(image_path), return_word_box=True, use_det=True, use_cls=True, use_rec=True)
    regions = []
    image = np.asarray(Image.open(image_path).convert("RGB"))
    if progress:
        progress("正在检测完整公式区域…")
    formulas = detect_formulas(image)
    # RapidOCR exposes corrected text but not its 180-degree classification in
    # the combined result. Recover that direction from the same line crops.
    from rapidocr.utils.process_img import get_rotate_crop_image
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    boxes = result.boxes if result.boxes is not None else []
    crops = [get_rotate_crop_image(bgr, np.asarray(box,dtype=np.float32)) for box in boxes]
    directions = engine.text_cls(crops).cls_res if crops else []
    word_results = getattr(result, "word_results", None) or ()
    for index, (box, text, score) in enumerate(zip(boxes, result.txts or [], result.scores if result.scores is not None else [])):
        if not text.strip():
            continue
        points = np.asarray(box)
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        line_width = max(np.linalg.norm(points[1]-points[0]),np.linalg.norm(points[2]-points[3]))
        line_height = max(np.linalg.norm(points[3]-points[0]),np.linalg.norm(points[2]-points[1]))
        if line_height >= line_width*1.5:
            points = points[[1,2,3,0]]  # Same quarter-turn as RapidOCR's crop.
        if directions and '180' in directions[index][0] and directions[index][1] > engine.text_cls.cls_thresh:
            points = points[[2,3,0,1]]
        angle = math.degrees(math.atan2(points[1, 1] - points[0, 1], points[1, 0] - points[0, 0]))
        angle = round((angle+180)%360-180,2)
        if abs(angle)<.5:
            angle=0
        ids = candidate_fonts(text, limit=1)
        enabled = bool(ids) and float(score) >= .80
        region = {"id": uuid.uuid4().hex[:12], "text": text, "original_text": text,
                  "bbox": [max(0, float(x0)-3), max(0, float(y0)-3), float(x1-x0)+6, float(y1-y0)+6],
                  "x": float(x0), "y": float(y0), "font_id": ids[0] if ids else "",
                  "font_size": max(4, min(1000, round(float(np.linalg.norm(points[3]-points[0]))))), "letter_spacing": 0,
                  "rotation": angle, "source_rotation": angle, "source_quad": points.tolist(),
                  "color": "#182029", "enabled": enabled, "locked": False,
                  "confidence": round(float(score), 4), "score": None,
                  "erase_mode": "gradient", "fit_status": "new" if enabled else "preserved",
                  "fit_note": "" if enabled else "识别置信度较低或字体缺失，暂保留原图。"}
        words = word_results[index] if index < len(word_results) else None
        if enabled and words and not angle:
            refine_recognized_bounds(image, region, words)
        regions.append(region)
    if len(regions) > 500:
        raise ValueError("文字区域超过 500 个，请将页面拆分后处理。")
    return resolve_types(image, regions, formulas, engine=engine, detect=detect_formulas,
                         recognize=recognize_formula, fit_math=fit_formula, progress=progress)


def restore_plain_text(image, region):
    """Keep OCR evidence; old formula regions with no text get a local OCR retry."""
    text = region.get('text') or region.get('original_text') or ''
    if not text.strip():
        frame, box, _ = source_frame(image, region)
        x,y,w,h = map(int, box)
        crop = frame[max(0,y):min(frame.shape[0],y+h),max(0,x):min(frame.shape[1],x+w)]
        if not crop.size:
            raise ValueError('原文字范围无效，请调整后重试。')
        # Tight line crops can be rejected by the detector at the image edge.
        crop = cv2.copyMakeBorder(crop,20,20,20,20,cv2.BORDER_REPLICATE)
        result = ocr_engine()(cv2.cvtColor(crop,cv2.COLOR_RGB2BGR), use_det=True,use_cls=True,use_rec=True)
        text = ' '.join(getattr(result,'txts',None) or []).strip()
    if not text:
        raise ValueError('未识别出普通文字，原区域已保留。可调整原字范围后重试。')
    if len(text)>512:
        raise ValueError('区域文字过长，请拆成单行后重试。')
    fonts = candidate_fonts(text, limit=1)
    if not fonts:
        raise ValueError('本机没有支持这些文字的字体。')
    region.update(kind='text', text=text, original_text=region.get('original_text') or text,
                  font_id=fonts[0], enabled=True, preserve_original=False, score=None,
                  fit_status='edited', alternatives=[], fit_note='已恢复普通文字。')
    for key in ('type_decision','type_review','type_review_dismissed'):
        region.pop(key,None)


def refine_recognized_bounds(image, region, words):
    """Separate line detection bounds from the recognizer's actual text support.

    Recognition alignments are approximate: keep whole connected strokes that
    intersect their union, rather than cutting glyphs at character-box edges.
    Never infer decoration merely from its color or shape.
    """
    normalize = lambda value: "".join(value.split())
    if normalize("".join(w[0] for w in words)) != normalize(region["original_text"]):
        return
    if any(w[1] < .8 or w[2] is None for w in words):
        return
    boxes = np.asarray([w[2] for w in words], dtype=float)
    if boxes.ndim != 3 or boxes.shape[1:] != (4, 2) or not np.isfinite(boxes).all():
        return
    try:
        ev = crop_evidence(image, region["bbox"])
    except ValueError:
        return
    ph, pw = ev["binary"].shape
    points = boxes.reshape(-1, 2)
    low, high = points.min(axis=0), points.max(axis=0)
    x0 = max(0, int(math.floor(low[0] - ev["x"])) - 3)
    y0 = max(0, int(math.floor(low[1] - ev["y"])) - 3)
    x1 = min(pw, int(math.ceil(high[0] - ev["x"])) + 3)
    y1 = min(ph, int(math.ceil(high[1] - ev["y"])) + 3)
    if x1 <= x0 or y1 <= y0:
        return
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ev["binary"], 8)
    included = np.unique(labels[y0:y1, x0:x1]);included = included[included > 0]
    if not len(included):
        return
    selected = stats[included]
    left, top = selected[:, :2].min(axis=0)
    right, bottom = (selected[:, :2] + selected[:, 2:4]).max(axis=0)
    if selected[:, cv2.CC_STAT_AREA].sum() < np.count_nonzero(ev["binary"]) * .6:
        return  # A large disagreement needs manual review.
    # Only change a box when the recognizer excluded actual foreground ink.
    if len(included) == len(stats) - 1:
        return
    left, top = max(0, int(left)-3), max(0, int(top)-3)
    right, bottom = min(pw, int(right)+3), min(ph, int(bottom)+3)
    region["ocr_bbox"] = region["bbox"][:]
    region["bbox"] = [ev["x"]+left, ev["y"]+top, right-left, bottom-top]
    region["recognition_boxes"] = boxes.tolist()


def make_demo():
    fonts = font_catalog()
    def choose(family, style, text):
        for entry in fonts.values():
            if family in entry.get("aliases", [entry["family"]]) and entry["style"].lower() == style:
                return entry["id"]
        return candidate_fonts(text, 1)[0]
    pieces = ['<rect width="1600" height="900" fill="#f4f6f8"/>',
              '<rect x="80" y="290" width="1440" height="500" rx="28" fill="white"/>',
              '<rect x="1040" y="320" width="440" height="420" rx="22" fill="#153b38"/>']
    samples = [("让文字，清晰如初。", 90, 95, 78, "Microsoft YaHei", "bold", "#17262b"),
               ("保留原图的设计，重新找回文字的细节。", 92, 215, 28, "Microsoft YaHei", "regular", "#647179"),
               ("从字形，到排版", 125, 355, 46, "Source Han Serif CN", "bold", "#263d3e"),
               ("位置 · 字体 · 大小 · 字重", 128, 445, 30, "Microsoft YaHei", "regular", "#3c5759"),
               ("Precision in every letter", 128, 550, 43, "Times New Roman", "regular", "#304a49"),
               ("Aa  2026", 1080, 385, 60, "Arial", "bold", "#ffffff"),
               ("清晰，也接近原作", 1080, 515, 27, "Microsoft YaHei", "regular", "#cce6dd"),
               ("示例为本机生成的模糊文字测试页", 92, 831, 21, "Microsoft YaHei", "regular", "#79878b")]
    for text, x, y, size, family, style, color in samples:
        fid = choose(family, style, text)
        layout = outline_layout(fid, text, float(size), 0.0)
        pieces.append(f'<g fill="{color}" transform="translate({x} {y})">{layout["body"]}</g>')
    raw = resvg_py.svg_to_bytes(svg_string=svg_document(1600, 900, "".join(pieces)))
    return Image.open(io.BytesIO(raw)).convert("RGB").filter(ImageFilter.GaussianBlur(1.0))


class Studio:
    def __init__(self, root=None):
        self.store = StudioStore(root)
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sharpener")
        self.job = {"active": False, "id": "", "status": "idle", "message": "准备就绪"}
        self.cancelled = threading.Event()

    def ensure_idle(self):
        if self.job["active"]:
            raise RuntimeError("当前任务尚未结束，请等待或取消后再操作。")

    def start_job(self, payload):
        with self.lock:
            self.ensure_idle()
            payload = dict(payload, _destination=None)
            kind = payload.get("kind")
            if kind not in {"analyze", "analyze_all", "fit", "render", "export", "formula_recognize", "formula_fit", "text_restore", "colors"}:
                raise ValueError("未知任务。")
            project = self.store.load(payload["project_id"])
            if payload.get("revision") != project["revision"]:
                raise RuntimeError("项目已发生变化，请刷新后重试。")
            page = next((p for p in project["pages"] if p["id"] == payload.get("page_id")), None)
            if page is None and kind not in {"export", "analyze_all"}:
                raise ValueError("页面不存在。")
            if not project["pages"]:
                raise ValueError("项目没有页面，请先导入 PPTX 或图片。")
            if kind == "colors":
                if payload.get("scope", "current") not in {"current", "all"}:
                    raise ValueError("无效颜色提取范围。")
                if payload.get("region_id") and not any(r["id"] == payload["region_id"] for r in page["regions"]):
                    raise ValueError("文字区域不存在。")
            if kind == "export":
                if (payload.get("scope", "all") not in {"all", "current"}
                        or payload.get("format", "pptx") not in {"pptx", "svg", "png", "json"}):
                    raise ValueError("无效的导出范围或格式。")
                if payload.get("scope") == "current" and page is None:
                    raise ValueError("页面不存在。")
                fmt, scope = payload.get("format", "pptx"), payload.get("scope", "all")
                if fmt == "json" and scope != "all":
                    raise ValueError("编辑数据备份必须包含全部页面。")
                if "destination" in payload:
                    extension = "zip" if scope == "all" and fmt in {"svg", "png"} else fmt
                    payload["_destination"] = export_destination(payload["destination"], extension, self.store.root)
            if not isinstance(payload.get("reset", False), bool):
                raise ValueError("重新识别参数必须为布尔值。")
            if kind == "analyze" and page["regions"] and not payload.get("reset"):
                raise ValueError("重新识别需确认替换当前文字区域。")
            self.cancelled.clear()
            self.job = {"id": uuid.uuid4().hex, "active": True, "status": "running",
                        "kind": kind, "project_id": project["id"], "page_id": payload.get("page_id"),
                        "message": "准备处理…", "progress": 0, "warnings": [], "download": None}
            self.executor.submit(self._run, payload, project, page)
            return dict(self.job)

    def _run(self, payload, project, page):
        def progress(message, value=None):
            if self.cancelled.is_set():
                raise InterruptedError("已取消，已完成页面的结果已保存。"
                                       if payload["kind"] == "analyze_all" else "任务已取消，保留处理前的项目。")
            with self.lock:
                self.job["message"] = message
                if value is not None:
                    self.job["progress"] = value
        try:
            directory = self.store.directory(project["id"])
            kind = payload["kind"]
            if kind == "analyze_all":
                total = len(project["pages"])
                completed = skipped = failed = 0
                if payload.get("reset"):
                    progress("准备重新识别全部页面…", 0)
                    backup_dir = directory / "backups"
                    backup_dir.mkdir(exist_ok=True)
                    (backup_dir / f"before-rescan-{uuid.uuid4().hex}.json").write_text(
                        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
                    # Keep old results until each replacement finishes. Persist
                    # pending flags so cancellation/restart can resume the rest.
                    for item in project["pages"]:
                        item["pending_rescan"] = True
                    with self.lock:
                        project["revision"] += 1
                        self.store.save(project)
                for index, original in enumerate(project["pages"]):
                    prefix = f"第 {index+1}/{total} 页"
                    progress(prefix, index / total * 100)
                    # Keep existing edits and resume only unfinished pages.
                    if not original.get("pending_rescan") and (original.get("status") == "review" or original["regions"]):
                        skipped += 1
                        continue
                    working = deepcopy(original)
                    def page_progress(message, value=0):
                        progress(f"{prefix} · {message}", (index + value / 100) / total * 100)
                    try:
                        self._fit_page(dict(payload, kind="analyze"), directory, working, page_progress)
                        page_progress("生成预览", 95)
                        render_page(directory, working)
                        working["render_revision"] = project["revision"] + 1
                        working.pop("error", None)
                        working.pop("pending_rescan", None)
                        project["pages"][index] = working
                        completed += 1
                    except InterruptedError:
                        raise
                    except Exception as exc:
                        original.update(status="error", error=str(exc))
                        self.job["warnings"].append(f"{prefix}失败：{exc}")
                        failed += 1
                    with self.lock:
                        project["revision"] += 1
                        self.store.save(project)
                progress("完成", 100)
                with self.lock:
                    self.job.update(active=False, status="done", completed=completed, skipped=skipped, failed=failed,
                                    message=f"共 {total} 页：完成 {completed} 页，保留已有结果 {skipped} 页，失败 {failed} 页。")
                return
            if kind == "colors":
                targets = project["pages"] if payload.get("scope") == "all" else [page]
                changed = 0
                for index, item in enumerate(targets):
                    image = np.asarray(Image.open(directory / f"{item['id']}.png").convert("RGB"))
                    for region in item["regions"]:
                        progress(f"第 {index+1}/{len(targets)} 页 · 提取文字颜色…", index / len(targets) * 90)
                        if (not region.get("enabled") or region.get("locked") or region.get("kind") == "formula"
                                or (region.get("color_source") == "manual" and not payload.get("region_id"))
                                or (payload.get("region_id") and region["id"] != payload["region_id"])):
                            continue
                        try:
                            patch = recover_colors(image, region)
                            changed += patch.get("color_mode") == "multi"
                            region.update(patch)
                        except ValueError as exc:
                            region["color_note"] = str(exc)
                    item["render_revision"] = -1
                progress("保存颜色结果…", 95)
                with self.lock:
                    project["revision"] += 1
                    self.store.save(project)
                    self.job.update(active=False, status="done", progress=100,
                                    message=f"已检查 {len(targets)} 页，恢复 {changed} 处多色文字；锁定区域与手动配色已保留。")
                return
            if kind == "text_restore":
                region = next((r for r in page['regions'] if r['id']==payload.get('region_id')), None)
                if region is None or region.get('locked'):
                    raise ValueError('请选择未锁定的文字区域。')
                progress('恢复普通文字并匹配样式…', 10)
                image = np.asarray(Image.open(directory / f"{page['id']}.png").convert('RGB'))
                restore_plain_text(image, region)
                self._fit_page(dict(payload,kind='fit'),directory,page,progress)
            if kind in {"analyze", "fit"}:
                self._fit_page(payload, directory, page, progress)
            if kind in {"formula_recognize", "formula_fit"}:
                region = next((r for r in page["regions"] if r["id"] == payload.get("region_id")), None)
                if region is None or region.get("kind") != "formula" or region.get("locked"):
                    raise ValueError("请选择未锁定的公式区域。")
                image = np.asarray(Image.open(directory / f"{page['id']}.png").convert("RGB"))
                if kind == "formula_recognize":
                    progress("正在本机识别公式结构…", 20)
                    region.update(latex=recognize_formula(image, region), enabled=False)
                progress("正在匹配公式尺寸和位置…", 70)
                region.update(fit_formula(image, region))
            if kind == "export":
                scope, format = payload.get("scope", "all"), payload.get("format", "pptx")
                target = export_pages(directory, project, scope=scope, format=format,
                                      page_id=payload.get("page_id"), progress=progress)
                exported = project["pages"] if scope == "all" else [page]
                for item in exported if format != "json" else []:
                    item["render_revision"] = project["revision"] + 1
                if payload["_destination"]:
                    saved_path = save_export(target, payload["_destination"], progress)
                    self.job["saved_path"] = str(saved_path)
                    try:
                        remember_directory(self.store.root, saved_path.parent)
                    except OSError:
                        pass  # A preference failure must not invalidate a successful export.
                else:
                    self.job["download"] = f"/asset?project={project['id']}&file={target.name}&download=1"
            else:
                progress("正在生成预览…", 94)
                render_page(directory, page)
                page["render_revision"] = project["revision"] + 1
            if not self.job.get("saved_path"):
                progress("完成", 100)
            with self.lock:
                project["revision"] += 1
                self.store.save(project)
                message = (f"已导出 {len(exported)} 页 · {format.upper()}" if kind == "export"
                           else "处理完成，请检查文字内容和样式。")
                self.job.update(active=False, status="done", progress=100, message=message)
        except InterruptedError as exc:
            with self.lock:
                self.job.update(active=False, status="cancelled", message=str(exc))
        except Exception as exc:
            traceback.print_exc()
            with self.lock:
                message = f"文件操作失败，请检查文件夹是否可用及写入权限：{exc}" if isinstance(exc, OSError) else str(exc)
                self.job.update(active=False, status="error", message=message)

    def _fit_page(self, payload, directory, page, progress):
        image = np.asarray(Image.open(directory / f"{page['id']}.png").convert("RGB"))
        if payload["kind"] == "analyze":
            page["regions"] = detect_regions(directory / f"{page['id']}.png", progress)
            formulas = [r for r in page["regions"] if r.get("kind") == "formula"]
            for index, region in enumerate(formulas):
                if region.get('type_decision'):
                    continue  # Both candidates were already checked during detection.
                progress(f"识别公式 {index+1}/{len(formulas)} · 暂保留原图供核对", 5)
                try:
                    region["latex"] = recognize_formula(image, region)
                    region.update(fit_formula(image, region))
                except ValueError as exc:
                    region.update(enabled=False, fit_status="preserved", fit_note=str(exc))
                    self.job["warnings"].append(f"{page['name']} · 公式：{exc}")
        selected = [r for r in page["regions"] if r.get("kind") != "formula" and r.get("enabled", True) and not r.get("locked")
                    and (not payload.get("region_id") or r["id"] == payload["region_id"])]
        for idx, region in enumerate(selected):
            percent = 10 + idx / max(1, len(selected)) * 80
            progress(f"拟合文字 {idx+1}/{len(selected)} · {region['text'][:25]}", percent)
            try:
                if not (payload['kind']=='analyze' and region.get('type_decision',{}).get('choice')=='text'):
                    region.update(fit_region(image, region, payload.get("font_ids"),
                        lambda msg: progress(f"{idx+1}/{len(selected)} · {msg}", percent)))
                if region.get("enabled") and region.get("color_source") != "manual":
                    try:
                        region.update(recover_colors(image, region))
                    except ValueError:
                        pass  # Color recovery must not invalidate a usable monochrome fit.
            except ValueError as exc:
                region.update(enabled=False, fit_status="preserved", fit_note=str(exc))
                self.job["warnings"].append(f"{page['name']} · {region['text'][:20]}：{exc}")
        if payload['kind'] == 'analyze':
            progress('校正文字对齐…', 92)
            align_page(image, page['regions'])
        if not page["regions"]:
            self.job["warnings"].append(f"{page['name']}：未检测到文字，原图已保留。")
        page["status"] = "review"
        page.pop("error", None)
        if payload["kind"] == "analyze":
            page.pop("pending_rescan", None)


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, app, **kwargs):
        self.app = app
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        pass

    def send_data(self, content, mime="application/json; charset=utf-8", status=200, download=None):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in {"/", "/app.js", "/canvas-geometry.js", "/review.js", "/color-runs.js", "/batch-style.js", "/app.css", "/icon.svg"}:
                name = "index.html" if url.path == "/" else url.path[1:]
                mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                        "canvas-geometry.js": "text/javascript; charset=utf-8", "review.js": "text/javascript; charset=utf-8", "color-runs.js": "text/javascript; charset=utf-8",
                        "batch-style.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8", "icon.svg": "image/svg+xml"}[name]
                self.send_data((WEB / name).read_bytes(), mime)
            elif url.path == "/api/boot":
                self.send_data({"token": self.app.token, "version": "0.4.0", "projects": self.app.store.listing(),
                                "fonts": [{k: v for k, v in f.items() if k not in {"path", "index"}} for f in font_catalog().values()],
                                "data_dir": str(self.app.store.root), "formula_detection": formula_available(),
                                "export_directory": default_export_directory(self.app.store.root)})
            elif url.path == "/api/project":
                self.send_data(self.app.store.load(query["id"]))
            elif url.path == "/api/job":
                with self.app.lock:
                    self.send_data(dict(self.app.job))
            elif url.path == "/asset":
                name = query.get("file", "")
                if not re.fullmatch(r"(?:[0-9a-f]{12}(?:-result)?\.(?:png|svg)|export(?:-page)?\.pptx|export-(?:svg|png)\.zip|project\.json)", name):
                    raise ValueError("无效文件名。")
                path = self.app.store.directory(query["project"]) / name
                self.send_data(path.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream",
                               download=name if query.get("download") else None)
            else:
                self.send_data({"error": "Not found"}, status=404)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self.send_data({"error": str(exc)}, status=400)
        except Exception as exc:
            traceback.print_exc()
            self.send_data({"error": str(exc)}, status=500)

    def do_POST(self):
        try:
            if self.headers.get("X-Studio-Token") != self.app.token:
                self.send_data({"error": "请刷新应用后重试。"}, status=403)
                return
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 128_000_000:
                raise ValueError("上传内容为空或超过 128 MB。")
            raw = self.rfile.read(length)
            path = urlparse(self.path).path
            if path == "/api/import":
                with self.app.lock:
                    self.app.ensure_idle()
                    filename = Path(unquote(self.headers.get("X-Filename", "image.png"))).name
                    images = image_inputs(raw, filename)
                    query = parse_qs(urlparse(self.path).query)
                    existing = query.get("project", [None])[0]
                    project = self.app.store.load(existing) if existing else self.app.store.create(Path(filename).stem)
                    self.send_data(self.app.store.add_images(project, images))
                return
            data = json.loads(raw)
            if path == "/api/workspaces":
                with self.app.lock:
                    self.send_data({"projects": self.app.store.listing(), "trash": self.app.store.listing(trashed=True)})
            elif path in {"/api/workspace/trash", "/api/workspace/restore"}:
                with self.app.lock:
                    self.app.ensure_idle()
                    if path.endswith("/trash"):
                        self.app.store.trash(data["id"], data.get("revision"))
                    else:
                        self.app.store.restore(data["id"])
                    self.send_data({"ok": True})
            elif path == "/api/folders":
                self.send_data(directory_contents(data.get("path") or default_export_directory(self.app.store.root)))
            elif path == "/api/demo":
                with self.app.lock:
                    self.app.ensure_idle()
                    project = self.app.store.create("文字重绘 · 示例")
                    self.send_data(self.app.store.add_images(project, [("示例：中英文与不同字重", make_demo())]))
            elif path == "/api/preview":
                with self.app.lock:
                    project = self.app.store.load(data["project_id"])
                    page = next((p for p in project["pages"] if p["id"] == data["page_id"]), None)
                    if page is None:
                        raise ValueError("页面不存在。")
                    page["regions"] = data["regions"]
                svg = compose_page(self.app.store.directory(project["id"]), page)
                self.send_data({"svg": svg, "regions": [
                    {"id": r["id"], "ink_width": r.get("ink_width", 0), "ink_height": r.get("ink_height", 0)}
                    for r in page["regions"]]})
            elif path == "/api/save":
                with self.app.lock:
                    self.app.ensure_idle()
                    project = self.app.store.load(data["id"])
                    if data.get("revision") != project["revision"]:
                        raise RuntimeError("另一个窗口已修改项目，请刷新后继续。")
                    incoming = data["pages"]
                    if [p["id"] for p in incoming] != [p["id"] for p in project["pages"]]:
                        raise ValueError("不能通过保存更改页面结构。")
                    for page, changed in zip(project["pages"], incoming):
                        validate_regions(changed["regions"], page["width"], page["height"])
                        if page["regions"] != changed["regions"]:
                            page["render_revision"] = -1
                        page["regions"] = changed["regions"]
                    project["revision"] += 1
                    self.app.store.save(project)
                    self.send_data(project)
            elif path == "/api/job":
                self.send_data(self.app.start_job(data))
            elif path == "/api/cancel":
                self.app.cancelled.set()
                self.send_data({"ok": True})
            else:
                self.send_data({"error": "Not found"}, status=404)
        except RuntimeError as exc:
            self.send_data({"error": str(exc)}, status=409)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self.send_data({"error": str(exc)}, status=400)
        except OSError as exc:
            self.send_data({"error": f"无法访问文件夹，请检查路径和权限：{exc}"}, status=400)
        except Exception as exc:
            traceback.print_exc()
            self.send_data({"error": str(exc)}, status=500)


def create_server(root=None, port=8766):
    app = Studio(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, app=app))
    server.app = app
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="AI Text Sharpener Studio · 本地文字重绘")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    server = create_server(args.data_dir, args.port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"AI Text Sharpener Studio: {url}", flush=True)
    print(f"Projects: {server.app.store.root}", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app.cancelled.set()
        server.shutdown()
        server.server_close()
        server.app.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
