<template>
  <div class="page-shell">
    <div class="page-header">
      <div>
        <h1 class="page-title">地图展示</h1>
        <p class="page-subtitle">按道路和严重程度查看裂缝空间分布，点击点位即可查看几何指标与检测结果图。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadPoints">刷新点位</el-button>
    </div>

    <div class="surface map-workbench">
      <aside class="map-controls">
        <div class="section-head">
          <div>
            <h2 class="section-title">点位筛选</h2>
            <p class="meta-text">筛选条件会立即刷新地图标记。</p>
          </div>
        </div>

        <div class="control-stack">
          <el-select v-model="filters.road_name" clearable placeholder="筛选道路">
            <el-option v-for="item in roadOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="filters.severity_level" clearable placeholder="筛选严重度">
            <el-option label="轻微" :value="1" />
            <el-option label="中等" :value="2" />
            <el-option label="严重" :value="3" />
          </el-select>
        </div>

        <div class="map-stats">
          <div>
            <span>当前点位</span>
            <strong>{{ pointStats.total }}</strong>
          </div>
          <div>
            <span>严重</span>
            <strong>{{ pointStats.severe }}</strong>
          </div>
          <div>
            <span>中等</span>
            <strong>{{ pointStats.medium }}</strong>
          </div>
          <div>
            <span>轻微</span>
            <strong>{{ pointStats.minor }}</strong>
          </div>
        </div>

        <div class="map-legend">
          <span><i class="legend-dot severe" /> 严重风险</span>
          <span><i class="legend-dot medium" /> 中等风险</span>
          <span><i class="legend-dot minor" /> 轻微风险</span>
        </div>
      </aside>

      <section class="map-stage">
        <div class="map-statusbar">
          <div>
            <strong>裂缝空间分布</strong>
            <span>高德地图底图 / 实时数据库点位</span>
          </div>
          <el-tag type="success" effect="plain">{{ pointStats.total }} 个点位</el-tag>
        </div>
        <div ref="mapRef" class="map-panel" />
        <div v-if="mapError" class="map-empty">{{ mapError }}</div>
        <div v-else-if="!pointStats.total" class="map-empty">暂无点位，请先完成一次检测或调整筛选条件。</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { Refresh } from "@element-plus/icons-vue";

import { fetchCrackMap, fetchFrameRoads, fetchInspectionFrameDetail } from "../api/modules";
import { assetUrl } from "../api/request";
import {
  clearMapObjects,
  createAmap,
  fitAmapBounds,
  markerContent,
  wgs84ToGcj02,
} from "../utils/amap";

const loading = ref(false);
const mapRef = ref(null);
const mapError = ref("");
const roadOptions = ref([]);
const mapPoints = ref([]);
const filters = reactive({
  road_name: "",
  severity_level: null,
});

let mapInstance = null;
let AMapApi = null;
const mapObjects = [];
const popupGroups = new Map();

const pointStats = computed(() => ({
  total: mapPoints.value.length,
  severe: mapPoints.value.filter((item) => item.severity_level === 3).length,
  medium: mapPoints.value.filter((item) => item.severity_level === 2).length,
  minor: mapPoints.value.filter((item) => item.severity_level === 1).length,
}));

function markerColor(level) {
  if (level === 3) return "#ef4444";
  if (level === 2) return "#f97316";
  return "#22c55e";
}

function coordinateKey(longitude, latitude) {
  return `${Number(longitude).toFixed(7)},${Number(latitude).toFixed(7)}`;
}

function groupPoints(points) {
  const groups = new Map();
  points.forEach((point) => {
    const key = coordinateKey(point.longitude, point.latitude);
    if (!groups.has(key)) {
      groups.set(key, {
        longitude: Number(point.longitude),
        latitude: Number(point.latitude),
        severity_level: point.severity_level,
        items: [],
      });
    }
    const group = groups.get(key);
    group.items.push(point);
    group.severity_level = Math.max(group.severity_level, point.severity_level);
  });
  return [...groups.values()];
}

