"use strict";

const $ = (selector) => document.querySelector(selector);
const canvas = $("#mask-canvas");
const cursorCanvas = $("#cursor-canvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const cursorCtx = cursorCanvas.getContext("2d");

const state = {
  data: null,
  index: 0,
  mode: "brush",
  brushSize: 14,
  drawing: false,
  panning: false,
  spacePressed: false,
  panStart: null,
  lastPoint: null,
  undo: [],
  redo: [],
  dirty: false,
  zoom: 1,
  fitZoom: 1,
  loadingToken: 0,
};

const statusLabels = {
  pending: "待标注",
  annotated: "已标裂缝",
  negative: "空白样本",
  skipped: "已跳过",
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.blob();
  if (!response.ok) throw new Error(body.error || `请求失败 (${response.status})`);
  return body;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 1800);
}

function current() {
  return state.data.candidates[state.index];
}

function completedCount() {
  const counts = state.data.counts;
  return counts.annotated + counts.negative;
}

function refreshSummary() {
  const total = state.data.total;
  const completed = completedCount();
  $("#progress-label").textContent = `${completed} / ${total}`;
  const split = state.data.split_counts || {};
  const splitSummary = split.train || split.test ? ` · 训练 ${split.train || 0} / 测试 ${split.test || 0}` : "";
  $("#progress-detail").textContent = `跳过 ${state.data.counts.skipped} · 待标 ${state.data.counts.pending}${splitSummary}`;
  $("#progress-fill").style.width = `${total ? (completed / total) * 100 : 0}%`;
  $("#sample-total").textContent = `/ ${total}`;
  $("#sample-index").max = total;
  $("#output-path").textContent = state.data.output_dir;
  renderSegments();
}

function renderSegments() {
  const container = $("#segment-list");
  const currentSegment = current()?.segment;
  container.replaceChildren();
  for (const segment of state.data.segments) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `segment-item${segment.name === currentSegment ? " active" : ""}`;
    button.title = segment.name;
    const percent = segment.total ? (segment.completed / segment.total) * 100 : 0;
    button.innerHTML = `
      <span class="segment-name"></span>
      <span class="segment-progress">
        <span class="segment-progress-track"><span style="width:${percent}%"></span></span>
        <span>${segment.completed}/${segment.total}</span>
      </span>`;
    button.querySelector(".segment-name").textContent = segment.name;
    button.addEventListener("click", () => jumpToSegment(segment.name));
    container.appendChild(button);
  }
}

function filteredIndex(direction, fromIndex = state.index) {
  const filter = $("#status-filter").value;
  const splitFilter = $("#split-filter").value;
  const total = state.data.total;
  const matches = (candidate) => {
    const statusMatches = filter === "all"
      || (filter === "completed" && ["annotated", "negative"].includes(candidate.status))
      || candidate.status === filter;
    const splitMatches = splitFilter === "all" || candidate.dataset_split === splitFilter;
    return statusMatches && splitMatches;
  };
  for (let offset = 1; offset <= total; offset += 1) {
    const index = (fromIndex + direction * offset + total) % total;
    if (matches(state.data.candidates[index])) return index;
  }
  return fromIndex;
}

function firstPendingAfter(fromIndex) {
  const splitFilter = $("#split-filter").value;
  const total = state.data.total;
  for (let offset = 1; offset <= total; offset += 1) {
    const index = (fromIndex + offset) % total;
    const candidate = state.data.candidates[index];
    const splitMatches = splitFilter === "all" || candidate.dataset_split === splitFilter;
    if (candidate.status === "pending" && splitMatches) return index;
  }
  return Math.min(fromIndex + 1, total - 1);
}

function jumpToSegment(segmentName) {
  const splitFilter = $("#split-filter").value;
  const splitMatches = (candidate) => splitFilter === "all" || candidate.dataset_split === splitFilter;
  const index = state.data.candidates.findIndex(
    (candidate) => candidate.segment === segmentName && candidate.status === "pending" && splitMatches(candidate),
  );
  const fallback = state.data.candidates.findIndex(
    (candidate) => candidate.segment === segmentName && splitMatches(candidate),
  );
  navigate(index >= 0 ? index : fallback);
}

