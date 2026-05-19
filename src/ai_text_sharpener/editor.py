"""Local browser editor for review JSON files."""
from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .fonts import FontSpec, discover_grouped_fonts, list_user_fonts
from .pipeline import (
    analyze_image,
    auto_align_left_groups,
    fit_font_sizes_to_bboxes,
    render_review_document,
)
from .ppt_export import export_project_to_pptx
from .style import bbox_to_rect
from .project import (
    ReviewProjectItem,
    load_review_project,
    resolve_project_path,
)
from .review import ReviewDocument, load_review_document, write_review_document


EDITOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Text Sharpener Review</title>
  <style>
    :root {
      --bg: #f6f4ef;
      --panel: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #d8d3c6;
      --accent: #0b5cab;
      --accent-2: #b7791f;
      --danger: #b91c1c;
      --off: #737373;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      height: 100vh;
      overflow: hidden;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
      letter-spacing: 0;
    }

    .shell {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr) 380px;
      height: 100vh;
    }

    .slides {
      display: grid;
      grid-template-rows: 52px minmax(0, 1fr);
      min-width: 0;
      border-right: 1px solid var(--line);
      background: #fbfaf7;
    }

    .stage {
      display: grid;
      grid-template-rows: 52px minmax(0, 1fr);
      min-width: 0;
      border-right: 1px solid var(--line);
    }

    .toolbar,
    .inspector-head {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfaf7;
    }

    .toolbar h1 {
      margin: 0;
      font-size: 16px;
      line-height: 1;
      font-weight: 700;
    }

    .toolbar .spacer { flex: 1; }

    .slides-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }

    .slides-head h2 {
      margin: 0;
      font-size: 15px;
      line-height: 1;
    }

    .slide-list {
      overflow: auto;
    }

    .slide-row {
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      width: 100%;
      padding: 9px 12px;
      border: 0;
      border-bottom: 1px solid #ebe7dc;
      border-radius: 0;
      text-align: left;
      background: transparent;
    }

    .slide-row.active { background: #e9f2ff; }
    .slide-no { color: var(--muted); font-size: 12px; font-weight: 700; }
    .slide-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    button {
      min-height: 32px;
      padding: 0 12px;
      border: 1px solid #a8b3c4;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      font: inherit;
      cursor: pointer;
    }

    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    button:disabled {
      cursor: default;
      opacity: 0.55;
    }

    .status {
      min-width: 160px;
      color: var(--muted);
      font-size: 13px;
      text-align: right;
      white-space: nowrap;
    }

    .canvas-wrap {
      position: relative;
      min-height: 0;
      overflow: hidden;
      padding: 14px;
    }

    canvas {
      display: block;
      width: 100%;
      height: 100%;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .inspector {
      display: grid;
      grid-template-rows: 52px minmax(60px, 180px) minmax(0, 1fr);
      min-width: 0;
      min-height: 0;
      background: var(--panel);
    }

    .inspector-head {
      justify-content: space-between;
    }

    .inspector-head h2 {
      margin: 0;
      font-size: 15px;
      line-height: 1;
    }

    .region-list {
      overflow: auto;
      border-bottom: 1px solid var(--line);
      background: #fbfaf7;
    }

    .region-row {
      display: grid;
      grid-template-columns: 50px minmax(0, 1fr) 52px;
      gap: 8px;
      align-items: center;
      width: 100%;
      padding: 8px 12px;
      border: 0;
      border-bottom: 1px solid #ebe7dc;
      border-radius: 0;
      text-align: left;
      background: transparent;
    }

    .region-row.active { background: #e9f2ff; }
    .region-row.co-active { background: #fff2d6; }
    .region-row.off { color: var(--off); }
    .region-id { font-size: 12px; font-weight: 700; }
    .region-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .region-state { font-size: 12px; color: var(--muted); text-align: right; }

    .form {
      overflow-y: auto;
      min-height: 0;
      padding: 14px;
    }

    .field {
      margin-bottom: 12px;
    }

    label {
      display: block;
      margin-bottom: 5px;
      color: #334155;
      font-size: 12px;
      font-weight: 700;
    }

    input,
    textarea,
    select {
      width: 100%;
      min-height: 34px;
      border: 1px solid #b8c0cf;
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--ink);
      background: #ffffff;
      font: inherit;
    }

    textarea {
      min-height: 86px;
      resize: vertical;
      line-height: 1.35;
    }

    input[type="checkbox"] {
      width: 18px;
      min-height: 18px;
    }

    input[type="color"] {
      padding: 2px;
    }

    .check-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 14px;
    }

    .check-row label {
      margin: 0;
      font-size: 13px;
      font-weight: 700;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .meta {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      word-break: break-word;
    }

    .spans-section {
      margin-top: 14px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }

    .spans-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
    }

    .spans-head > label {
      margin: 0;
      font-size: 12px;
      font-weight: 700;
      color: #334155;
    }

    .spans-head > div { display: flex; gap: 6px; }

    .span-row {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      margin-bottom: 8px;
      background: #f8f7f4;
    }

    .span-row-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }

    .span-idx { font-size: 11px; font-weight: 700; color: var(--muted); }

    .span-grid {
      display: grid;
      grid-template-columns: 1fr 38px 72px 80px 28px;
      gap: 6px;
      align-items: end;
    }

    .span-grid .field { margin: 0; }
    .span-grid label { font-size: 11px; }

    .ctx-menu {
      position: fixed;
      z-index: 100;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.18);
      padding: 4px;
      min-width: 200px;
      display: none;
    }
    .ctx-menu.show { display: block; }
    .ctx-item {
      display: block;
      width: 100%;
      text-align: left;
      padding: 6px 10px;
      border: 0;
      background: none;
      font-size: 13px;
      cursor: pointer;
      border-radius: 4px;
    }
    .ctx-item:hover { background: #f0f4f8; }
    .ctx-sep { border-top: 1px solid var(--line); margin: 4px 0; }

    .color-row { display: flex; gap: 4px; align-items: stretch; }
    .color-row input[type=color] { flex: 1; min-width: 0; }
    .span-grid input[type="color"] { min-height: 34px; }

    button.sm {
      min-height: 28px;
      padding: 0 8px;
      font-size: 13px;
    }

    .align-bar {
      position: absolute;
      top: 8px; left: 50%;
      transform: translateX(-50%);
      z-index: 5;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.10);
      padding: 4px;
      display: none;
      gap: 2px;
      align-items: center;
    }
    .align-bar.show { display: flex; }
    .align-bar button {
      min-height: 28px;
      min-width: 32px;
      padding: 0 6px;
      font-size: 14px;
      background: none;
      border: 0;
      border-radius: 4px;
      cursor: pointer;
    }
    .align-bar button:hover { background: #f0f4f8; }
    .align-bar .sep { width: 1px; height: 20px; background: var(--line); margin: 0 4px; }
    .align-bar .count { font-size: 12px; color: var(--muted); padding: 0 6px; }

    @media (max-width: 980px) {
      body { overflow: auto; }
      .shell {
        grid-template-columns: 1fr;
        grid-template-rows: 180px minmax(480px, 60vh) minmax(520px, auto);
        min-height: 100vh;
      }
      .slides { border-right: 0; border-bottom: 1px solid var(--line); }
      .stage { border-right: 0; border-bottom: 1px solid var(--line); }
      .inspector { grid-template-rows: 52px 180px minmax(360px, auto); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <nav class="slides">
      <div class="slides-head">
        <h2>Slides</h2>
        <span id="slideCount" class="meta">0</span>
      </div>
      <div id="slideList" class="slide-list"></div>
    </nav>

    <main class="stage">
      <div class="toolbar">
        <h1>AI Text Sharpener Review</h1>
        <div class="spacer"></div>
        <button id="fitBtn" type="button">Fit</button>
        <button id="viewBtn" type="button" title="Toggle canvas backdrop between original image and rendered output">View: Source</button>
        <button id="previewBtn" type="button" title="Show replacement preview for all replace-on regions vs only the selected one">Preview: All</button>
        <button id="redetectBtn" type="button" title="Re-run OCR and add missed text regions (keeps current edits)">Re-detect</button>
        <button id="fitSizesBtn" type="button" title="Shrink any region's font-size that overflows its bbox">Fit sizes</button>
        <button id="saveBtn" class="primary" type="button">Save</button>
        <button id="renderBtn" type="button">Render</button>
        <button id="exportPptBtn" type="button" title="Export the whole project as a flat-image PPTX">Export PPT</button>
        <div id="status" class="status">Loading</div>
      </div>
      <div class="canvas-wrap" id="canvasWrap">
        <canvas id="canvas"></canvas>
        <div id="alignBar" class="align-bar" role="toolbar" aria-label="Alignment">
          <span class="count" id="alignCount">0 selected</span>
          <span class="sep"></span>
          <button data-align="left" type="button" title="Align left (min X)">⇤</button>
          <button data-align="hcenter" type="button" title="Align horizontal center (avg X)">↔</button>
          <button data-align="right" type="button" title="Align right (max X)">⇥</button>
          <span class="sep"></span>
          <button data-align="top" type="button" title="Align top (min Y)">⤒</button>
          <button data-align="vcenter" type="button" title="Align vertical middle (avg Y)">⇕</button>
          <button data-align="bottom" type="button" title="Align bottom (max Y)">⤓</button>
          <span class="sep"></span>
          <button data-align="dist-h" type="button" title="Distribute horizontally (≥3 needed)">↔↔</button>
          <button data-align="dist-v" type="button" title="Distribute vertically (≥3 needed)">⇕⇕</button>
        </div>
      </div>
    </main>

    <aside class="inspector">
      <div class="inspector-head">
        <h2>Regions</h2>
        <span id="count" class="meta">0</span>
      </div>
      <div id="regionList" class="region-list"></div>
      <form id="regionForm" class="form">
        <div class="check-row">
          <input id="replace" type="checkbox">
          <label for="replace">Replace</label>
        </div>

        <div class="field">
          <label for="text">Text</label>
          <textarea id="text"></textarea>
        </div>

        <div class="field">
          <label for="originalText">Original OCR</label>
          <textarea id="originalText" readonly></textarea>
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="x">X</label>
            <input id="x" type="number" step="1">
          </div>
          <div class="field">
            <label for="y">Y</label>
            <input id="y" type="number" step="1">
          </div>
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="fontSize">Font size</label>
            <input id="fontSize" type="number" min="1" step="1">
          </div>
          <div class="field">
            <label for="letterSpacing">Letter spacing</label>
            <input id="letterSpacing" type="number" step="0.1">
          </div>
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="fontWeight">Weight</label>
            <select id="fontWeight">
              <option value="normal">normal</option>
              <option value="bold">bold</option>
            </select>
          </div>
          <div class="field">
            <label for="textAnchor">Anchor</label>
            <select id="textAnchor" title="X is interpreted as: center / left edge / right edge of the text">
              <option value="center">center</option>
              <option value="left">left</option>
              <option value="right">right</option>
            </select>
          </div>
        </div>

        <div class="field">
          <label for="fontFamily">Font family</label>
          <select id="fontFamilyPick">
            <option value="">— pick —</option>
          </select>
          <input id="fontFamily" type="text" placeholder="or type a font name" autocomplete="off">
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="color">Color</label>
            <div class="color-row">
              <input id="color" type="color">
              <button id="colorPickerBtn" type="button" class="sm" title="Eyedropper: pick a color from the screen / canvas">💧</button>
            </div>
          </div>
          <div class="field">
            <label for="confidence">Confidence</label>
            <input id="confidence" type="text" readonly>
          </div>
        </div>

        <div id="regionMeta" class="meta"></div>

        <div class="spans-section">
          <div class="spans-head">
            <label>Inline Spans</label>
            <div>
              <button type="button" id="spansInitBtn" class="sm" title="Convert text to one editable span">Split</button>
              <button type="button" id="spansAddBtn" class="sm" title="Add a new span">+ Span</button>
              <button type="button" id="spansClearBtn" class="sm" title="Remove all spans">Clear</button>
            </div>
          </div>
          <div id="spansList"></div>
        </div>
      </form>
    </aside>
  </div>

  <div id="ctxMenu" class="ctx-menu" role="menu">
    <button class="ctx-item" data-action="super" type="button">Superscript &nbsp; x²</button>
    <button class="ctx-item" data-action="sub" type="button">Subscript &nbsp; x₂</button>
    <button class="ctx-item" data-action="baseline" type="button">Baseline (clear sup/sub)</button>
    <div class="ctx-sep"></div>
    <button class="ctx-item" data-action="bold" type="button">Toggle Bold</button>
    <button class="ctx-item" data-action="color" type="button">Color…</button>
    <button class="ctx-item" data-action="eyedrop" type="button">Eyedropper 💧 from screen</button>
    <button class="ctx-item" data-action="size" type="button">Font size…</button>
    <div class="ctx-sep"></div>
    <button class="ctx-item" data-action="clear-format" type="button">Clear formatting</button>
  </div>
  <input id="ctxColorPicker" type="color" style="position:fixed;left:-9999px;top:-9999px">

  <script>
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const wrap = document.getElementById('canvasWrap');
    const statusEl = document.getElementById('status');
    const slideListEl = document.getElementById('slideList');
    const slideCountEl = document.getElementById('slideCount');
    const listEl = document.getElementById('regionList');
    const countEl = document.getElementById('count');
    const renderBtn = document.getElementById('renderBtn');
    const fields = {
      replace: document.getElementById('replace'),
      text: document.getElementById('text'),
      originalText: document.getElementById('originalText'),
      x: document.getElementById('x'),
      y: document.getElementById('y'),
      fontSize: document.getElementById('fontSize'),
      letterSpacing: document.getElementById('letterSpacing'),
      fontWeight: document.getElementById('fontWeight'),
      textAnchor: document.getElementById('textAnchor'),
      fontFamily: document.getElementById('fontFamily'),
      color: document.getElementById('color'),
      confidence: document.getElementById('confidence'),
      meta: document.getElementById('regionMeta'),
    };

    let state = null;
    let image = new Image();
    let activeSlideId = null;
    let selectedId = null;
    let selectedIds = new Set();
    let marquee = null;
    let scale = 1;
    let offsetX = 0;
    let offsetY = 0;
    let dragging = false;
    let dragStartPositions = null;
    let dragStartPoint = null;
    let viewMode = 'source';
    let previewMode = 'all';
    let snapGuides = [];
    const undoStacks = {};
    const redoStacks = {};
    let lastHistoryTime = 0;
    let lastHistoryKey = null;
    let autoRenderTimer = null;
    let autoRenderInFlight = false;
    let autoRenderPending = false;
    const AUTO_RENDER_DELAY_MS = 800;

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function withSlide(path) {
      if (!activeSlideId) return path;
      const separator = path.includes('?') ? '&' : '?';
      return `${path}${separator}slide=${encodeURIComponent(activeSlideId)}`;
    }

    function withCacheBust(path) {
      const separator = path.includes('?') ? '&' : '?';
      return `${path}${separator}t=${Date.now()}`;
    }

    function imagePath() {
      return viewMode === 'rendered' ? '/image-rendered' : '/image';
    }

    function updateViewBtnLabel() {
      const btn = document.getElementById('viewBtn');
      if (btn) btn.textContent = viewMode === 'rendered' ? 'View: Rendered' : 'View: Source';
    }

    function reloadBackdrop() {
      const newImage = new Image();
      newImage.onload = () => {
        image = newImage;
        fitCanvas();
      };
      newImage.onerror = () => {
        if (viewMode === 'rendered') {
          setStatus('No rendered PNG yet — Render first');
          viewMode = 'source';
          updateViewBtnLabel();
          reloadBackdrop();
        } else {
          setStatus('Failed to load image');
        }
      };
      newImage.src = withCacheBust(withSlide(imagePath()));
    }

    function rgbToHex(rgb) {
      return '#' + rgb.map(v => Math.max(0, Math.min(255, Number(v)))
        .toString(16).padStart(2, '0')).join('');
    }

    function hexToRgb(hex) {
      const v = hex.replace('#', '');
      return [
        parseInt(v.slice(0, 2), 16),
        parseInt(v.slice(2, 4), 16),
        parseInt(v.slice(4, 6), 16),
      ];
    }

    function selectedRegion() {
      if (!state || !selectedId) return null;
      return state.regions.find(r => r.id === selectedId) || null;
    }

    function rectFor(region) {
      const xs = region.bbox.map(p => p[0]);
      const ys = region.bbox.map(p => p[1]);
      const x0 = Math.min(...xs);
      const y0 = Math.min(...ys);
      const x1 = Math.max(...xs);
      const y1 = Math.max(...ys);
      return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    }

    function imagePoint(evt) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (evt.clientX - rect.left - offsetX) / scale,
        y: (evt.clientY - rect.top - offsetY) / scale,
      };
    }

    function _historyStacks() {
      if (!activeSlideId) return null;
      if (!undoStacks[activeSlideId]) undoStacks[activeSlideId] = [];
      if (!redoStacks[activeSlideId]) redoStacks[activeSlideId] = [];
      return { undo: undoStacks[activeSlideId], redo: redoStacks[activeSlideId] };
    }

    function pushHistory(key) {
      const stacks = _historyStacks();
      if (!stacks || !state) return;
      const now = Date.now();
      if (key && key === lastHistoryKey && now - lastHistoryTime < 500) {
        lastHistoryTime = now;
        return;
      }
      stacks.undo.push(JSON.stringify(state.regions));
      if (stacks.undo.length > 100) stacks.undo.shift();
      stacks.redo.length = 0;
      lastHistoryTime = now;
      lastHistoryKey = key;
    }

    function applySnapshot(json) {
      state.regions = JSON.parse(json);
      renderList();
      if (selectedId && !state.regions.find(r => r.id === selectedId)) {
        selectedId = state.regions[0] ? state.regions[0].id : null;
      }
      if (selectedId) selectRegion(selectedId);
      else renderSpans();
      draw();
    }

    function undo() {
      const stacks = _historyStacks();
      if (!stacks || !stacks.undo.length) { setStatus('Nothing to undo'); return; }
      stacks.redo.push(JSON.stringify(state.regions));
      applySnapshot(stacks.undo.pop());
      lastHistoryTime = 0; lastHistoryKey = null;
      setStatus('Undone');
      scheduleAutoRender();
    }

    function redo() {
      const stacks = _historyStacks();
      if (!stacks || !stacks.redo.length) { setStatus('Nothing to redo'); return; }
      stacks.undo.push(JSON.stringify(state.regions));
      applySnapshot(stacks.redo.pop());
      lastHistoryTime = 0; lastHistoryKey = null;
      setStatus('Redone');
      scheduleAutoRender();
    }

    function snapPoint(x, y, excludeId, disable) {
      snapGuides = [];
      if (disable || !state || !image.width) return { x, y };
      const threshold = 8 / scale;
      const xCands = [image.width / 2];
      const yCands = [image.height / 2];
      for (const r of state.regions) {
        if (r.id === excludeId) continue;
        xCands.push(r.x);
        yCands.push(r.y);
      }
      let snapX = x, snapY = y;
      let bestX = threshold, bestY = threshold;
      for (const cx of xCands) {
        const d = Math.abs(cx - x);
        if (d < bestX) { bestX = d; snapX = cx; }
      }
      for (const cy of yCands) {
        const d = Math.abs(cy - y);
        if (d < bestY) { bestY = d; snapY = cy; }
      }
      if (snapX !== x) snapGuides.push({ orientation: 'v', value: snapX });
      if (snapY !== y) snapGuides.push({ orientation: 'h', value: snapY });
      return { x: snapX, y: snapY };
    }

    function hitTest(x, y) {
      if (!state) return null;
      const hits = state.regions.filter(region => {
        const r = rectFor(region);
        return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
      });
      hits.sort((a, b) => {
        const ra = rectFor(a);
        const rb = rectFor(b);
        return (ra.w * ra.h) - (rb.w * rb.h);
      });
      return hits[0] || null;
    }

    function fitCanvas() {
      const dpr = window.devicePixelRatio || 1;
      const box = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(box.width * dpr));
      canvas.height = Math.max(1, Math.floor(box.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const availableW = Math.max(1, box.width);
      const availableH = Math.max(1, box.height);
      scale = Math.min(availableW / image.width, availableH / image.height);
      offsetX = (availableW - image.width * scale) / 2;
      offsetY = (availableH - image.height * scale) / 2;
      draw();
    }

    function drawRegionText(region) {
      const baseSize = region.font_size_px;
      const baseWeight = region.font_weight || 'normal';
      const family = region.font_family || 'Arial';
      const baseColor = `rgb(${region.color[0]}, ${region.color[1]}, ${region.color[2]})`;
      const x = offsetX + region.x * scale;
      const y = offsetY + region.y * scale;
      const spacing = Number(region.letter_spacing_px || 0) * scale;

      const rawSpans = region.spans && region.spans.length
        ? region.spans
        : [{ text: region.text, color: null, font_size_px: null, font_weight: null }];

      const segments = [];
      let totalWidth = 0;
      let totalChars = 0;
      for (const span of rawSpans) {
        const chars = Array.from(span.text || '');
        if (!chars.length) continue;
        const va = span.vertical_align;
        let rawSize;
        if (span.font_size_px != null) rawSize = span.font_size_px;
        else if (va === 'super' || va === 'sub') rawSize = Math.max(8, Math.round(baseSize * 0.65));
        else rawSize = baseSize;
        const size = Math.max(8, rawSize * scale);
        const yOffset = va === 'super' ? -size * 0.4 : va === 'sub' ? size * 0.2 : 0;
        const weight = span.font_weight || baseWeight;
        const color = span.color ? `rgb(${span.color[0]}, ${span.color[1]}, ${span.color[2]})` : baseColor;
        ctx.font = `${weight} ${size}px ${family}`;
        const widths = chars.map(c => ctx.measureText(c).width);
        const segW = widths.reduce((a, b) => a + b, 0);
        segments.push({ chars, widths, size, weight, color, yOffset });
        totalWidth += segW;
        totalChars += chars.length;
      }
      if (!segments.length) return;
      totalWidth += spacing * Math.max(0, totalChars - 1);

      ctx.save();
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      const anchor = region.text_anchor || 'center';
      let cursor;
      if (anchor === 'left') cursor = x;
      else if (anchor === 'right') cursor = x - totalWidth;
      else cursor = x - totalWidth / 2;
      for (const seg of segments) {
        ctx.font = `${seg.weight} ${seg.size}px ${family}`;
        ctx.fillStyle = seg.color;
        const sy = y + (seg.yOffset || 0);
        for (let i = 0; i < seg.chars.length; i += 1) {
          ctx.fillText(seg.chars[i], cursor, sy);
          cursor += seg.widths[i] + spacing;
        }
      }
      ctx.restore();
    }

    function draw() {
      if (!state || !image.complete) return;
      if (typeof updateAlignBar === 'function') updateAlignBar();
      const { width: cw, height: ch } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, cw, ch);
      ctx.drawImage(image, offsetX, offsetY, image.width * scale, image.height * scale);

      for (const region of state.regions) {
        const r = rectFor(region);
        const primary = region.id === selectedId;
        const inSelection = selectedIds.has(region.id);
        const selected = primary || inSelection;
        ctx.save();
        ctx.lineWidth = primary ? 3 : (inSelection ? 2.4 : 1.5);
        ctx.strokeStyle = primary ? '#b7791f' : (inSelection ? '#d49a3a' : (region.replace ? '#0b5cab' : '#737373'));
        ctx.fillStyle = inSelection ? 'rgba(183, 121, 31, 0.12)' : (region.replace ? 'rgba(11, 92, 171, 0.08)' : 'rgba(115, 115, 115, 0.10)');
        ctx.strokeRect(offsetX + r.x * scale, offsetY + r.y * scale, r.w * scale, r.h * scale);
        ctx.fillRect(offsetX + r.x * scale, offsetY + r.y * scale, r.w * scale, r.h * scale);
        ctx.restore();

        const showPreview = region.replace && (previewMode === 'all' || selected);
        if (showPreview) {
          if (viewMode === 'source') {
            const bg = region.background || [255, 255, 255];
            ctx.save();
            ctx.fillStyle = `rgba(${bg[0]}, ${bg[1]}, ${bg[2]}, 0.78)`;
            ctx.fillRect(offsetX + r.x * scale, offsetY + r.y * scale, r.w * scale, r.h * scale);
            ctx.restore();
          }
          drawRegionText(region);
        }
      }

      if (marquee && (marquee.w > 0 || marquee.h > 0)) {
        ctx.save();
        ctx.strokeStyle = '#b7791f';
        ctx.fillStyle = 'rgba(183, 121, 31, 0.10)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        const mx = offsetX + marquee.x * scale;
        const my = offsetY + marquee.y * scale;
        const mw = marquee.w * scale;
        const mh = marquee.h * scale;
        ctx.fillRect(mx, my, mw, mh);
        ctx.strokeRect(mx, my, mw, mh);
        ctx.restore();
      }

      if (snapGuides.length) {
        ctx.save();
        ctx.strokeStyle = '#e07b00';
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 4]);
        for (const g of snapGuides) {
          ctx.beginPath();
          if (g.orientation === 'v') {
            const px = offsetX + g.value * scale;
            ctx.moveTo(px, offsetY);
            ctx.lineTo(px, offsetY + image.height * scale);
          } else {
            const py = offsetY + g.value * scale;
            ctx.moveTo(offsetX, py);
            ctx.lineTo(offsetX + image.width * scale, py);
          }
          ctx.stroke();
        }
        ctx.restore();
      }
    }

    function renderSlides() {
      slideListEl.innerHTML = '';
      const slides = state.slides || [];
      slideCountEl.textContent = `${slides.length}`;
      for (let i = 0; i < slides.length; i += 1) {
        const slide = slides[i];
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'slide-row' + (slide.id === activeSlideId ? ' active' : '');
        row.innerHTML = `
          <span class="slide-no">${i + 1}</span>
          <span class="slide-name"></span>
        `;
        row.querySelector('.slide-name').textContent = slide.name || slide.id;
        row.addEventListener('click', async () => {
          if (slide.id === activeSlideId) return;
          await saveReview();
          await load(slide.id);
        });
        slideListEl.appendChild(row);
      }
    }

    function renderList() {
      listEl.innerHTML = '';
      countEl.textContent = `${state.regions.filter(r => r.replace).length}/${state.regions.length}`;
      for (const region of state.regions) {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'region-row' +
          (region.id === selectedId ? ' active' : '') +
          (selectedIds.has(region.id) && region.id !== selectedId ? ' co-active' : '') +
          (!region.replace ? ' off' : '');
        row.innerHTML = `
          <span class="region-id">${region.id}</span>
          <span class="region-text"></span>
          <span class="region-state">${region.replace ? 'on' : 'off'}</span>
        `;
        row.querySelector('.region-text').textContent = region.text || region.original_text || '';
        row.addEventListener('click', () => selectRegion(region.id));
        listEl.appendChild(row);
      }
    }

    function selectRegion(id) {
      selectedId = id;
      if (id && !selectedIds.has(id)) selectedIds = new Set([id]);
      else if (!id) selectedIds = new Set();
      const region = selectedRegion();
      if (!region) return;
      fields.replace.checked = Boolean(region.replace);
      fields.text.value = region.text || '';
      fields.originalText.value = region.original_text || '';
      fields.x.value = region.x;
      fields.y.value = region.y;
      fields.fontSize.value = region.font_size_px;
      fields.letterSpacing.value = Number(region.letter_spacing_px || 0);
      fields.fontWeight.value = region.font_weight || 'normal';
      fields.textAnchor.value = region.text_anchor || 'center';
      fields.fontFamily.value = region.font_family || '';
      const pick = document.getElementById('fontFamilyPick');
      if (pick) pick.value = [...pick.options].some(o => o.value === fields.fontFamily.value) ? fields.fontFamily.value : '';
      fields.color.value = rgbToHex(region.color || [0, 0, 0]);
      fields.confidence.value = Number(region.confidence || 0).toFixed(3);
      const r = rectFor(region);
      const sel = selectedIds.size;
      fields.meta.textContent = sel > 1
        ? `${sel} regions selected — color / font / size / weight / anchor apply to all`
        : `bbox ${Math.round(r.x)}, ${Math.round(r.y)}, ${Math.round(r.w)} x ${Math.round(r.h)}`;
      const spansSection = document.querySelector('.spans-section');
      if (spansSection) spansSection.style.opacity = sel > 1 ? '0.4' : '';
      if (spansSection) spansSection.style.pointerEvents = sel > 1 ? 'none' : '';
      renderList();
      renderSpans();
      draw();
    }

    function syncSelected() {
      const primary = selectedRegion();
      if (!primary) return;
      const newAnchor = fields.textAnchor.value || 'center';
      const newSize = Math.max(1, Number(fields.fontSize.value || 1));
      const newSpacing = Number(fields.letterSpacing.value || 0);
      const newWeight = fields.fontWeight.value;
      const newFamily = fields.fontFamily.value;
      const newColor = hexToRgb(fields.color.value);
      const newReplace = fields.replace.checked;
      const isMulti = selectedIds.size > 1;
      const targets = isMulti
        ? state.regions.filter(r => selectedIds.has(r.id))
        : [primary];
      for (const region of targets) {
        region.replace = newReplace;
        region.font_size_px = newSize;
        region.letter_spacing_px = newSpacing;
        region.font_weight = newWeight;
        region.font_family = newFamily;
        region.color = newColor;
        if (newAnchor !== (region.text_anchor || 'center')) {
          const rct = rectFor(region);
          if (newAnchor === 'left') region.x = Math.round(rct.x);
          else if (newAnchor === 'right') region.x = Math.round(rct.x + rct.w);
          else region.x = Math.round(rct.x + rct.w / 2);
        }
        region.text_anchor = newAnchor;
      }
      // Per-region fields only apply to primary
      primary.text = fields.text.value;
      if (!isMulti) {
        primary.x = Number(fields.x.value || 0);
        primary.y = Number(fields.y.value || 0);
      } else {
        fields.x.value = primary.x;
        fields.y.value = primary.y;
      }
      renderList();
      draw();
    }

    async function saveReview() {
      setStatus('Saving');
      const res = await fetch(withSlide('/api/review'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(state),
      });
      if (!res.ok) {
        setStatus('Save failed');
        return;
      }
      setStatus('Saved');
    }

    async function _runAutoPath(endpoint, label) {
      if (autoRenderInFlight) { autoRenderPending = true; return; }
      autoRenderInFlight = true;
      setStatus(label + '...');
      try {
        const res = await fetch(withSlide(endpoint), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(state),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          setStatus(data.error || (label + ' failed'));
        } else {
          setStatus(label + ' done');
          if (endpoint === '/api/render' && viewMode === 'rendered') reloadBackdrop();
        }
      } catch (e) {
        setStatus(label + ' failed');
      } finally {
        autoRenderInFlight = false;
        if (autoRenderPending) {
          autoRenderPending = false;
          runAutoTask();
        }
      }
    }

    function runAutoSave() { return _runAutoPath('/api/review', 'Saving'); }
    function runAutoRender() { return _runAutoPath('/api/render', 'Rendering'); }
    function runAutoTask() {
      return viewMode === 'rendered' ? runAutoRender() : runAutoSave();
    }

    function scheduleAutoRender() {
      if (autoRenderTimer) clearTimeout(autoRenderTimer);
      autoRenderTimer = setTimeout(() => {
        autoRenderTimer = null;
        runAutoTask();
      }, AUTO_RENDER_DELAY_MS);
    }

    function markMutated(key) {
      pushHistory(key);
      scheduleAutoRender();
    }

    function renderOutput() {
      if (autoRenderTimer) { clearTimeout(autoRenderTimer); autoRenderTimer = null; }
      runAutoRender();
    }

    async function autofitSizes() {
      if (!state) return;
      setStatus('Fitting sizes');
      const res = await fetch(withSlide('/api/autofit'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(state),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setStatus(data.error || 'Fit failed'); return; }
      setStatus(`Fit sizes: ${data.changed} region(s) shrunk`);
      await load(activeSlideId);
    }

    async function redetect() {
      if (!state) return;
      if (!confirm('Re-run OCR on this slide and add any missed regions? (current edits are kept; takes a few seconds)')) return;
      setStatus('Re-detecting');
      const res = await fetch(withSlide('/api/redetect'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(state),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setStatus(data.error || 'Re-detect failed'); return; }
      setStatus(`Re-detect: +${data.added} regions (total ${data.total})`);
      await load(activeSlideId);
    }

    async function exportPpt() {
      setStatus('Exporting PPTX');
      const res = await fetch('/api/export-ppt', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setStatus(data.error || 'PPTX export failed');
        return;
      }
      setStatus(`PPTX -> ${data.output || 'done'}`);
    }

    async function loadFonts() {
      try {
        const res = await fetch('/api/fonts');
        if (!res.ok) return;
        const data = await res.json();
        const groups = data.system_groups || [];
        const user = data.user || [];
        let css = '';
        for (const f of user) {
          const url = '/fonts/' + encodeURIComponent(f.filename);
          css += `@font-face { font-family: "${f.family}"; src: url("${url}"); font-display: swap; }\n`;
        }
        if (css) {
          const style = document.createElement('style');
          style.textContent = css;
          document.head.appendChild(style);
        }
        const pick = document.getElementById('fontFamilyPick');
        while (pick.options.length > 1) pick.remove(1);
        const addGroup = (label, names) => {
          if (!names || !names.length) return;
          const grp = document.createElement('optgroup');
          grp.label = label;
          for (const n of names) {
            const opt = document.createElement('option');
            opt.value = n;
            opt.textContent = n;
            grp.appendChild(opt);
          }
          pick.appendChild(grp);
        };
        for (const g of groups) addGroup(g.label, g.names);
        addGroup('Imported', user.map(f => f.family));
        const fontsDirHint = data.fonts_dir
          ? `Drop .ttf/.otf/.ttc files in ${data.fonts_dir} then refresh to import more fonts.`
          : '';
        if (fontsDirHint) pick.title = fontsDirHint;
      } catch (e) {}
    }

    async function load(slideId = null) {
      if (autoRenderTimer) { clearTimeout(autoRenderTimer); autoRenderTimer = null; }
      autoRenderPending = false;
      const url = slideId ? `/api/state?slide=${encodeURIComponent(slideId)}` : '/api/state';
      const res = await fetch(url);
      state = await res.json();
      activeSlideId = state.active_slide_id || slideId;
      if (activeSlideId) {
        undoStacks[activeSlideId] = [];
        redoStacks[activeSlideId] = [];
      }
      lastHistoryTime = 0; lastHistoryKey = null;
      renderBtn.disabled = !state.output_png;
      image = new Image();
      image.onload = () => {
        selectedId = state.regions[0] ? state.regions[0].id : null;
        fitCanvas();
        renderSlides();
        renderList();
        if (selectedId) selectRegion(selectedId);
        setStatus('Ready');
      };
      image.src = withCacheBust(withSlide(imagePath()));
    }

    // ── Span management ──────────────────────────────────────────────────────

    const spansListEl = document.getElementById('spansList');
    const spansInitBtn = document.getElementById('spansInitBtn');
    const spansAddBtn = document.getElementById('spansAddBtn');
    const spansClearBtn = document.getElementById('spansClearBtn');

    function escHtml(str) {
      return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderSpans() {
      const region = selectedRegion();
      if (!region) { spansListEl.innerHTML = ''; return; }
      const spans = region.spans || [];
      const hasSpans = spans.length > 0;
      spansInitBtn.style.display = hasSpans ? 'none' : '';
      spansAddBtn.style.display = hasSpans ? '' : 'none';
      spansClearBtn.style.display = hasSpans ? '' : 'none';

      if (!hasSpans) {
        spansListEl.innerHTML = '<div class="meta" style="padding:4px 0">No spans — region uses single format above.</div>';
        return;
      }

      spansListEl.innerHTML = '';
      spans.forEach((span, i) => {
        const color = span.color ? rgbToHex(span.color) : rgbToHex(region.color || [0,0,0]);
        const size = span.font_size_px != null ? span.font_size_px : region.font_size_px;
        const weight = span.font_weight || '';
        const row = document.createElement('div');
        row.className = 'span-row';
        const va = span.vertical_align || '';
        row.innerHTML = `
          <div class="span-row-head">
            <span class="span-idx">Span ${i + 1}</span>
            <select class="sm" data-span="${i}" data-prop="vertical_align" title="Baseline / superscript / subscript (auto-shrinks to 65% when no explicit size)">
              <option value=""${!va ? ' selected' : ''}>baseline</option>
              <option value="super"${va === 'super' ? ' selected' : ''}>x²  super</option>
              <option value="sub"${va === 'sub' ? ' selected' : ''}>x₂  sub</option>
            </select>
            <button type="button" class="sm" data-del="${i}" title="Remove span">×</button>
          </div>
          <div class="span-grid">
            <div class="field">
              <label>Text</label>
              <textarea rows="2" style="min-height:0;resize:vertical" data-span="${i}" data-prop="text">${escHtml(span.text)}</textarea>
            </div>
            <div class="field">
              <label>Color</label>
              <input type="color" data-span="${i}" data-prop="color" value="${escHtml(color)}">
            </div>
            <div class="field">
              <label>Size px</label>
              <input type="number" min="1" step="1" data-span="${i}" data-prop="font_size_px" value="${size}">
            </div>
            <div class="field">
              <label>Weight</label>
              <select data-span="${i}" data-prop="font_weight">
                <option value=""${!weight ? ' selected' : ''}>(inherit)</option>
                <option value="normal"${weight === 'normal' ? ' selected' : ''}>normal</option>
                <option value="bold"${weight === 'bold' ? ' selected' : ''}>bold</option>
              </select>
            </div>
            <div></div>
          </div>`;
        spansListEl.appendChild(row);
      });
    }

    // ── Alignment toolbar ───────────────────────────────────────────────────

    const alignBarEl = document.getElementById('alignBar');
    const alignCountEl = document.getElementById('alignCount');

    function updateAlignBar() {
      const n = selectedIds.size;
      if (n >= 2) {
        alignCountEl.textContent = `${n} selected`;
        alignBarEl.classList.add('show');
      } else {
        alignBarEl.classList.remove('show');
      }
    }

    function applyAlignment(action) {
      if (selectedIds.size < 2) return;
      const targets = state.regions.filter(r => selectedIds.has(r.id));
      if (targets.length < 2) return;
      const xs = targets.map(r => r.x);
      const ys = targets.map(r => r.y);
      markMutated('align-' + action);
      if (action === 'left') { const m = Math.min(...xs); for (const r of targets) r.x = m; }
      else if (action === 'right') { const m = Math.max(...xs); for (const r of targets) r.x = m; }
      else if (action === 'hcenter') { const m = Math.round(xs.reduce((a,b)=>a+b,0)/xs.length); for (const r of targets) r.x = m; }
      else if (action === 'top') { const m = Math.min(...ys); for (const r of targets) r.y = m; }
      else if (action === 'bottom') { const m = Math.max(...ys); for (const r of targets) r.y = m; }
      else if (action === 'vcenter') { const m = Math.round(ys.reduce((a,b)=>a+b,0)/ys.length); for (const r of targets) r.y = m; }
      else if (action === 'dist-h' && targets.length >= 3) {
        const sorted = [...targets].sort((a, b) => a.x - b.x);
        const lo = sorted[0].x, hi = sorted[sorted.length - 1].x;
        const gap = (hi - lo) / (sorted.length - 1);
        sorted.forEach((r, i) => r.x = Math.round(lo + gap * i));
      }
      else if (action === 'dist-v' && targets.length >= 3) {
        const sorted = [...targets].sort((a, b) => a.y - b.y);
        const lo = sorted[0].y, hi = sorted[sorted.length - 1].y;
        const gap = (hi - lo) / (sorted.length - 1);
        sorted.forEach((r, i) => r.y = Math.round(lo + gap * i));
      }
      const primary = selectedRegion();
      if (primary) { fields.x.value = primary.x; fields.y.value = primary.y; }
      draw();
    }

    alignBarEl.addEventListener('click', (evt) => {
      const btn = evt.target.closest('[data-align]');
      if (btn) applyAlignment(btn.dataset.align);
    });

    // ── Eyedropper / color picker ───────────────────────────────────────────

    function _hexFromRgbArr(arr) {
      return '#' + arr.map(v => Math.max(0, Math.min(255, v|0)).toString(16).padStart(2, '0')).join('');
    }

    async function pickColor(callback) {
      if (window.EyeDropper) {
        try {
          const result = await new EyeDropper().open();
          callback(result.sRGBHex);
        } catch (e) { /* user cancelled */ }
        return;
      }
      setStatus('Click a pixel on the canvas to sample color (Esc to cancel)');
      const prevCursor = canvas.style.cursor;
      canvas.style.cursor = 'crosshair';
      const onPointer = (evt) => {
        evt.stopPropagation();
        evt.preventDefault();
        const p = imagePoint(evt);
        const ix = Math.max(0, Math.min(image.width - 1, Math.floor(p.x)));
        const iy = Math.max(0, Math.min(image.height - 1, Math.floor(p.y)));
        const tmp = document.createElement('canvas');
        tmp.width = 1; tmp.height = 1;
        try {
          tmp.getContext('2d').drawImage(image, -ix, -iy);
          const data = tmp.getContext('2d').getImageData(0, 0, 1, 1).data;
          cleanup();
          callback(_hexFromRgbArr([data[0], data[1], data[2]]));
        } catch (err) {
          cleanup();
          setStatus('Pixel sample failed: ' + err.message);
        }
      };
      const onKey = (evt) => {
        if (evt.key === 'Escape') { cleanup(); setStatus('Eyedropper cancelled'); }
      };
      const cleanup = () => {
        canvas.removeEventListener('pointerdown', onPointer, true);
        document.removeEventListener('keydown', onKey, true);
        canvas.style.cursor = prevCursor;
      };
      canvas.addEventListener('pointerdown', onPointer, true);
      document.addEventListener('keydown', onKey, true);
    }

    document.getElementById('colorPickerBtn').addEventListener('click', () => {
      pickColor((hex) => {
        fields.color.value = hex;
        fields.color.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });

    // ── Right-click rich formatting on the main Text field ──────────────────

    const ctxMenuEl = document.getElementById('ctxMenu');
    const ctxColorPicker = document.getElementById('ctxColorPicker');
    let ctxSelection = null;

    function _sameColor(a, b) {
      if (a === b) return true;
      if (!a || !b) return false;
      return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
    }
    function _sameSpanStyle(a, b) {
      return _sameColor(a.color, b.color)
        && a.font_size_px === b.font_size_px
        && a.font_weight === b.font_weight
        && a.vertical_align === b.vertical_align;
    }
    function _mergeAdjacent(spans) {
      const result = [];
      for (const s of spans) {
        const last = result[result.length - 1];
        if (last && _sameSpanStyle(last, s)) {
          last.text += s.text;
        } else {
          result.push({ ...s });
        }
      }
      return result;
    }
    function _ensureSpans(region) {
      if (!region.spans || !region.spans.length) {
        region.spans = [{
          text: region.text || '',
          color: null, font_size_px: null, font_weight: null, vertical_align: null,
        }];
      }
    }
    function _makeMutator(action, payload) {
      if (action === 'super') return s => { s.vertical_align = 'super'; };
      if (action === 'sub') return s => { s.vertical_align = 'sub'; };
      if (action === 'baseline') return s => { s.vertical_align = null; };
      if (action === 'bold') return s => { s.font_weight = s.font_weight === 'bold' ? null : 'bold'; };
      if (action === 'color') return s => { s.color = payload; };
      if (action === 'size') return s => { s.font_size_px = payload; };
      if (action === 'clear-format') return s => {
        s.color = null; s.font_size_px = null; s.font_weight = null; s.vertical_align = null;
      };
      return () => {};
    }
    function applyCharFormatting(action, payload) {
      if (!ctxSelection) return;
      const region = state.regions.find(r => r.id === ctxSelection.regionId);
      if (!region) return;
      const { start, end } = ctxSelection;
      if (start >= end) return;
      markMutated('rich-' + action);
      _ensureSpans(region);
      const mutator = _makeMutator(action, payload);
      const out = [];
      let idx = 0;
      for (const s of region.spans) {
        const sStart = idx, sEnd = idx + s.text.length;
        idx = sEnd;
        if (!s.text || sEnd <= start || sStart >= end) { out.push({ ...s }); continue; }
        if (sStart < start) out.push({ ...s, text: s.text.slice(0, start - sStart) });
        const midText = s.text.slice(Math.max(0, start - sStart), Math.min(s.text.length, end - sStart));
        const middle = { ...s, text: midText };
        mutator(middle);
        out.push(middle);
        if (sEnd > end) out.push({ ...s, text: s.text.slice(end - sStart) });
      }
      region.spans = _mergeAdjacent(out.filter(s => s.text));
      region.text = region.spans.map(s => s.text).join('');
      fields.text.value = region.text;
      try { fields.text.setSelectionRange(start, end); } catch {}
      renderSpans();
      draw();
    }

    fields.text.addEventListener('contextmenu', (evt) => {
      const start = fields.text.selectionStart;
      const end = fields.text.selectionEnd;
      if (start === end) return;  // no selection: let browser show its default menu
      evt.preventDefault();
      const primary = selectedRegion();
      if (!primary) return;
      ctxSelection = { regionId: primary.id, start, end };
      const margin = 8;
      const left = Math.min(evt.clientX, window.innerWidth - 220 - margin);
      const top = Math.min(evt.clientY, window.innerHeight - 260 - margin);
      ctxMenuEl.style.left = left + 'px';
      ctxMenuEl.style.top = top + 'px';
      ctxMenuEl.classList.add('show');
    });

    ctxMenuEl.addEventListener('click', (evt) => {
      const btn = evt.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      ctxMenuEl.classList.remove('show');
      if (action === 'color') {
        ctxColorPicker.value = '#000000';
        ctxColorPicker.onchange = () => applyCharFormatting('color', hexToRgb(ctxColorPicker.value));
        ctxColorPicker.click();
      } else if (action === 'eyedrop') {
        pickColor((hex) => applyCharFormatting('color', hexToRgb(hex)));
      } else if (action === 'size') {
        const v = prompt('Font size (px) for selected characters:', '');
        const n = Number(v);
        if (n && n > 0) applyCharFormatting('size', Math.round(n));
      } else {
        applyCharFormatting(action);
      }
    });

    document.addEventListener('click', (evt) => {
      if (!evt.target.closest('.ctx-menu')) ctxMenuEl.classList.remove('show');
    });
    document.addEventListener('keydown', (evt) => {
      if (evt.key === 'Escape') ctxMenuEl.classList.remove('show');
    });

    spansListEl.addEventListener('input', (evt) => {
      const el = evt.target;
      const region = selectedRegion();
      if (!region || el.dataset.span == null) return;
      const i = Number(el.dataset.span);
      const prop = el.dataset.prop;
      const span = (region.spans || [])[i];
      if (!span) return;
      markMutated('span-' + prop + '-' + i);
      if (prop === 'text') {
        span.text = el.value;
        region.text = (region.spans || []).map(s => s.text).join('');
        fields.text.value = region.text;
      } else if (prop === 'color') {
        span.color = hexToRgb(el.value);
      } else if (prop === 'font_size_px') {
        span.font_size_px = Math.max(1, Number(el.value) || 1);
      } else if (prop === 'font_weight') {
        span.font_weight = el.value || null;
      } else if (prop === 'vertical_align') {
        span.vertical_align = el.value || null;
      }
      draw();
    });

    spansListEl.addEventListener('click', (evt) => {
      const btn = evt.target.closest('[data-del]');
      if (!btn) return;
      const region = selectedRegion();
      if (!region) return;
      markMutated('span-del-' + Date.now());
      region.spans.splice(Number(btn.dataset.del), 1);
      if (!region.spans.length) region.spans = [];
      renderSpans();
      draw();
    });

    spansInitBtn.addEventListener('click', () => {
      const region = selectedRegion();
      if (!region) return;
      markMutated('span-init-' + Date.now());
      region.spans = [{ text: region.text, color: null, font_size_px: null, font_weight: null }];
      renderSpans();
    });

    spansAddBtn.addEventListener('click', () => {
      const region = selectedRegion();
      if (!region) return;
      markMutated('span-add-' + Date.now());
      if (!region.spans) region.spans = [];
      region.spans.push({ text: '', color: null, font_size_px: null, font_weight: null });
      renderSpans();
    });

    spansClearBtn.addEventListener('click', () => {
      const region = selectedRegion();
      if (!region) return;
      markMutated('span-clear-' + Date.now());
      region.text = (region.spans || []).map(s => s.text).join('') || region.text;
      region.spans = [];
      fields.text.value = region.text;
      renderSpans();
    });

    // ── Field listeners ───────────────────────────────────────────────────────

    for (const el of [
      fields.replace,
      fields.text,
      fields.x,
      fields.y,
      fields.fontSize,
      fields.letterSpacing,
      fields.fontWeight,
      fields.textAnchor,
      fields.fontFamily,
      fields.color,
    ]) {
      const trackedSync = () => { markMutated('f-' + el.id); syncSelected(); };
      el.addEventListener('input', trackedSync);
      el.addEventListener('change', trackedSync);
    }

    canvas.addEventListener('pointerdown', (evt) => {
      const p = imagePoint(evt);
      const hit = hitTest(p.x, p.y);
      if (hit) {
        if (evt.shiftKey) {
          if (selectedIds.has(hit.id)) selectedIds.delete(hit.id);
          else selectedIds.add(hit.id);
          if (!selectedIds.has(selectedId)) {
            selectedId = selectedIds.size ? [...selectedIds][0] : null;
          }
          if (selectedId) selectRegion(selectedId);
          else { renderList(); draw(); }
        } else {
          if (!selectedIds.has(hit.id)) {
            selectedIds = new Set([hit.id]);
            selectRegion(hit.id);
          }
          const replaceable = [...selectedIds]
            .map(id => state.regions.find(r => r.id === id))
            .filter(r => r && r.replace);
          if (replaceable.length) {
            pushHistory('drag-' + hit.id + '-' + Date.now());
            dragging = true;
            dragStartPoint = p;
            dragStartPositions = new Map(replaceable.map(r => [r.id, { x: r.x, y: r.y }]));
          }
          canvas.setPointerCapture(evt.pointerId);
        }
      } else {
        marquee = { startX: p.x, startY: p.y, x: p.x, y: p.y, w: 0, h: 0 };
        canvas.setPointerCapture(evt.pointerId);
      }
    });

    canvas.addEventListener('pointermove', (evt) => {
      if (marquee) {
        const p = imagePoint(evt);
        marquee.x = Math.min(marquee.startX, p.x);
        marquee.y = Math.min(marquee.startY, p.y);
        marquee.w = Math.abs(p.x - marquee.startX);
        marquee.h = Math.abs(p.y - marquee.startY);
        draw();
        return;
      }
      if (!dragging || !dragStartPositions || !dragStartPoint) return;
      const p = imagePoint(evt);
      let dx = p.x - dragStartPoint.x;
      let dy = p.y - dragStartPoint.y;
      const primary = selectedRegion();
      if (primary && !evt.shiftKey) {
        const ps = dragStartPositions.get(primary.id);
        if (ps) {
          const snapped = snapPoint(ps.x + dx, ps.y + dy, primary.id, false);
          dx = snapped.x - ps.x;
          dy = snapped.y - ps.y;
        }
      } else {
        snapGuides = [];
      }
      for (const [id, start] of dragStartPositions) {
        const r = state.regions.find(x => x.id === id);
        if (!r) continue;
        r.x = Math.round(start.x + dx);
        r.y = Math.round(start.y + dy);
      }
      if (primary) {
        fields.x.value = primary.x;
        fields.y.value = primary.y;
      }
      draw();
    });

    canvas.addEventListener('pointerup', (evt) => {
      if (marquee) {
        const m = marquee;
        marquee = null;
        if (m.w >= 3 && m.h >= 3) {
          const ids = new Set();
          for (const r of state.regions) {
            const rct = rectFor(r);
            const cx = rct.x + rct.w / 2, cy = rct.y + rct.h / 2;
            if (cx >= m.x && cx <= m.x + m.w && cy >= m.y && cy <= m.y + m.h) {
              ids.add(r.id);
            }
          }
          selectedIds = ids;
          selectedId = ids.size ? [...ids][0] : null;
          if (selectedId) selectRegion(selectedId);
          else { renderList(); draw(); }
        } else {
          draw();
        }
        try { canvas.releasePointerCapture(evt.pointerId); } catch {}
        return;
      }
      const wasDragging = dragging;
      dragging = false;
      dragStartPositions = null;
      dragStartPoint = null;
      if (snapGuides.length) { snapGuides = []; draw(); }
      try { canvas.releasePointerCapture(evt.pointerId); } catch {}
      if (wasDragging) scheduleAutoRender();
    });

    document.getElementById('fitBtn').addEventListener('click', fitCanvas);
    document.getElementById('saveBtn').addEventListener('click', saveReview);
    renderBtn.addEventListener('click', renderOutput);
    document.getElementById('previewBtn').addEventListener('click', () => {
      previewMode = previewMode === 'all' ? 'selected' : 'all';
      const btn = document.getElementById('previewBtn');
      btn.textContent = previewMode === 'all' ? 'Preview: All' : 'Preview: Selected';
      draw();
    });
    document.getElementById('viewBtn').addEventListener('click', () => {
      viewMode = viewMode === 'source' ? 'rendered' : 'source';
      updateViewBtnLabel();
      if (viewMode === 'rendered') {
        if (autoRenderTimer) { clearTimeout(autoRenderTimer); autoRenderTimer = null; }
        runAutoRender();
      } else {
        reloadBackdrop();
      }
    });
    document.getElementById('redetectBtn').addEventListener('click', redetect);
    document.getElementById('fitSizesBtn').addEventListener('click', autofitSizes);
    document.getElementById('fontFamilyPick').addEventListener('change', (evt) => {
      const v = evt.target.value;
      if (!v) return;
      markMutated('f-fontFamilyPick');
      fields.fontFamily.value = v;
      syncSelected();
    });
    document.getElementById('exportPptBtn').addEventListener('click', exportPpt);
    document.addEventListener('keydown', (evt) => {
      if (!(evt.ctrlKey || evt.metaKey)) return;
      const k = evt.key.toLowerCase();
      if (k === 'z') {
        evt.preventDefault();
        if (evt.shiftKey) redo(); else undo();
      } else if (k === 'y') {
        evt.preventDefault();
        redo();
      }
    });

    document.addEventListener('keydown', (evt) => {
      if (evt.ctrlKey || evt.metaKey || evt.altKey) return;
      const t = evt.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if (!selectedIds.size) return;
      const step = evt.shiftKey ? 10 : 1;
      let dx = 0, dy = 0;
      if (evt.key === 'ArrowLeft') dx = -step;
      else if (evt.key === 'ArrowRight') dx = step;
      else if (evt.key === 'ArrowUp') dy = -step;
      else if (evt.key === 'ArrowDown') dy = step;
      else return;
      evt.preventDefault();
      markMutated('nudge-' + evt.key);
      for (const id of selectedIds) {
        const r = state.regions.find(x => x.id === id);
        if (r && r.replace) { r.x += dx; r.y += dy; }
      }
      const primary = selectedRegion();
      if (primary) {
        fields.x.value = primary.x;
        fields.y.value = primary.y;
      }
      draw();
    });
    window.addEventListener('resize', fitCanvas);
    loadFonts();
    load();
  </script>
</body>
</html>
"""


def build_editor_html() -> str:
    return EDITOR_HTML


DEFAULT_FONT_SPEC = FontSpec(
    title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40,
)
DEFAULT_FONTS_DIR = Path("fonts")


class ReviewEditorHandler(BaseHTTPRequestHandler):
    def __init__(
        self,
        *args,
        image_path: Optional[Path],
        review_path: Optional[Path],
        output_png: Optional[Path],
        output_svg: Optional[Path],
        project_path: Optional[Path],
        font_spec: FontSpec = DEFAULT_FONT_SPEC,
        fonts_dir: Path = DEFAULT_FONTS_DIR,
        **kwargs,
    ):
        self.image_path = image_path
        self.review_path = review_path
        self.output_png = output_png
        self.output_svg = output_svg or (output_png.with_suffix(".svg") if output_png else None)
        self.project_path = project_path
        self.font_spec = font_spec
        self.fonts_dir = fonts_dir
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def _items(self) -> list[ReviewProjectItem]:
        if self.project_path is not None:
            return load_review_project(self.project_path).items
        if self.image_path is None or self.review_path is None:
            return []
        output_png = str(self.output_png) if self.output_png else ""
        output_svg = str(self.output_svg) if self.output_svg else ""
        return [
            ReviewProjectItem(
                id="slide-001",
                name=self.image_path.stem,
                image_path=str(self.image_path),
                review_path=str(self.review_path),
                output_png=output_png,
                output_svg=output_svg,
            )
        ]

    def _item_for_request(self, parsed) -> Optional[ReviewProjectItem]:
        items = self._items()
        if not items:
            return None
        query = parse_qs(parsed.query)
        slide_id = query.get("slide", [""])[0]
        if not slide_id:
            return items[0]
        return next((item for item in items if item.id == slide_id), None)

    def _resolve_item_path(self, item: ReviewProjectItem, value: str) -> Path:
        if self.project_path is not None:
            return resolve_project_path(self.project_path, value)
        return Path(value)

    def _item_image_path(self, item: ReviewProjectItem) -> Path:
        return self._resolve_item_path(item, item.image_path)

    def _item_review_path(self, item: ReviewProjectItem) -> Path:
        return self._resolve_item_path(item, item.review_path)

    def _item_output_png(self, item: ReviewProjectItem) -> Optional[Path]:
        if not item.output_png:
            return None
        return self._resolve_item_path(item, item.output_png)

    def _item_output_svg(self, item: ReviewProjectItem) -> Optional[Path]:
        if not item.output_svg:
            return None
        return self._resolve_item_path(item, item.output_svg)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(build_editor_html(), "text/html; charset=utf-8")
        elif parsed.path == "/api/state":
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            review = load_review_document(self._item_review_path(item)).to_dict()
            output_png = self._item_output_png(item)
            output_svg = self._item_output_svg(item)
            review["output_png"] = str(output_png) if output_png else ""
            review["output_svg"] = str(output_svg) if output_svg else ""
            review["active_slide_id"] = item.id
            review["slides"] = [slide.to_dict() for slide in self._items()]
            self._send_json(review)
        elif parsed.path == "/image":
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            self._send_file(self._item_image_path(item))
        elif parsed.path == "/api/fonts":
            self._send_json({
                "system_groups": [
                    {"label": label, "names": list(names)}
                    for label, names in discover_grouped_fonts()
                ],
                "user": list_user_fonts(self.fonts_dir),
                "fonts_dir": str(self.fonts_dir.resolve() if self.fonts_dir else ""),
            })
        elif parsed.path.startswith("/fonts/"):
            filename = parsed.path[len("/fonts/"):]
            if "/" in filename or ".." in filename or "\\" in filename:
                self._send_json({"error": "Invalid font path"}, status=400)
                return
            font_path = self.fonts_dir / filename if self.fonts_dir else None
            if font_path is None or not font_path.exists():
                self._send_json({"error": "Font not found"}, status=404)
                return
            self._send_file(font_path)
        elif parsed.path == "/image-rendered":
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            try:
                self._render_if_stale(item)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            rendered = self._item_output_png(item)
            if rendered is None or not rendered.exists():
                self._send_json({"error": "No rendered PNG yet"}, status=404)
                return
            self._send_file(rendered)
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/review":
            review = self._read_review()
            if review is None:
                return
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            review_path = self._item_review_path(item)
            write_review_document(review, review_path)
            self._send_json({"ok": True, "review": str(review_path)})
        elif parsed.path == "/api/render":
            review = self._read_review()
            if review is None:
                return
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            output_png = self._item_output_png(item)
            output_svg = self._item_output_svg(item)
            if output_png is None or output_svg is None:
                self._send_json({"error": "No output path configured"}, status=400)
                return
            review_path = self._item_review_path(item)
            image_path = self._item_image_path(item)
            write_review_document(review, review_path)
            render_review_document(image_path, output_png, output_svg, review, fonts_dir=self.fonts_dir)
            self._send_json({
                "ok": True,
                "output_png": str(output_png),
                "output_svg": str(output_svg),
            })
        elif parsed.path == "/api/autofit":
            review = self._read_review()
            if review is None:
                return
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            changed = fit_font_sizes_to_bboxes(review.regions)
            write_review_document(review, self._item_review_path(item))
            self._send_json({"ok": True, "changed": changed})
        elif parsed.path == "/api/redetect":
            review = self._read_review()
            if review is None:
                return
            item = self._item_for_request(parsed)
            if item is None:
                self._send_json({"error": "Slide not found"}, status=404)
                return
            image_path = self._item_image_path(item)
            try:
                added = self._redetect_merge(review, image_path)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            review_path = self._item_review_path(item)
            write_review_document(review, review_path)
            self._send_json({"ok": True, "added": added, "total": len(review.regions)})
        elif parsed.path == "/api/export-ppt":
            if self.project_path is None:
                self._send_json(
                    {"error": "PPTX export requires a multi-slide project (started with --project)"},
                    status=400,
                )
                return
            self._drain_body()
            output = self.project_path.parent / (self.project_path.stem + "_export.pptx")
            try:
                for item in load_review_project(self.project_path).items:
                    self._render_if_stale(item)
                result = export_project_to_pptx(self.project_path, output)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"ok": True, "output": str(result)})
        else:
            self._send_json({"error": "Not found"}, status=404)

    def _drain_body(self) -> bytes:
        length = int(self.headers.get("content-length", "0"))
        return self.rfile.read(length) if length else b""

    def _render_if_stale(self, item: ReviewProjectItem) -> bool:
        """Re-render the slide's PNG if it's missing or older than the review JSON.

        Returns True when a fresh render ran, False when the existing PNG was fresh
        enough.  Quiet on missing pieces (no source image / no output path).
        """
        review_path = self._item_review_path(item)
        output_png = self._item_output_png(item)
        output_svg = self._item_output_svg(item)
        if output_png is None or output_svg is None or not review_path.exists():
            return False
        image_path = self._item_image_path(item)
        if not image_path.exists():
            return False
        if output_png.exists() and output_png.stat().st_mtime >= review_path.stat().st_mtime:
            return False
        review = load_review_document(review_path)
        render_review_document(image_path, output_png, output_svg, review)
        return True

    def _redetect_merge(self, current_review: ReviewDocument, image_path: Path) -> int:
        """Re-run analyze_image and append regions that don't overlap existing ones.

        Returns the number of newly added regions.
        """
        fresh = analyze_image(image_path, self.font_spec)

        existing_rects = []
        existing_ids = set()
        max_num = 0
        for r in current_review.regions:
            x, y, w, h = bbox_to_rect(r.bbox)
            existing_rects.append((x, y, w, h))
            existing_ids.add(r.id)
            if r.id.startswith("r") and r.id[1:].isdigit():
                max_num = max(max_num, int(r.id[1:]))

        counter = max_num + 1
        for nr in fresh.regions:
            nx, ny, nw, nh = bbox_to_rect(nr.bbox)
            ncx, ncy = nx + nw / 2, ny + nh / 2
            if any(
                ex <= ncx <= ex + ew and ey <= ncy <= ey + eh
                for ex, ey, ew, eh in existing_rects
            ):
                continue
            while f"r{counter:03d}" in existing_ids:
                counter += 1
            nr.id = f"r{counter:03d}"
            existing_ids.add(nr.id)
            counter += 1
            current_review.regions.append(nr)
        added = len(current_review.regions) - len(existing_rects)
        # Only fit the newly-added regions to avoid clobbering existing user-edited sizes
        if added:
            fit_font_sizes_to_bboxes(current_review.regions[-added:])
        auto_align_left_groups(current_review.regions)
        return added

    def _read_review(self) -> Optional[ReviewDocument]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8-sig"))
            return ReviewDocument.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return None

    def _send_file(self, path: Path) -> None:
        if not path.exists():
            self._send_json({"error": "File not found"}, status=404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, data: dict, status: int = 200) -> None:
        text = json.dumps(data, ensure_ascii=False)
        self._send_text(text, "application/json; charset=utf-8", status=status)


def make_server(
    image_path: Optional[Path],
    review_path: Optional[Path],
    output_png: Optional[Path],
    output_svg: Optional[Path],
    host: str,
    port: int,
    project_path: Optional[Path] = None,
    fonts_dir: Path = DEFAULT_FONTS_DIR,
) -> ThreadingHTTPServer:
    handler = partial(
        ReviewEditorHandler,
        image_path=image_path,
        review_path=review_path,
        output_png=output_png,
        output_svg=output_svg,
        project_path=project_path,
        fonts_dir=fonts_dir,
    )
    return ThreadingHTTPServer((host, port), handler)


def serve_editor(
    host: str,
    port: int,
    image_path: Optional[Path] = None,
    review_path: Optional[Path] = None,
    output_png: Optional[Path] = None,
    output_svg: Optional[Path] = None,
    project_path: Optional[Path] = None,
    open_browser: bool = True,
    fonts_dir: Path = DEFAULT_FONTS_DIR,
) -> None:
    if fonts_dir:
        Path(fonts_dir).mkdir(parents=True, exist_ok=True)
    # Warm the system-font cache so the first /api/fonts call is instant.
    import threading
    threading.Thread(target=discover_grouped_fonts, daemon=True).start()
    server = make_server(
        image_path=image_path,
        review_path=review_path,
        output_png=output_png,
        output_svg=output_svg,
        host=host,
        port=port,
        project_path=project_path,
        fonts_dir=fonts_dir,
    )
    url = f"http://{host}:{server.server_port}/"
    print(f"Review editor: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the local review editor.")
    parser.add_argument("input_path", nargs="?", type=Path)
    parser.add_argument("review_json", nargs="?", type=Path)
    parser.add_argument("--project", type=Path, default=None)
    parser.add_argument("--output-png", type=Path, default=None)
    parser.add_argument("--svg", dest="output_svg", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument(
        "--fonts-dir", type=Path, default=DEFAULT_FONTS_DIR,
        help="Folder of .ttf/.otf/.ttc files to expose as imported fonts (default: ./fonts).",
    )
    args = parser.parse_args()

    if args.project is not None:
        if not args.project.exists():
            raise SystemExit(f"Review project not found: {args.project}")
        serve_editor(
            host=args.host,
            port=args.port,
            project_path=args.project,
            open_browser=not args.no_open,
            fonts_dir=args.fonts_dir,
        )
        return

    if args.input_path is None or args.review_json is None:
        raise SystemExit("Provide input_path and review_json, or use --project review_project.json")
    if not args.input_path.exists():
        raise SystemExit(f"Input image not found: {args.input_path}")
    if not args.review_json.exists():
        raise SystemExit(f"Review JSON not found: {args.review_json}")

    serve_editor(
        image_path=args.input_path,
        review_path=args.review_json,
        output_png=args.output_png,
        output_svg=args.output_svg,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
        fonts_dir=args.fonts_dir,
    )


if __name__ == "__main__":
    main()