function escapeHtml(value) {
  return String(value ?? "-")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatPopupTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatCoordinate(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(6) : "-";
}

function normalizePopupItem(source = {}, fallback = {}) {
  return {
    crack_id: source.id ?? source.crack_id ?? fallback.crack_id ?? null,
    identity_id: source.identity_id ?? fallback.identity_id ?? null,
    frame_id: source.frame_id ?? fallback.frame_id ?? null,
    identity_code: source.identity_code ?? fallback.identity_code ?? null,
    crack_code: source.crack_code ?? fallback.crack_code ?? null,
    road_name: source.road_name ?? fallback.road_name ?? null,
    district: source.district ?? fallback.district ?? null,
    severity_level: source.severity_level ?? fallback.severity_level ?? null,
    severity_label: source.severity_label ?? fallback.severity_label ?? null,
    crack_type: source.crack_type ?? fallback.crack_type ?? null,
    length_m: source.length_m ?? fallback.length_m ?? null,
    avg_width_cm: source.avg_width_cm ?? fallback.avg_width_cm ?? null,
    area_m2: source.area_m2 ?? fallback.area_m2 ?? null,
    longitude: source.longitude ?? fallback.longitude ?? null,
    latitude: source.latitude ?? fallback.latitude ?? null,
    result_image_uri: source.result_image_uri ?? fallback.result_image_uri ?? null,
    original_image_uri: source.original_image_uri ?? fallback.original_image_uri ?? null,
    mask_image_uri: source.mask_image_uri ?? fallback.mask_image_uri ?? null,
    detected_at: source.detected_at ?? fallback.detected_at ?? null,
    lifecycle_status: source.lifecycle_status ?? fallback.lifecycle_status ?? null,
    maintenance_status: source.maintenance_status ?? fallback.maintenance_status ?? null,
    priority_level: source.priority_level ?? fallback.priority_level ?? null,
  };
}

function buildPopupPreviews(item, title) {
  return [
    { mode: "original", label: "原图", uri: item.original_image_uri, alt: `${title} 原图` },
    { mode: "overlay", label: "Overlay", uri: item.result_image_uri, alt: `${title} overlay` },
    { mode: "mask", label: "Mask", uri: item.mask_image_uri, alt: `${title} mask` },
  ];
}

function resolvePreviewMode(item, previewMode) {
  const previews = buildPopupPreviews(item, "");
  const preferred = previews.find((preview) => preview.mode === previewMode && preview.uri);
  if (preferred) {
    return preferred.mode;
  }
  const available = previews.find((preview) => preview.uri);
  return available ? available.mode : previews[0].mode;
}

function popupPreviewCard(groupKey, preview, active) {
  const cardBorder = active ? "#2563eb" : "#e2e8f0";
  const cardBackground = active ? "#eff6ff" : "#ffffff";
  const cardHeader = active ? "#dbeafe" : "#f8fafc";
  const label = escapeHtml(preview.label);
  const previewBody = preview.uri
    ? `<img src="${assetUrl(preview.uri)}" alt="${escapeHtml(preview.alt)}" style="display:block; width:100%; height:70px; object-fit:cover; background:#e2e8f0;" />`
    : `<div style="display:flex; align-items:center; justify-content:center; height:70px; background:#f8fafc; color:#94a3b8; font-size:12px;">暂无图片</div>`;
  return `
    <button
      type="button"
      data-crack-preview="${groupKey}"
      data-preview-mode="${preview.mode}"
      ${preview.uri ? "" : "disabled"}
      style="padding:0; width:100%; border:1px solid ${cardBorder}; border-radius:10px; overflow:hidden; background:${cardBackground}; text-align:left; cursor:${preview.uri ? "pointer" : "not-allowed"}; ${preview.uri ? "" : "opacity:0.68;"}"
    >
      <div style="display:flex; align-items:center; justify-content:space-between; gap:6px; padding:7px 8px; font-size:12px; font-weight:600; color:${active ? "#1d4ed8" : "#0f172a"}; background:${cardHeader}; border-bottom:1px solid ${cardBorder};">
        <span>${label}</span>
        <span style="font-size:11px; color:${active ? "#2563eb" : "#94a3b8"};">${active ? "预览中" : preview.uri ? "点击查看" : "缺失"}</span>
      </div>
      ${previewBody}
    </button>
  `;
}

function popupPreviewPanel(groupKey, item, title, previewMode) {
  const previews = buildPopupPreviews(item, title);
  const activeMode = resolvePreviewMode(item, previewMode);
  const activePreview = previews.find((preview) => preview.mode === activeMode) || previews[0];
  const previewContent = activePreview.uri
    ? `<img src="${assetUrl(activePreview.uri)}" alt="${escapeHtml(activePreview.alt)}" style="display:block; width:100%; height:220px; object-fit:contain; background:#0f172a;" />`
    : `<div style="display:flex; align-items:center; justify-content:center; height:220px; background:linear-gradient(135deg, #0f172a, #1e293b); color:#cbd5e1; font-size:13px;">暂无可预览图片</div>`;
  return `
    <div style="margin-top:14px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px;">
        <strong style="font-size:13px; color:#0f172a;">大图预览</strong>
        <span style="font-size:12px; color:#64748b;">当前：${escapeHtml(activePreview.label)}</span>
      </div>
      <div style="border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; box-shadow:0 14px 28px rgba(15, 23, 42, 0.12);">
        ${previewContent}
      </div>
      <div style="display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; margin-top:10px;">
        ${previews.map((preview) => popupPreviewCard(groupKey, preview, preview.mode === activeMode)).join("")}
      </div>
    </div>
  `;
}

function popupHtml(group, index = 0, previewMode = "overlay", isFrameLoading = false) {
  const item = group.items[index] || group.items[0];
  const title = escapeHtml(item.identity_code || item.crack_code || "裂缝点位");
  const controls = group.items.length > 1
    ? `
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:12px;">
        <button type="button" data-crack-popup="${group.key}" data-dir="-1" style="border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:4px 8px; cursor:pointer;">上一条</button>
        <span>${index + 1} / ${group.items.length}</span>
        <button type="button" data-crack-popup="${group.key}" data-dir="1" style="border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:4px 8px; cursor:pointer;">下一条</button>
      </div>
    `
    : "";
  const frameHint = item.frame_id
    ? `<div style="margin-top:10px; padding:8px 10px; border-radius:8px; background:${isFrameLoading ? "#fff7ed" : "#f8fafc"}; border:1px solid ${isFrameLoading ? "#fdba74" : "#e2e8f0"}; color:${isFrameLoading ? "#c2410c" : "#64748b"}; font-size:12px;">${isFrameLoading ? "正在加载同帧裂缝..." : `当前支持浏览同帧裂缝，共 ${group.items.length} 条`}</div>`
    : "";
  return `
    <div style="width: 360px; color:#1f2937; line-height:1.5;">
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
        <strong style="font-size:15px; color:#0f172a;">${title}</strong>
        ${item.frame_id ? `<span style="padding:2px 8px; border-radius:999px; background:#dbeafe; color:#1d4ed8; font-size:12px;">同帧 ${group.items.length} 条</span>` : group.items.length > 1 ? `<span style="padding:2px 8px; border-radius:999px; background:#dbeafe; color:#1d4ed8; font-size:12px;">同点 ${group.items.length} 条</span>` : ""}
      </div>
      <div style="display:grid; grid-template-columns:72px 1fr; column-gap:10px; row-gap:6px; margin-top:12px; font-size:13px;">
        <span style="color:#64748b;">道路名称</span>
        <span style="color:#0f172a; font-weight:600;">${escapeHtml(item.road_name || "-")}</span>
        <span style="color:#64748b;">经纬度</span>
        <span>${formatCoordinate(item.longitude)}, ${formatCoordinate(item.latitude)}</span>
        <span style="color:#64748b;">等级</span>
        <span>${escapeHtml(item.severity_label || "-")}</span>
        <span style="color:#64748b;">发现时间</span>
        <span>${escapeHtml(formatPopupTime(item.detected_at))}</span>
      </div>
      ${frameHint}
      ${popupPreviewPanel(group.key, item, title, previewMode)}
      ${controls}
    </div>
  `;
}

function renderPopupState(state) {
  if (!state?.infoWindow) return;
  const item = state.group.items[state.index] || state.group.items[0] || {};
  state.preview = resolvePreviewMode(item, state.preview);
  state.infoWindow.setContent(popupHtml(state.group, state.index, state.preview, state.isFrameLoading));
}

async function ensureFrameItems(state) {
  if (!state || state.hasLoadedFrameItems || state.isFrameLoading) return;
  const currentItem = state.group.items[state.index] || state.group.items[0];
  const frameId = currentItem?.frame_id;
  if (!frameId) {
    state.hasLoadedFrameItems = true;
    return;
  }

  state.isFrameLoading = true;
  renderPopupState(state);

  try {
    const frameDetail = await fetchInspectionFrameDetail(frameId);
    const frameItems = (frameDetail.cracks || []).map((crack) =>
      normalizePopupItem(
        {
          ...crack,
          road_name: frameDetail.road_name,
          district: frameDetail.district,
          mask_image_uri: frameDetail.mask_image_uri,
          detected_at: frameDetail.captured_at,
          frame_id: frameDetail.id,
        },
        currentItem,
      ),
    );
    if (frameItems.length) {
      const currentCrackId = currentItem?.crack_id;
      state.group.items = frameItems;
      const matchedIndex = frameItems.findIndex((item) => item.crack_id === currentCrackId);
      state.index = matchedIndex >= 0 ? matchedIndex : 0;
    }
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    state.isFrameLoading = false;
    state.hasLoadedFrameItems = true;
    const nextItem = state.group.items[state.index] || state.group.items[0] || {};
    state.preview = resolvePreviewMode(nextItem, state.preview);
    renderPopupState(state);
    setTimeout(() => {
      attachPopupInteractions(document);
    }, 0);
  }
}

function attachPopupInteractions(container) {
  if (!container) return;

  container.querySelectorAll("[data-crack-popup]").forEach((button) => {
    if (button.dataset.popupBound === "1") return;
    button.dataset.popupBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = button.getAttribute("data-crack-popup");
      const dir = Number(button.getAttribute("data-dir") || 1);
      const state = popupGroups.get(key);
      if (!state) return;
      state.index = (state.index + dir + state.group.items.length) % state.group.items.length;
      state.preview = resolvePreviewMode(state.group.items[state.index] || {}, state.preview);
      renderPopupState(state);
      setTimeout(() => {
        attachPopupInteractions(container);
      }, 0);
    });
  });

  container.querySelectorAll("[data-crack-preview]").forEach((button) => {
    if (button.dataset.popupBound === "1") return;
    button.dataset.popupBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = button.getAttribute("data-crack-preview");
      const previewMode = button.getAttribute("data-preview-mode") || "overlay";
      const state = popupGroups.get(key);
      if (!state) return;
      state.preview = resolvePreviewMode(state.group.items[state.index] || {}, previewMode);
      renderPopupState(state);
      setTimeout(() => {
        attachPopupInteractions(container);
      }, 0);
    });
  });
}