function setMode(mode) {
  state.mode = mode;
  $("#brush-tool").classList.toggle("active", mode === "brush");
  $("#eraser-tool").classList.toggle("active", mode === "eraser");
}

function updateZoom(nextZoom) {
  state.zoom = Math.max(0.15, Math.min(4, nextZoom));
  const candidate = current();
  if (!candidate) return;
  const wrap = $("#canvas-wrap");
  wrap.style.width = `${Math.round(candidate.width * state.zoom)}px`;
  wrap.style.height = `${Math.round(candidate.height * state.zoom)}px`;
  $("#zoom-value").textContent = `${Math.round(state.zoom * 100)}%`;
}

function fitCanvas() {
  const candidate = current();
  if (!candidate) return;
  const viewport = $("#canvas-viewport");
  const widthScale = Math.max(0.1, (viewport.clientWidth - 36) / candidate.width);
  const heightScale = Math.max(0.1, (viewport.clientHeight - 36) / candidate.height);
  state.fitZoom = Math.min(widthScale, heightScale, 1.4);
  updateZoom(state.fitZoom);
}

function imageDataSnapshot() {
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function pushUndo() {
  state.undo.push(imageDataSnapshot());
  if (state.undo.length > 30) state.undo.shift();
  state.redo = [];
  updateHistoryButtons();
}

function undo() {
  if (!state.undo.length) return;
  state.redo.push(imageDataSnapshot());
  ctx.putImageData(state.undo.pop(), 0, 0);
  state.dirty = true;
  updateHistoryButtons();
}

function redo() {
  if (!state.redo.length) return;
  state.undo.push(imageDataSnapshot());
  ctx.putImageData(state.redo.pop(), 0, 0);
  state.dirty = true;
  updateHistoryButtons();
}

function updateHistoryButtons() {
  $("#undo-button").disabled = state.undo.length === 0;
  $("#redo-button").disabled = state.redo.length === 0;
}

function clearMask() {
  pushUndo();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  state.dirty = true;
}

function pointFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function drawStroke(from, to) {
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.lineWidth = state.brushSize;
  ctx.globalCompositeOperation = state.mode === "brush" ? "source-over" : "destination-out";
  ctx.strokeStyle = "rgba(235, 64, 54, 0.78)";
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();
  ctx.restore();
}

function drawCursor(event) {
  cursorCtx.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
  if (event.type === "pointerleave") return;
  const point = pointFromEvent(event);
  cursorCtx.beginPath();
  cursorCtx.arc(point.x, point.y, state.brushSize / 2, 0, Math.PI * 2);
  cursorCtx.strokeStyle = state.mode === "brush" ? "rgba(255,255,255,.9)" : "rgba(72,185,177,.95)";
  cursorCtx.lineWidth = Math.max(1, 1 / state.zoom);
  cursorCtx.stroke();
}

function pointerDown(event) {
  const viewport = $("#canvas-viewport");
  if (event.button === 1 || (event.button === 0 && state.spacePressed)) {
    event.preventDefault();
    state.panning = true;
    state.panStart = {
      x: event.clientX,
      y: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    canvas.setPointerCapture(event.pointerId);
    cursorCtx.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
    return;
  }
  if (event.button !== 0) return;
  event.preventDefault();
  pushUndo();
  state.drawing = true;
  state.lastPoint = pointFromEvent(event);
  canvas.setPointerCapture(event.pointerId);
  drawStroke(state.lastPoint, state.lastPoint);
  state.dirty = true;
}

function pointerMove(event) {
  if (state.panning && state.panStart) {
    const viewport = $("#canvas-viewport");
    viewport.scrollLeft = state.panStart.scrollLeft - (event.clientX - state.panStart.x);
    viewport.scrollTop = state.panStart.scrollTop - (event.clientY - state.panStart.y);
    return;
  }
  drawCursor(event);
  if (!state.drawing) return;
  const point = pointFromEvent(event);
  drawStroke(state.lastPoint, point);
  state.lastPoint = point;
}

function pointerUp(event) {
  if (state.panning) {
    state.panning = false;
    state.panStart = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    return;
  }
  if (!state.drawing) return;
  state.drawing = false;
  state.lastPoint = null;
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
}

async function loadMask(index, token) {
  const image = new Image();
  image.src = `/api/candidates/${index}/mask?t=${Date.now()}`;
  await image.decode();
  if (token !== state.loadingToken) return;
  const scratch = document.createElement("canvas");
  scratch.width = canvas.width;
  scratch.height = canvas.height;
  const scratchCtx = scratch.getContext("2d", { willReadFrequently: true });
  scratchCtx.drawImage(image, 0, 0);
  const pixels = scratchCtx.getImageData(0, 0, canvas.width, canvas.height);
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    const marked = pixels.data[offset] > 0;
    pixels.data[offset] = 235;
    pixels.data[offset + 1] = 64;
    pixels.data[offset + 2] = 54;
    pixels.data[offset + 3] = marked ? 200 : 0;
  }
  ctx.putImageData(pixels, 0, 0);
}

function updateMetadata() {
  const candidate = current();
  const purpose = candidate.split_name ? ` · ${candidate.split_name}` : "";
  $("#sample-meta").textContent = `${candidate.segment} · ${candidate.time_seconds.toFixed(2)} 秒 · ${candidate.quadrant_name}${purpose}`;
  $("#quadrant-badge").textContent = candidate.quadrant_name;
  $("#video-name").textContent = candidate.video_name;
  $("#sample-number").textContent = `第 ${candidate.sample_number} 个抽样点`;
  $("#time-value").textContent = `${candidate.time_seconds.toFixed(3)} 秒`;
  $("#frame-value").textContent = candidate.frame_index;
  $("#size-value").textContent = `${candidate.width} × ${candidate.height}`;
  $("#status-value").textContent = statusLabels[candidate.status] || candidate.status;
  $("#status-value").dataset.status = candidate.status;
  $("#split-value").textContent = candidate.split_name || "常规标注";
  $("#split-value").dataset.split = candidate.dataset_split || "all";
  $("#split-row").hidden = !candidate.dataset_split;
  $("#sample-index").value = state.index + 1;
  $("#previous-button").disabled = state.data.total < 2;
  $("#next-button").disabled = state.data.total < 2;
  renderSegments();
}

async function loadCandidate(index) {
  state.index = Math.max(0, Math.min(index, state.data.total - 1));
  const token = ++state.loadingToken;
  const candidate = current();
  const source = $("#source-image");
  const context = $("#context-image");
  $("#loading-state").classList.remove("hidden");
  updateMetadata();
  state.undo = [];
  state.redo = [];
  updateHistoryButtons();
  state.dirty = false;
  canvas.width = candidate.width;
  canvas.height = candidate.height;
  cursorCanvas.width = candidate.width;
  cursorCanvas.height = candidate.height;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  source.src = `/api/candidates/${state.index}/image?t=${Date.now()}`;
  context.src = `/api/candidates/${state.index}/context?t=${Date.now()}`;
  try {
    await Promise.all([source.decode(), context.decode(), loadMask(state.index, token)]);
    if (token !== state.loadingToken) return;
    requestAnimationFrame(fitCanvas);
  } catch (error) {
    toast(error.message || "图像加载失败", true);
  } finally {
    if (token === state.loadingToken) $("#loading-state").classList.add("hidden");
  }
}

function canNavigate() {
  return !state.dirty || window.confirm("当前掩膜尚未保存，确定离开吗？");
}

function navigate(index) {
  if (!canNavigate() || index < 0) return;
  loadCandidate(index);
}

function binaryMaskDataUrl() {
  const sourcePixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  const output = document.createElement("canvas");
  output.width = canvas.width;
  output.height = canvas.height;
  const outputCtx = output.getContext("2d");
  const mask = outputCtx.createImageData(canvas.width, canvas.height);
  for (let offset = 0; offset < sourcePixels.length; offset += 4) {
    const value = sourcePixels[offset + 3] > 0 ? 255 : 0;
    mask.data[offset] = value;
    mask.data[offset + 1] = value;
    mask.data[offset + 2] = value;
    mask.data[offset + 3] = 255;
  }
  outputCtx.putImageData(mask, 0, 0);
  return output.toDataURL("image/png");
}

async function save(negative = false) {
  setBusy(true);
  try {
    state.data = await api(`/api/candidates/${state.index}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mask: binaryMaskDataUrl(), negative }),
    });
    state.dirty = false;
    toast(negative ? "空白样本已保存" : "裂缝掩膜已保存");
    const next = firstPendingAfter(state.index);
    refreshSummary();
    await loadCandidate(next);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function skip() {
  setBusy(true);
  try {
    state.data = await api(`/api/candidates/${state.index}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "skipped" }),
    });
    state.dirty = false;
    toast("样本已跳过");
    const next = firstPendingAfter(state.index);
    refreshSummary();
    await loadCandidate(next);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  for (const selector of ["#save-button", "#negative-button", "#skip-button"]) {
    $(selector).disabled = busy;
  }
}

