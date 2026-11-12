<template>
  <div class="chat-page">
    <section class="surface chat-panel">
      <header class="chat-head">
        <div class="chat-title">
          <span class="title-icon">
            <el-icon><Cpu /></el-icon>
          </span>
          <div>
            <h1>智能查询大模型</h1>
            <p>自然语言检索道路缺陷统计、风险点位与维修建议</p>
          </div>
        </div>
        <el-button :icon="RefreshRight" @click="resetResult">清空</el-button>
      </header>

      <div class="chat-body">
        <div
          v-for="(message, index) in messages"
          :key="`${message.role}-${index}`"
          :class="['message-row', message.role === 'user' ? 'is-user' : 'is-assistant']"
        >
          <div class="message-avatar">
            <span v-if="message.role === 'user'">我</span>
            <el-icon v-else><Cpu /></el-icon>
          </div>
          <div class="message-stack">
            <div v-if="message.thinking" class="thinking-box is-thinking">
              <div class="thinking-title">模型详细思考</div>
              <pre>{{ message.thinking }}</pre>
            </div>
            <div v-if="message.statusLog" class="thinking-box">
              <div class="thinking-title">执行过程</div>
              <pre>{{ message.statusLog }}</pre>
            </div>
            <div v-if="message.content" :class="['message-bubble', { 'is-markdown': message.role === 'assistant' }]">
              <div v-if="message.role === 'assistant'" class="markdown-body" v-html="renderMarkdown(message.content)" />
              <template v-else>{{ message.content }}</template>
            </div>
            <div v-if="message.actions" class="message-actions">
              <el-button plain :icon="Operation" @click="flowDialogVisible = true">Agent链路</el-button>
              <el-button plain :icon="Histogram" :disabled="!hasAnalysis" @click="statsDialogVisible = true">
                统计结果
              </el-button>
              <el-button plain type="primary" :icon="MapLocation" @click="openMapDialog">
                在地图查看
              </el-button>
            </div>
          </div>
        </div>

        <div v-if="loading" class="message-row is-assistant">
          <div class="message-avatar">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="typing-bubble">
            <span />
            <span />
            <span />
          </div>
        </div>
        <div ref="messagesEndRef" />
      </div>

      <footer class="chat-foot">
        <div class="quick-prompts">
          <span>快捷指令</span>
          <button v-for="item in examples" :key="item" @click="question = item">{{ item }}</button>
        </div>
        <div class="composer">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入查询指令，例如：查询学府路最近一周严重裂缝..."
            @keydown.ctrl.enter="submitQuery"
          />
          <el-button
            class="send-button"
            type="primary"
            :icon="Promotion"
            :disabled="!question.trim() || loading"
            :loading="loading"
            @click="submitQuery"
          />
        </div>
      </footer>
    </section>

    <el-dialog v-model="flowDialogVisible" title="Agent 调用流程" width="960px">
      <div class="flow-dialog">
        <section>
          <div class="dialog-section-head">
            <h2>Todo 执行过程</h2>
            <el-tag size="small" effect="plain">{{ result.todos.length }} 步</el-tag>
          </div>
          <div v-if="result.todos.length" class="todo-list">
            <div
              v-for="todo in result.todos"
              :key="todo.id || todo.step_order"
              :class="['todo-item', `is-${todo.status}`]"
            >
              <div class="todo-index">{{ todo.step_order }}</div>
              <div class="todo-main">
                <div class="todo-line">
                  <span class="todo-content">{{ todo.content }}</span>
                  <el-tag :type="todoStatusType(todo.status)" size="small">{{ todo.status }}</el-tag>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">当前还没有 Todo 流程。</div>
        </section>

        <section>
          <div class="dialog-section-head">
            <h2>工具调用轨迹</h2>
            <el-tag size="small" :type="result.tool_calls.length ? 'success' : 'info'" effect="plain">
              {{ result.tool_calls.length }} 次调用
            </el-tag>
          </div>
          <el-collapse v-if="result.tool_calls.length">
            <el-collapse-item
              v-for="(item, index) in result.tool_calls"
              :key="item.id || `${item.tool_name}-${index}`"
              :name="index"
            >
              <template #title>
                <div class="tool-title">
                  <span>{{ index + 1 }}. {{ item.tool_name }}</span>
                  <el-tag :type="item.status === 'success' ? 'success' : 'danger'" size="small">
                    {{ item.status }}
                  </el-tag>
                </div>
              </template>
              <div class="tool-body">
                <div>
                  <p class="mini-title">Arguments</p>
                  <pre class="code-block">{{ prettyJson(item.tool_args) }}</pre>
                </div>
                <div>
                  <p class="mini-title">Observation</p>
                  <pre class="code-block">{{ prettyJson(item.tool_result || { error_message: item.error_message }) }}</pre>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
          <div v-else class="empty-state">当前还没有工具调用记录。</div>
        </section>
      </div>
    </el-dialog>

    <el-dialog v-model="statsDialogVisible" title="统计结果" width="920px">
      <div v-if="hasAnalysis">
        <div class="stats-grid">
          <div class="stat-box">
            <span>裂缝总数</span>
            <strong>{{ statsMode === "compare" ? result.stats.current?.total_count || 0 : result.stats.total_count || 0 }}</strong>
          </div>
          <div class="stat-box">
            <span>严重裂缝</span>
            <strong>{{ statsMode === "compare" ? result.stats.current?.severe_count || 0 : result.stats.severe_count || 0 }}</strong>
          </div>
          <div class="stat-box">
            <span>总长度(m)</span>
            <strong>{{ statsMode === "compare" ? result.stats.current?.total_length_m || 0 : result.stats.total_length_m || 0 }}</strong>
          </div>
          <div class="stat-box">
            <span>总面积(m²)</span>
            <strong>{{ statsMode === "compare" ? result.stats.current?.total_area_m2 || 0 : result.stats.total_area_m2 || 0 }}</strong>
          </div>
        </div>

        <el-descriptions :column="2" border class="stats-descriptions">
          <template v-if="statsMode === 'compare'">
            <el-descriptions-item label="当前时间段">
              {{ result.stats.current_start }} 至 {{ result.stats.current_end }}
            </el-descriptions-item>
            <el-descriptions-item label="对比时间段">
              {{ result.stats.previous_start }} 至 {{ result.stats.previous_end }}
            </el-descriptions-item>
            <el-descriptions-item label="数量变化">
              {{ result.stats.delta?.count_change ?? 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="严重裂缝变化">
              {{ result.stats.delta?.serious_count_change ?? 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="长度变化(m)">
              {{ result.stats.delta?.length_change_m ?? 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="面积变化(m²)">
              {{ result.stats.delta?.area_change_m2 ?? 0 }}
            </el-descriptions-item>
          </template>
          <template v-else>
            <el-descriptions-item label="时间范围">
              {{ result.stats.start_date || "-" }} 至 {{ result.stats.end_date || "-" }}
            </el-descriptions-item>
            <el-descriptions-item label="严重程度分布">
              轻微 {{ result.stats.severity_distribution?.["轻微"] || 0 }} /
              中等 {{ result.stats.severity_distribution?.["中等"] || 0 }} /
              严重 {{ result.stats.severity_distribution?.["严重"] || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="最大宽度(mm)">
              {{ result.stats.max_width_mm || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="平均宽度(mm)">
              {{ result.stats.avg_width_mm || 0 }}
            </el-descriptions-item>
          </template>
        </el-descriptions>

        <div v-if="hasImageAnalysis" class="advice-block">
          <div class="dialog-section-head">
            <h2>图片辅助判读</h2>
            <el-tag size="small" type="success" effect="plain">
              {{ result.image_analysis.images_analyzed?.length || 0 }} 张
            </el-tag>
          </div>
          <p class="summary-copy">{{ result.image_analysis.summary || result.image_analysis.message }}</p>
          <ul v-if="result.image_analysis.findings?.length" class="action-list">
            <li v-for="item in result.image_analysis.findings || []" :key="item">{{ item }}</li>
          </ul>
        </div>

        <div v-if="hasAdvice" class="advice-block">
          <div class="dialog-section-head">
            <h2>维修建议</h2>
            <el-tag size="small" :type="adviceTagType" effect="plain">
              {{ result.maintenance_advice.priority_level || "未生成" }}
            </el-tag>
          </div>
          <div class="advice-metrics">
            <div class="advice-metric">
              <span>技术等级</span>
              <strong>{{ result.maintenance_advice.technical_grade || "-" }}</strong>
            </div>
            <div class="advice-metric">
              <span>维修等级</span>
              <strong>{{ result.maintenance_advice.maintenance_level || "-" }}</strong>
            </div>
            <div class="advice-metric">
              <span>处置方式</span>
              <strong>{{ result.maintenance_advice.maintenance_label || "-" }}</strong>
            </div>
            <div class="advice-metric">
              <span>参考PCI</span>
              <strong>{{ result.maintenance_advice.reference_pci ?? "-" }}</strong>
            </div>
          </div>
          <p class="summary-copy">{{ result.maintenance_advice.summary }}</p>
          <p v-if="result.maintenance_advice.standard_basis" class="basis-copy">
            {{ result.maintenance_advice.standard_basis }}
          </p>
          <ul class="action-list">
            <li v-for="action in result.maintenance_advice.actions || []" :key="action">{{ action }}</li>
          </ul>
        </div>
      </div>
      <div v-else class="empty-state">当前还没有统计结果。</div>
    </el-dialog>

    <el-dialog v-model="mapDialogVisible" title="地图高亮位置" width="980px" @opened="handleMapOpened">
      <div ref="mapRef" class="dialog-map" />
      <p class="map-note">{{ mapMessage }}</p>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import DOMPurify from "dompurify";
import { marked } from "marked";
import {
  Cpu,
  Histogram,
  MapLocation,
  Operation,
  Promotion,
  RefreshRight,
} from "@element-plus/icons-vue";

import { AGENT_STREAM_URL, fetchAgentSession, fetchInspectionFrameDetail, runAgentQuery } from "../api/modules";
import { API_BASE_URL, assetUrl } from "../api/request";
import {
  clearMapObjects,
  createAmap,
  fitAmapBounds,
  markerContent,
  wgs84ToGcj02,
} from "../utils/amap";

const loading = ref(false);
const question = ref("");
const mapRef = ref(null);
const messagesEndRef = ref(null);
const flowDialogVisible = ref(false);
const statsDialogVisible = ref(false);
const mapDialogVisible = ref(false);
const mapMessage = ref("提交查询后，地图会高亮本次 Agent 选择的裂缝点位。");
const examples = [
  "查看学府路最近一周的裂缝情况",
  "找出最严重的5处裂缝",
  "帮我生成需要优先维修的道路清单",
  "这周和上周相比裂缝数量有没有增加",
];

const welcomeMessage = {
  role: "assistant",
  content: "您好，我是道路裂缝智能查询助手。您可以询问道路缺陷统计、重点位置巡检记录，或让我生成维修优先级建议。",
};
const STORAGE_KEY = "road-crack-demo:agent-chat-state";
const NEARBY_MARKER_CLUSTER_METERS = 30;

const messages = ref([{ ...welcomeMessage }]);

const initialResult = () => ({
  session_id: null,
  query: "",
  answer: "",
  todos: [],
  tool_calls: [],
  stats: {},
  cracks: [],
  images: [],
  image_analysis: {},
  map_geojson: { type: "FeatureCollection", features: [] },
  maintenance_advice: {},
  debug: {},
});

const result = reactive(initialResult());

let mapInstance = null;
let AMapApi = null;
let activeStreamController = null;
let pageLeaving = false;
let streamAbortExpected = false;
const mapObjects = [];
const popupGroups = new Map();

const featureCount = computed(() => result.map_geojson?.features?.length || 0);
const hasStats = computed(() => !!Object.keys(result.stats || {}).length);
const hasAdvice = computed(() => !!Object.keys(result.maintenance_advice || {}).length);
const hasImageAnalysis = computed(() => !!Object.keys(result.image_analysis || {}).length);
const hasAnalysis = computed(() => hasStats.value || hasAdvice.value || hasImageAnalysis.value || result.cracks.length > 0);
const statsMode = computed(() => (result.stats?.current && result.stats?.previous ? "compare" : "aggregate"));
const adviceTagType = computed(() => {
  if (result.maintenance_advice?.priority_level === "高") return "danger";
  if (result.maintenance_advice?.priority_level === "中") return "warning";
  return "success";
});

marked.setOptions({
  breaks: true,
  gfm: true,
});

function prettyJson(data) {
  return JSON.stringify(data || {}, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "-")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(content) {
  const html = marked.parse(content || "");
  return DOMPurify.sanitize(html);
}

function todoStatusType(status) {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "in_progress") return "warning";
  return "info";
}

function scrollToBottom() {
  nextTick(() => {
    messagesEndRef.value?.scrollIntoView({ behavior: "smooth", block: "end" });
  });
}

function abortActiveStream(expected = false) {
  streamAbortExpected = streamAbortExpected || expected;
  activeStreamController?.abort();
}

function resetResult() {
  abortActiveStream(true);
  Object.assign(result, initialResult());
  messages.value = [{ ...welcomeMessage }];
  question.value = "";
  flowDialogVisible.value = false;
  statsDialogVisible.value = false;
  mapDialogVisible.value = false;
  mapMessage.value = "提交查询后，地图会高亮本次 Agent 选择的裂缝点位。";
  clearMapObjects(mapInstance, mapObjects);
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failures
  }
}

function markPageLeaving() {
  pageLeaving = true;
  abortActiveStream(true);
}

function isAbortLikeError(error) {
  const message = String(error?.message || "");
  return error?.name === "AbortError" || /abort|cancel|body stream|network/i.test(message);
}

function isExpectedStreamAbort(error) {
  return (pageLeaving || streamAbortExpected) && isAbortLikeError(error);
}

function isStreamAbortFailureContent(content) {
  const text = String(content || "");
  return /^查询失败：/i.test(text) && /abort|cancel|body stream/i.test(text);
}

function hasResultArtifacts(data) {
  return Boolean(
    data?.answer ||
      data?.todos?.length ||
      data?.tool_calls?.length ||
      Object.keys(data?.stats || {}).length ||
      data?.cracks?.length ||
      data?.images?.length ||
      Object.keys(data?.image_analysis || {}).length ||
      data?.map_geojson?.features?.length ||
      Object.keys(data?.maintenance_advice || {}).length,
  );
}

function serializeLocalState() {
  return {
    messages: messages.value,
    result: JSON.parse(JSON.stringify(result)),
    question: question.value,
    flowDialogVisible: flowDialogVisible.value,
    statsDialogVisible: statsDialogVisible.value,
    mapMessage: mapMessage.value,
  };
}

function persistState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(serializeLocalState()));
  } catch {
    // ignore storage failures
  }
}

async function restoreState() {
  let restored = null;
  try {
    restored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    restored = null;
  }
  if (!restored || typeof restored !== "object") return;

  if (Array.isArray(restored.messages) && restored.messages.length) {
    messages.value = restored.messages.map((message) => {
      if (message?.role === "assistant" && isStreamAbortFailureContent(message.content)) {
        return { ...message, content: "", actions: false };
      }
      return message;
    });
  }
  if (restored.result && typeof restored.result === "object") {
    Object.assign(result, initialResult(), restored.result);
  }
  question.value = typeof restored.question === "string" ? restored.question : "";
  flowDialogVisible.value = Boolean(restored.flowDialogVisible);
  statsDialogVisible.value = Boolean(restored.statsDialogVisible);
  mapMessage.value = typeof restored.mapMessage === "string"
    ? restored.mapMessage
    : "提交查询后，地图会高亮本次 Agent 选择的裂缝点位。";

  if (result.session_id) {
    try {
      const latest = await fetchAgentSession(result.session_id);
      Object.assign(result, initialResult(), latest);
      const assistantIndex = [...messages.value].map((item) => item.role).lastIndexOf("assistant");
      if (assistantIndex >= 0) {
        const existingContent = messages.value[assistantIndex]?.content || "";
        const restoredContent = isStreamAbortFailureContent(existingContent) ? "" : existingContent;
        patchAssistantMessage(assistantIndex, {
          content: latest.answer || restoredContent || "",
          actions: hasResultArtifacts(latest),
        });
      }
    } catch {
      // keep local snapshot when backend session fetch is unavailable
    }
  }
}

function severityColor(severity) {
  if (severity >= 3) return "#ef4444";
  if (severity >= 2) return "#f97316";
  return "#22c55e";
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
    frame_code: source.frame_code ?? fallback.frame_code ?? null,
    task_id: source.task_id ?? fallback.task_id ?? null,
    identity_code: source.identity_code ?? fallback.identity_code ?? null,
    crack_code: source.crack_code ?? fallback.crack_code ?? null,
    road_name: source.road_name ?? fallback.road_name ?? null,
    district: source.district ?? fallback.district ?? null,
    severity_level: source.severity_level ?? source.severity ?? fallback.severity_level ?? fallback.severity ?? null,
    severity_label: source.severity_label ?? fallback.severity_label ?? null,
    crack_type: source.crack_type ?? fallback.crack_type ?? null,
    length_m: source.length_m ?? fallback.length_m ?? null,
    avg_width_cm: source.avg_width_cm ?? fallback.avg_width_cm ?? null,
    max_width_cm: source.max_width_cm ?? fallback.max_width_cm ?? null,
    area_m2: source.area_m2 ?? fallback.area_m2 ?? null,
    longitude: source.longitude ?? fallback.longitude ?? null,
    latitude: source.latitude ?? fallback.latitude ?? null,
    risk_score: source.risk_score ?? fallback.risk_score ?? null,
    result_image_uri: source.result_image_uri ?? fallback.result_image_uri ?? null,
    original_image_uri: source.original_image_uri ?? fallback.original_image_uri ?? null,
    mask_image_uri: source.mask_image_uri ?? fallback.mask_image_uri ?? null,
    image_url: source.image_url ?? fallback.image_url ?? source.result_image_uri ?? fallback.result_image_uri ?? null,
    detected_at: source.detected_at ?? fallback.detected_at ?? null,
    lifecycle_status: source.lifecycle_status ?? fallback.lifecycle_status ?? null,
    maintenance_status: source.maintenance_status ?? fallback.maintenance_status ?? null,
    priority_level: source.priority_level ?? fallback.priority_level ?? null,
  };
}

function buildPopupPreviews(item, title) {
  return [
    { mode: "original", label: "原图", uri: item.original_image_uri, alt: `${title} 原图` },
    { mode: "overlay", label: "结果图", uri: item.result_image_uri, alt: `${title} 结果图` },
    { mode: "mask", label: "掩膜图", uri: item.mask_image_uri, alt: `${title} 掩膜图` },
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
      data-agent-preview="${groupKey}"
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
  const item = group.items[index] || group.items[0] || {};
  const title = escapeHtml(item.identity_code || item.crack_code || "裂缝点位");
  const controls = group.items.length > 1
    ? `
      <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:12px;">
        <button type="button" data-agent-popup="${group.key}" data-dir="-1" style="border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:4px 8px; cursor:pointer;">上一条</button>
        <span>${index + 1} / ${group.items.length}</span>
        <button type="button" data-agent-popup="${group.key}" data-dir="1" style="border:1px solid #cbd5e1; background:#fff; border-radius:6px; padding:4px 8px; cursor:pointer;">下一条</button>
      </div>
    `
    : "";
  const frameHint = item.frame_id
    ? `<div style="margin-top:10px; padding:8px 10px; border-radius:8px; background:${isFrameLoading ? "#fff7ed" : "#f8fafc"}; border:1px solid ${isFrameLoading ? "#fdba74" : "#e2e8f0"}; color:${isFrameLoading ? "#c2410c" : "#64748b"}; font-size:12px;">${isFrameLoading ? "正在加载同帧裂缝..." : `当前支持浏览同帧裂缝，共 ${group.items.length} 条`}</div>`
    : "";
  return `
    <div style="width: 390px; color:#1f2937; line-height:1.5;">
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
        <strong style="font-size:15px; color:#0f172a;">${title}</strong>
        ${item.frame_id ? `<span style="padding:2px 8px; border-radius:999px; background:#dbeafe; color:#1d4ed8; font-size:12px;">同帧 ${group.items.length} 条</span>` : group.items.length > 1 ? `<span style="padding:2px 8px; border-radius:999px; background:#dbeafe; color:#1d4ed8; font-size:12px;">同点 ${group.items.length} 条</span>` : ""}
      </div>
      <div style="display:grid; grid-template-columns:82px 1fr; column-gap:10px; row-gap:6px; margin-top:12px; font-size:13px;">
        <span style="color:#64748b;">道路名称</span>
        <span style="color:#0f172a; font-weight:600;">${escapeHtml(item.road_name || "-")}</span>
        <span style="color:#64748b;">行政区</span>
        <span>${escapeHtml(item.district || "-")}</span>
        <span style="color:#64748b;">经纬度</span>
        <span>${formatCoordinate(item.longitude)}, ${formatCoordinate(item.latitude)}</span>
        <span style="color:#64748b;">等级</span>
        <span>${escapeHtml(item.severity_label || "-")}</span>
        <span style="color:#64748b;">风险分</span>
        <span>${escapeHtml(item.risk_score ?? "-")}</span>
        <span style="color:#64748b;">裂缝类型</span>
        <span>${escapeHtml(item.crack_type || "-")}</span>
        <span style="color:#64748b;">长度</span>
        <span>${escapeHtml(Number(item.length_m || 0).toFixed(2))} m</span>
        <span style="color:#64748b;">宽度</span>
        <span>${escapeHtml(Number(item.width_mm || 0).toFixed(1))} mm</span>
        <span style="color:#64748b;">面积</span>
        <span>${escapeHtml(Number(item.area_m2 || 0).toFixed(4))} m²</span>
        <span style="color:#64748b;">发现时间</span>
        <span>${escapeHtml(formatPopupTime(item.detected_at))}</span>
        <span style="color:#64748b;">状态</span>
        <span>${escapeHtml([item.lifecycle_status, item.maintenance_status, item.priority_level].filter(Boolean).join(" / ") || "-")}</span>
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
          frame_id: frameDetail.id,
          frame_code: frameDetail.frame_code,
          task_id: frameDetail.task_id,
          original_image_uri: crack.original_image_uri || frameDetail.original_image_uri,
          result_image_uri: crack.result_image_uri || frameDetail.result_image_uri,
          mask_image_uri: crack.mask_image_uri || frameDetail.mask_image_uri,
          detected_at: frameDetail.captured_at,
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

  container.querySelectorAll("[data-agent-popup]").forEach((button) => {
    if (button.dataset.popupBound === "1") return;
    button.dataset.popupBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = button.getAttribute("data-agent-popup");
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

  container.querySelectorAll("[data-agent-preview]").forEach((button) => {
    if (button.dataset.popupBound === "1") return;
    button.dataset.popupBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = button.getAttribute("data-agent-preview");
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

function distanceMeters(from, to) {
  const fromLng = Number(from?.longitude);
  const fromLat = Number(from?.latitude);
  const toLng = Number(to?.longitude);
  const toLat = Number(to?.latitude);
  if (![fromLng, fromLat, toLng, toLat].every(Number.isFinite)) return Number.POSITIVE_INFINITY;
  const rad = Math.PI / 180;
  const earthRadius = 6371008.8;
  const dLat = (toLat - fromLat) * rad;
  const dLng = (toLng - fromLng) * rad;
  const lat1 = fromLat * rad;
  const lat2 = toLat * rad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * earthRadius * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function groupKey(index) {
  return `agent-marker-group-${index + 1}`;
}

function groupGeoJsonFeatures(features) {
  const groups = [];
  features.forEach((feature) => {
    const coordinates = feature?.geometry?.coordinates || [];
    const [longitude, latitude] = coordinates;
    const point = {
      longitude: Number(longitude),
      latitude: Number(latitude),
      properties: feature?.properties || {},
    };
    if (!Number.isFinite(point.longitude) || !Number.isFinite(point.latitude)) {
      return;
    }
    let group = groups.find((item) => distanceMeters(point, item) <= NEARBY_MARKER_CLUSTER_METERS);
    if (!group) {
      group = {
        key: groupKey(groups.length),
        longitude: point.longitude,
        latitude: point.latitude,
        severity: point.properties?.severity || 1,
        items: [],
      };
      groups.push(group);
    } else {
      const nextCount = group.items.length + 1;
      group.longitude = (group.longitude * group.items.length + point.longitude) / nextCount;
      group.latitude = (group.latitude * group.items.length + point.latitude) / nextCount;
    }
    group.items.push(point.properties);
    group.severity = Math.max(group.severity, feature?.properties?.severity || 1);
  });
  return groups;
}

async function initMap() {
  if (mapInstance || !mapRef.value) return Boolean(mapInstance);
  try {
    mapInstance = await createAmap(mapRef.value);
    AMapApi = window.AMap;
    return true;
  } catch (error) {
    mapMessage.value = error.message;
    ElMessage.error(error.message);
    return false;
  }
}

function renderGeoJson(geojson) {
  if (!mapInstance || !AMapApi) return;
  clearMapObjects(mapInstance, mapObjects);
  popupGroups.clear();

  const features = geojson?.features || [];
  if (!features.length) {
    mapMessage.value = "本次查询没有可展示的地图点位。";
    fitAmapBounds(mapInstance, []);
    return;
  }

  const groups = groupGeoJsonFeatures(features);
  const positions = [];
  groups.forEach((group) => {
    const normalizedGroup = {
      ...group,
      items: group.items.map((item) => normalizePopupItem(item)),
    };
    const initialPreview = resolvePreviewMode(normalizedGroup.items[0] || {}, "overlay");
    const position = wgs84ToGcj02(group.longitude, group.latitude);
    const markerSize = group.items.length > 1 ? 28 : group.severity >= 3 ? 22 : 18;
    const marker = new AMapApi.Marker({
      position,
      content: markerContent(severityColor(group.severity), markerSize, group.items.length),
      anchor: "center",
      zIndex: 100 + group.severity + group.items.length,
    });
    const infoWindow = new AMapApi.InfoWindow({
      content: popupHtml(normalizedGroup, 0, initialPreview),
      offset: new AMapApi.Pixel(0, -14),
      anchor: "bottom-center",
    });
    popupGroups.set(group.key, {
      marker,
      infoWindow,
      group: normalizedGroup,
      index: 0,
      preview: initialPreview,
      isFrameLoading: false,
      hasLoadedFrameItems: false,
    });
    marker.on("click", () => {
      const state = popupGroups.get(group.key);
      if (state) {
        renderPopupState(state);
      }
      infoWindow.open(mapInstance, position);
      setTimeout(() => {
        attachPopupInteractions(document);
      }, 0);
      if (state) {
        void ensureFrameItems(state);
      }
    });
    marker.setMap(mapInstance);
    mapObjects.push(marker);
    positions.push(position);
  });

  fitAmapBounds(mapInstance, positions, undefined, mapObjects);
  mapMessage.value = groups.length < features.length
    ? `本次查询已在地图中高亮 ${features.length} 个裂缝点位，近距离聚合为 ${groups.length} 个标记。`
    : `本次查询已在地图中高亮 ${features.length} 个裂缝点位。`;
}

async function handleMapOpened() {
  await nextTick();
  const ready = await initMap();
  if (ready) {
    mapInstance?.resize();
    renderGeoJson(result.map_geojson);
  }
}

function openMapDialog() {
  mapDialogVisible.value = true;
}

async function submitQuery() {
  const userText = question.value.trim();
  if (!userText) {
    ElMessage.warning("请先输入问题");
    return;
  }

  pageLeaving = false;
  streamAbortExpected = false;
  Object.assign(result, initialResult(), { query: userText });
  messages.value.push({ role: "user", content: userText });
  const assistantIndex = messages.value.length;
  messages.value.push({
    role: "assistant",
    content: "",
    thinking: "",
    statusLog: "",
    actions: false,
  });
  question.value = "";
  loading.value = true;
  scrollToBottom();

  try {
    await runAgentQueryStream(userText, assistantIndex);
  } catch (error) {
    if (isExpectedStreamAbort(error)) {
      return;
    }
    const message = error?.message || "未知错误";
    patchAssistantMessage(assistantIndex, {
      content: `查询失败：${message}`,
    });
    ElMessage.error(message);
  } finally {
    loading.value = false;
    scrollToBottom();
  }
}

function patchAssistantMessage(index, patch) {
  const current = messages.value[index];
  if (!current) return;
  messages.value[index] = {
    ...current,
    ...patch,
  };
}

function appendAssistantField(index, field, value) {
  const current = messages.value[index];
  if (!current) return;
  messages.value[index] = {
    ...current,
    [field]: `${current[field] || ""}${value}`,
  };
}

async function runAgentQueryStream(userText, assistantIndex) {
  const controller = new AbortController();
  activeStreamController = controller;

  try {
    const response = await fetch(`${API_BASE_URL}${AGENT_STREAM_URL}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      signal: controller.signal,
      body: JSON.stringify({ query: userText }),
    });

    if (!response.ok || !response.body) {
      const fallback = await runAgentQuery({ query: userText });
      Object.assign(result, initialResult(), fallback);
      patchAssistantMessage(assistantIndex, {
        content: fallback.answer || "已完成查询，但模型未返回文本回答。",
        actions: true,
      });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        handleStreamBlock(part, assistantIndex);
      }
      scrollToBottom();
    }
    if (buffer.trim()) {
      handleStreamBlock(buffer, assistantIndex);
    }
  } finally {
    if (activeStreamController === controller) {
      activeStreamController = null;
    }
  }
}

function handleStreamBlock(block, assistantIndex) {
  const lines = block
    .split("\n")
    .filter((item) => item.startsWith("data:"))
    .map((item) => item.replace(/^data:\s*/, ""));
  if (!lines.length) return;
  const raw = lines.join("\n");
  if (!raw || raw === "[DONE]") return;

  let event;
  try {
    event = JSON.parse(raw);
  } catch {
    return;
  }

  if (event.type === "session") {
    if (event.session_id) {
      result.session_id = event.session_id;
    }
    result.query = result.query || messages.value[assistantIndex - 1]?.content || "";
    result.debug = {
      ...(result.debug || {}),
      llm_mode: event.llm_mode || result.debug?.llm_mode,
      status: "running",
    };
    return;
  }
  if (event.type === "thinking_delta") {
    appendAssistantField(assistantIndex, "thinking", event.content || "");
    return;
  }
  if (event.type === "thinking_step" || event.type === "tool_result") {
    const text = event.content || "";
    if (!text) return;
    const current = messages.value[assistantIndex]?.statusLog || "";
    const prefix = current && !current.endsWith("\n") ? "\n" : "";
    appendAssistantField(assistantIndex, "statusLog", `${prefix}· ${text}\n`);
    return;
  }
  if (event.type === "answer_delta") {
    appendAssistantField(assistantIndex, "content", event.content || "");
    return;
  }
  if (event.type === "reasoning_answer_delta") {
    appendAssistantField(assistantIndex, "content", event.content || "");
    return;
  }
  if (event.type === "final" && event.data) {
    Object.assign(result, initialResult(), event.data);
    const currentContent = messages.value[assistantIndex]?.content || "";
    patchAssistantMessage(assistantIndex, {
      content: currentContent.trim()
        ? currentContent
        : event.data.answer || "已完成查询，但模型未返回文本回答。",
      actions: true,
    });
    return;
  }
  if (event.type === "error") {
    patchAssistantMessage(assistantIndex, {
      content: `查询失败：${event.content || "未知错误"}`,
    });
  }
}

watch(
  () => result.map_geojson,
  (value) => {
    if (mapDialogVisible.value && mapInstance) {
      renderGeoJson(value);
    }
  },
  { deep: true },
);

watch(
  [messages, question, flowDialogVisible, statsDialogVisible, mapDialogVisible, mapMessage, () => result],
  () => {
    persistState();
  },
  { deep: true },
);

onMounted(async () => {
  window.addEventListener("pagehide", markPageLeaving);
  window.addEventListener("beforeunload", markPageLeaving);
  await restoreState();
  scrollToBottom();
});

onBeforeUnmount(() => {
  markPageLeaving();
  window.removeEventListener("pagehide", markPageLeaving);
  window.removeEventListener("beforeunload", markPageLeaving);
  if (mapInstance) {
    clearMapObjects(mapInstance, mapObjects);
    mapInstance.destroy();
    mapInstance = null;
    AMapApi = null;
  }
});
</script>

<style scoped>
.chat-page {
  min-height: calc(100vh - 62px);
  display: flex;
}

.chat-panel {
  width: 100%;
  min-height: calc(100vh - 62px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}

.chat-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 22px;
}

.chat-title h1 {
  margin: 0;
  color: #0f172a;
  font-size: 20px;
}

.chat-title p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.chat-body {
  flex: 1;
  min-height: 420px;
  padding: 24px;
  overflow-y: auto;
  background: #f8fafc;
}

.message-row {
  display: flex;
  gap: 14px;
  margin-bottom: 20px;
}

.message-row.is-user {
  flex-direction: row-reverse;
}

.message-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-weight: 800;
}

.message-row.is-user .message-avatar {
  background: #2563eb;
}

.message-stack {
  max-width: min(760px, 78%);
}

.message-row.is-user .message-stack {
  align-items: flex-end;
}

.message-bubble {
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  border-top-left-radius: 4px;
  background: #fff;
  color: #0f172a;
  line-height: 1.8;
  white-space: pre-wrap;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.message-bubble.is-markdown {
  white-space: normal;
}

.thinking-box {
  margin-bottom: 10px;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f1f5f9;
  color: #475569;
}

.thinking-box.is-thinking {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.thinking-title {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.thinking-box pre {
  max-height: 180px;
  margin: 8px 0 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.7;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 0 0 12px;
  color: #0f172a;
}

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(table),
.markdown-body :deep(blockquote) {
  margin: 0 0 12px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
}

.markdown-body :deep(li + li) {
  margin-top: 4px;
}

.markdown-body :deep(code) {
  padding: 2px 6px;
  border-radius: 6px;
  background: #eff1f5;
  font-size: 0.92em;
}

.markdown-body :deep(pre) {
  margin: 0 0 12px;
  padding: 12px;
  overflow: auto;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 8px 10px;
  border: 1px solid #dbe3ee;
  text-align: left;
  vertical-align: top;
}

.markdown-body :deep(th) {
  background: #f8fafc;
  color: #334155;
}

.markdown-body :deep(blockquote) {
  padding-left: 12px;
  border-left: 3px solid #cbd5e1;
  color: #475569;
}

.message-row.is-user .message-bubble {
  border-color: #2563eb;
  border-top-left-radius: 18px;
  border-top-right-radius: 4px;
  background: #2563eb;
  color: #fff;
}

.message-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.typing-bubble {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  border-top-left-radius: 4px;
  background: #fff;
}

.typing-bubble span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #94a3b8;
  animation: bounce 1.1s infinite ease-in-out;
}

.typing-bubble span:nth-child(2) {
  animation-delay: 0.16s;
}

.typing-bubble span:nth-child(3) {
  animation-delay: 0.32s;
}

@keyframes bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.55;
  }

  40% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

.chat-foot {
  padding: 16px 18px;
  border-top: 1px solid #e2e8f0;
  background: #fff;
}

.quick-prompts {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.quick-prompts span {
  color: #94a3b8;
  font-size: 12px;
}

.quick-prompts button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  font-size: 12px;
  cursor: pointer;
}

.quick-prompts button:hover {
  text-decoration: underline;
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px;
  align-items: stretch;
  gap: 12px;
}

.send-button {
  height: auto;
  min-height: 48px;
}

.flow-dialog {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
  gap: 18px;
}

.dialog-section-head,
.tool-title,
.todo-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.dialog-section-head {
  margin-bottom: 14px;
}

.dialog-section-head h2 {
  margin: 0;
  color: #0f172a;
  font-size: 16px;
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.todo-item {
  display: flex;
  gap: 12px;
  padding: 14px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.todo-item.is-completed {
  border-color: #86efac;
}

.todo-item.is-in_progress {
  border-color: #fdba74;
}

.todo-item.is-failed {
  border-color: #fca5a5;
}

.todo-index {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #dbeafe;
  color: #2563eb;
  font-weight: 700;
}

.todo-main {
  flex: 1;
}

.todo-content {
  color: #334155;
  line-height: 1.7;
}

.tool-title {
  width: 100%;
}

.tool-body {
  display: grid;
  gap: 14px;
}

.mini-title {
  margin: 0 0 8px;
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.stat-box {
  padding: 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.stat-box span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.stat-box strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 24px;
}

.stats-descriptions,
.advice-block {
  margin-top: 18px;
}

.advice-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.advice-metric {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f8fbff;
  border: 1px solid #dbeafe;
}

.advice-metric span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.advice-metric strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 18px;
}

.summary-copy {
  margin: 0;
  color: #334155;
  line-height: 1.9;
  white-space: pre-wrap;
}

.basis-copy {
  margin: 10px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.7;
}

.action-list {
  margin: 12px 0 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.8;
}

.dialog-map {
  width: 100%;
  height: min(62vh, 560px);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.map-note {
  margin: 12px 0 0;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 1080px) {
  .flow-dialog,
  .stats-grid,
  .advice-metrics {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .chat-page,
  .chat-panel {
    min-height: calc(100vh - 40px);
  }

  .chat-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .message-stack {
    max-width: calc(100% - 54px);
  }

  .composer {
    grid-template-columns: 1fr;
  }

  .send-button {
    min-height: 42px;
  }
}
</style>