async function initMap() {
  if (mapInstance || !mapRef.value) {
    return Boolean(mapInstance);
  }
  try {
    mapError.value = "";
    mapInstance = await createAmap(mapRef.value);
    AMapApi = window.AMap;
    return true;
  } catch (error) {
    mapError.value = error.message;
    ElMessage.error(error.message);
    return false;
  }
}

function renderMarkers(points) {
  if (!mapInstance || !AMapApi) return;
  clearMapObjects(mapInstance, mapObjects);
  popupGroups.clear();

  if (!points.length) {
    return;
  }

  const positions = [];
  groupPoints(points).forEach((group) => {
    group.key = coordinateKey(group.longitude, group.latitude);
    const position = wgs84ToGcj02(group.longitude, group.latitude);
    const marker = new AMapApi.Marker({
      position,
      content: markerContent(markerColor(group.severity_level), group.items.length > 1 ? 24 : 18),
      anchor: "center",
      zIndex: 100 + group.severity_level,
    });
    const initialPreview = resolvePreviewMode(group.items[0] || {}, "overlay");
    const infoWindow = new AMapApi.InfoWindow({
      content: popupHtml(group, 0, initialPreview),
      offset: new AMapApi.Pixel(0, -14),
      anchor: "bottom-center",
    });
    popupGroups.set(group.key, { marker, infoWindow, group, index: 0, preview: initialPreview });
    popupGroups.set(group.key, {
      marker,
      infoWindow,
      group: {
        ...group,
        items: group.items.map((item) => normalizePopupItem(item)),
      },
      index: 0,
      preview: initialPreview,
      isFrameLoading: false,
      hasLoadedFrameItems: false,
    });
    marker.on("click", async () => {
      const state = popupGroups.get(group.key);
      if (state) {
        renderPopupState(state);
      }
      infoWindow.open(mapInstance, position);
      setTimeout(() => {
        attachPopupInteractions(document);
      }, 0);
      if (state) {
        await ensureFrameItems(state);
      }
    });
    marker.setMap(mapInstance);
    mapObjects.push(marker);
    positions.push(position);
  });

  fitAmapBounds(mapInstance, positions, undefined, mapObjects);
}