function bindEvents() {
  $("#brush-tool").addEventListener("click", () => setMode("brush"));
  $("#eraser-tool").addEventListener("click", () => setMode("eraser"));
  $("#brush-size").addEventListener("input", (event) => {
    state.brushSize = Number(event.target.value);
    $("#brush-size-value").textContent = state.brushSize;
  });
  $("#undo-button").addEventListener("click", undo);
  $("#redo-button").addEventListener("click", redo);
  $("#clear-button").addEventListener("click", clearMask);
  $("#zoom-out").addEventListener("click", () => updateZoom(state.zoom / 1.2));
  $("#zoom-in").addEventListener("click", () => updateZoom(state.zoom * 1.2));
  $("#fit-button").addEventListener("click", fitCanvas);
  $("#previous-button").addEventListener("click", () => navigate(filteredIndex(-1)));
  $("#next-button").addEventListener("click", () => navigate(filteredIndex(1)));
  $("#save-button").addEventListener("click", () => save(false));
  $("#negative-button").addEventListener("click", () => save(true));
  $("#skip-button").addEventListener("click", skip);
  $("#sample-index").addEventListener("change", (event) => navigate(Number(event.target.value) - 1));
  $("#status-filter").addEventListener("change", () => navigate(filteredIndex(1, state.index - 1)));
  $("#split-filter").addEventListener("change", () => navigate(filteredIndex(1, state.index - 1)));
  canvas.addEventListener("pointerdown", pointerDown);
  canvas.addEventListener("pointermove", pointerMove);
  canvas.addEventListener("pointerup", pointerUp);
  canvas.addEventListener("pointercancel", pointerUp);
  canvas.addEventListener("pointerleave", drawCursor);
  new ResizeObserver(() => {
    if (Math.abs(state.zoom - state.fitZoom) < 0.01) fitCanvas();
  }).observe($("#canvas-viewport"));
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("keydown", (event) => {
    if (event.code === "Space") {
      event.preventDefault();
      state.spacePressed = true;
      return;
    }
    if (["INPUT", "SELECT"].includes(document.activeElement.tagName)) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      event.shiftKey ? redo() : undo();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      event.preventDefault(); redo();
    } else if (event.key.toLowerCase() === "b") setMode("brush");
    else if (event.key.toLowerCase() === "e") setMode("eraser");
    else if (event.key === "ArrowLeft") navigate(filteredIndex(-1));
    else if (event.key === "ArrowRight") navigate(filteredIndex(1));
    else if (event.key === "Enter") save(false);
    else if (event.key.toLowerCase() === "n") save(true);
  });
  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") state.spacePressed = false;
  });
  window.addEventListener("blur", () => {
    state.spacePressed = false;
    state.panning = false;
    state.panStart = null;
  });
}

async function init() {
  bindEvents();
  updateHistoryButtons();
  try {
    state.data = await api("/api/state");
    if (!state.data.total) throw new Error("数据清单为空");
    $("#annotation-title").textContent = state.data.annotation_title || "道路裂缝标注";
    $("#split-filter").hidden = !state.data.split_counts?.train && !state.data.split_counts?.test;
    const firstPending = state.data.candidates.findIndex((candidate) => candidate.status === "pending");
    refreshSummary();
    await loadCandidate(firstPending >= 0 ? firstPending : 0);
  } catch (error) {
    $("#loading-state").textContent = error.message;
    toast(error.message, true);
  }
}

init();