async function loadRoadOptions() {
  try {
    const roads = await fetchFrameRoads();
    roadOptions.value = [...new Set(roads.map((item) => item.road_name).filter(Boolean))];
  } catch (error) {
    ElMessage.error(error.message);
  }
}

async function loadPoints() {
  loading.value = true;
  try {
    const points = await fetchCrackMap({
      road_name: filters.road_name || undefined,
      severity_level: filters.severity_level || undefined,
    });
    mapPoints.value = points;
    renderMarkers(points);
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    loading.value = false;
  }
}

watch(
  () => [filters.road_name, filters.severity_level],
  () => {
    loadPoints();
  },
);

onMounted(async () => {
  await nextTick();
  await initMap();
  await loadRoadOptions();
  await loadPoints();
});

onBeforeUnmount(() => {
  if (mapInstance) {
    clearMapObjects(mapInstance, mapObjects);
    mapInstance.destroy();
    mapInstance = null;
    AMapApi = null;
  }
});
</script>

<style scoped>
.map-workbench {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: min(72vh, 760px);
  overflow: hidden;
}

.map-controls {
  padding: 22px;
  border-right: 1px solid #e2e8f0;
  background: #fff;
}

.control-stack {
  display: grid;
  gap: 12px;
}

.map-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.map-stats div {
  padding: 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.map-stats span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.map-stats strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 24px;
}

.map-stage {
  position: relative;
  min-height: 620px;
  background: #e2e8f0;
}

.map-statusbar {
  position: absolute;
  top: 16px;
  left: 16px;
  right: 16px;
  z-index: 500;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
}

.map-statusbar strong,
.map-statusbar span {
  display: block;
}

.map-statusbar strong {
  color: #0f172a;
  font-size: 14px;
}

.map-statusbar span {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.map-panel {
  width: 100%;
  height: 100%;
  min-height: 620px;
  overflow: hidden;
}

.map-empty {
  position: absolute;
  left: 50%;
  bottom: 28px;
  transform: translateX(-50%);
  z-index: 500;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 13px;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.12);
}

.map-legend {
  display: grid;
  gap: 10px;
  margin-top: 22px;
  color: #334155;
  font-size: 13px;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  margin-right: 6px;
}

.legend-dot.minor {
  background: #22c55e;
}

.legend-dot.medium {
  background: #f97316;
}

.legend-dot.severe {
  background: #ef4444;
}

@media (max-width: 1080px) {
  .map-workbench {
    grid-template-columns: 1fr;
  }

  .map-controls {
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
}

@media (max-width: 640px) {
  .map-statusbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
