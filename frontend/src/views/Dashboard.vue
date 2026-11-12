<template>
  <div class="page-shell dashboard-shell">
    <div class="page-header">
      <div>
        <h1 class="page-title">首页看板</h1>
        <p class="page-subtitle">道路裂缝、复检档案与帧级检测结果汇总。</p>
      </div>
      <el-button type="primary" :icon="Refresh" @click="loadStatistics" :loading="loading">刷新数据</el-button>
    </div>

    <section class="surface overview-band">
      <div class="overview-main">
        <span>当前裂缝档案</span>
        <strong>{{ statistics.total_cracks }}</strong>
        <p>{{ statistics.total_observations }} 条观测记录 / {{ statistics.total_frames }} 帧检测图像</p>
      </div>
      <div class="overview-metrics">
        <div v-for="item in summaryCards" :key="item.label" class="overview-item">
          <el-icon :class="item.tone"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.foot }}</small>
        </div>
      </div>
    </section>

    <div class="dashboard-grid">
      <section class="surface section-card risk-panel">
        <div class="section-head">
          <div>
            <h2 class="section-title">裂缝风险占比</h2>
            <p class="meta-text">按当前裂缝档案严重度统计。</p>
          </div>
          <el-tag type="danger" effect="plain">{{ statistics.severe_count }} 严重</el-tag>
        </div>

        <div v-if="severitySegments.length" class="donut-block risk-donut-block">
          <div class="donut-shell" @mouseleave="severityHover = null">
            <div class="donut large">
              <svg class="donut-svg" viewBox="0 0 120 120" role="img" aria-label="裂缝风险占比">
                <circle class="donut-track" cx="60" cy="60" :r="LARGE_DONUT.radius" :stroke-width="LARGE_DONUT.stroke" />
                <circle
                  v-for="item in severityDonutSlices"
                  :key="item.label"
                  class="donut-slice"
                  cx="60"
                  cy="60"
                  :r="LARGE_DONUT.radius"
                  :stroke-width="LARGE_DONUT.stroke"
                  :stroke="item.color"
                  :stroke-dasharray="item.dashArray"
                  :stroke-dashoffset="item.dashOffset"
                  tabindex="0"
                  @mouseenter="severityHover = item"
                  @focus="severityHover = item"
                  @blur="severityHover = null"
                />
              </svg>
              <div class="donut-core">
                <strong>{{ severityTotal }}</strong>
                <span>总计</span>
              </div>
            </div>
          </div>
          <div class="chart-detail-card">
            <template v-if="severityHover">
              <span class="detail-kicker">风险等级</span>
              <strong>{{ severityHover.label }}</strong>
              <p>{{ severityHover.value }} 条</p>
              <em>{{ severityHover.percent }}%</em>
            </template>
            <template v-else>
              <span class="detail-kicker">风险分层</span>
              <strong>{{ severitySegments.length }} 类</strong>
              <p>{{ severityTotal }} 条裂缝档案</p>
              <em>{{ statistics.severe_count }} 条严重</em>
            </template>
          </div>
        </div>
        <div v-else class="empty-state">暂无裂缝风险数据。</div>
      </section>

      <section class="surface section-card road-panel">
        <div class="section-head">
          <div>
            <h2 class="section-title">道路裂缝数占比</h2>
            <p class="meta-text">按道路聚合裂缝数量。</p>
          </div>
          <el-tag type="info" effect="plain">{{ statistics.road_count }} 条道路</el-tag>
        </div>

        <div v-if="roadSegments.length" class="road-chart stacked-chart">
          <div class="donut-shell" @mouseleave="roadHover = null">
            <div class="donut small">
              <svg class="donut-svg" viewBox="0 0 120 120" role="img" aria-label="道路裂缝数占比">
                <circle class="donut-track" cx="60" cy="60" :r="SMALL_DONUT.radius" :stroke-width="SMALL_DONUT.stroke" />
                <circle
                  v-for="item in roadDonutSlices"
                  :key="item.label"
                  class="donut-slice"
                  cx="60"
                  cy="60"
                  :r="SMALL_DONUT.radius"
                  :stroke-width="SMALL_DONUT.stroke"
                  :stroke="item.color"
                  :stroke-dasharray="item.dashArray"
                  :stroke-dashoffset="item.dashOffset"
                  tabindex="0"
                  @mouseenter="roadHover = item"
                  @focus="roadHover = item"
                  @blur="roadHover = null"
                />
              </svg>
              <div class="donut-core">
                <strong>{{ roadTotal }}</strong>
                <span>道路裂缝</span>
              </div>
            </div>
          </div>
          <div class="chart-detail-card road-detail-card">
            <template v-if="roadHover">
              <span class="detail-kicker">道路名称</span>
              <strong>{{ roadHover.label }}</strong>
              <p>{{ roadHover.value }} 条</p>
              <em>{{ roadHover.percent }}%</em>
            </template>
            <template v-else>
              <span class="detail-kicker">统计范围</span>
              <strong>前 {{ roadSegments.length }} 条道路</strong>
              <p>{{ roadTotal }} 条裂缝</p>
              <em>{{ statistics.road_count }} 条道路已覆盖</em>
            </template>
          </div>
        </div>
        <div v-else class="empty-state">暂无道路统计。</div>
      </section>

      <section class="surface section-card state-panel">
        <div class="section-head">
          <div>
            <h2 class="section-title">复检档案状态</h2>
            <p class="meta-text">身份档案生命周期分布。</p>
          </div>
          <el-tag type="primary" effect="plain">{{ statistics.active_identity_count }} 活跃</el-tag>
        </div>
        <div v-if="identitySegments.length" class="state-content">
          <div class="state-meter-card">
            <div class="state-meter">
              <span
                v-for="item in identitySegments"
                :key="item.label"
                :style="{ width: `${item.percent}%`, background: item.color }"
              />
            </div>
            <div class="state-meter-copy">
              <strong>{{ identityTotal }}</strong>
              <span>档案总数</span>
            </div>
          </div>
          <div class="state-list">
            <div v-for="item in identitySegments" :key="item.label">
              <span class="legend-dot" :style="{ background: item.color }" />
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <em>{{ item.percent }}%</em>
            </div>
          </div>
        </div>
        <div v-else class="empty-state compact">暂无身份档案状态。</div>

        <div class="task-split">
          <div>
            <span>已完成任务</span>
            <strong>{{ statistics.finished_task_count }}</strong>
          </div>
          <div>
            <span>任务总数</span>
            <strong>{{ statistics.task_count }}</strong>
          </div>
        </div>
      </section>
    </div>

    <section class="surface section-card recent-panel">
      <div class="section-head">
        <div>
          <h2 class="section-title">最近裂缝记录</h2>
          <p class="meta-text">最新写入数据库的检测结果。</p>
        </div>
        <el-tag type="info" effect="plain">{{ statistics.recent_cracks.length }} 条</el-tag>
      </div>
      <el-table v-if="statistics.recent_cracks.length" :data="statistics.recent_cracks" stripe style="width: 100%">
        <el-table-column prop="crack_code" label="编号" min-width="150" />
        <el-table-column prop="road_name" label="道路" min-width="130" />
        <el-table-column prop="crack_type" label="类型" min-width="130" />
        <el-table-column prop="severity_label" label="风险等级" min-width="110">
          <template #default="{ row }">
            <span :class="['risk-tag', severityClass(row.severity_level)]">{{ row.severity_label }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="length_m" label="长度(m)" min-width="100" />
        <el-table-column prop="area_m2" label="面积(m²)" min-width="100" />
      </el-table>
      <div v-else class="empty-state">暂无裂缝数据。</div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Aim, DataLine, Finished, Picture, Refresh } from "@element-plus/icons-vue";

import { fetchCrackStatistics } from "../api/modules";

const loading = ref(false);
const statistics = reactive({
  total_cracks: 0,
  total_observations: 0,
  total_identities: 0,
  total_frames: 0,
  active_identity_count: 0,
  repaired_identity_count: 0,
  recurred_identity_count: 0,
  severe_count: 0,
  medium_count: 0,
  minor_count: 0,
  road_count: 0,
  task_count: 0,
  finished_task_count: 0,
  recent_cracks: [],
  road_breakdown: [],
});

const chartPalette = ["#2563eb", "#f97316", "#16a34a", "#dc2626", "#0891b2", "#7c3aed"];
const LARGE_DONUT = { radius: 44, stroke: 18 };
const SMALL_DONUT = { radius: 40, stroke: 16 };
const severityHover = ref(null);
const roadHover = ref(null);

const summaryCards = computed(() => [
  { label: "身份档案", value: statistics.total_identities, foot: "可追踪裂缝单体", icon: DataLine, tone: "is-blue" },
  { label: "检测帧", value: statistics.total_frames, foot: "帧级图像证据", icon: Picture, tone: "is-green" },
  { label: "覆盖道路", value: statistics.road_count, foot: "道路维度聚合", icon: Aim, tone: "is-orange" },
  { label: "完成任务", value: statistics.finished_task_count, foot: `共 ${statistics.task_count} 个`, icon: Finished, tone: "is-slate" },
]);

const severityTotal = computed(() => statistics.severe_count + statistics.medium_count + statistics.minor_count);
const severitySegments = computed(() =>
  buildSegments(
    [
      { label: "严重", value: statistics.severe_count, color: "#dc2626" },
      { label: "中等", value: statistics.medium_count, color: "#f97316" },
      { label: "轻微", value: statistics.minor_count, color: "#16a34a" },
    ],
    severityTotal.value,
  ),
);
const severityDonutSlices = computed(() => buildDonutSlices(severitySegments.value, LARGE_DONUT.radius));

const roadTotal = computed(() => statistics.road_breakdown.reduce((sum, item) => sum + Number(item.crack_count || 0), 0));
const roadSegments = computed(() =>
  buildSegments(
    statistics.road_breakdown.slice(0, 6).map((item, index) => ({
      label: item.road_name,
      value: Number(item.crack_count || 0),
      color: chartPalette[index % chartPalette.length],
    })),
    roadTotal.value,
  ),
);
const roadDonutSlices = computed(() => buildDonutSlices(roadSegments.value, SMALL_DONUT.radius));

const identityTotal = computed(
  () => statistics.active_identity_count + statistics.repaired_identity_count + statistics.recurred_identity_count,
);
const identitySegments = computed(() =>
  buildSegments(
    [
      { label: "活跃", value: statistics.active_identity_count, color: "#2563eb" },
      { label: "已修复", value: statistics.repaired_identity_count, color: "#16a34a" },
      { label: "复发", value: statistics.recurred_identity_count, color: "#dc2626" },
    ],
    identityTotal.value,
  ),
);

function buildSegments(items, total) {
  if (!total) return [];
  return items
    .filter((item) => item.value > 0)
    .map((item) => ({
      ...item,
      ratio: item.value / total,
      percent: Number(((item.value / total) * 100).toFixed(1)),
    }));
}

function buildDonutSlices(segments, radius) {
  if (!segments.length) return [];
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return segments.map((item) => {
    const length = circumference * item.ratio;
    const slice = {
      ...item,
      dashArray: `${length} ${Math.max(circumference - length, 0)}`,
      dashOffset: `${-offset}`,
    };
    offset += length;
    return slice;
  });
}

async function loadStatistics() {
  loading.value = true;
  try {
    const data = await fetchCrackStatistics();
    Object.assign(statistics, data);
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    loading.value = false;
  }
}

function severityClass(level) {
  if (level === 3) return "is-severe";
  if (level === 2) return "is-medium";
  return "is-minor";
}

onMounted(loadStatistics);
</script>

<style scoped>
.dashboard-shell {
  gap: 20px;
}

.overview-band {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  padding: 20px;
}

.overview-main {
  min-height: 180px;
  padding: 22px;
  border-radius: 8px;
  background: #0f172a;
  color: #fff;
}

.overview-main span,
.overview-main p {
  color: #cbd5e1;
}

.overview-main span {
  font-size: 14px;
}

.overview-main strong {
  display: block;
  margin-top: 18px;
  font-size: 58px;
  line-height: 1;
}

.overview-main p {
  margin: 18px 0 0;
  font-size: 13px;
}

.overview-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.overview-item {
  display: grid;
  align-content: start;
  min-width: 0;
  padding: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.overview-item .el-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  margin-bottom: 16px;
  border-radius: 8px;
  font-size: 22px;
}

.overview-item span {
  color: #64748b;
  font-size: 13px;
}

.overview-item strong {
  margin-top: 8px;
  color: #0f172a;
  font-size: 30px;
  line-height: 1;
}

.overview-item small {
  margin-top: 10px;
  color: #2563eb;
  font-size: 12px;
}

.is-blue {
  color: #2563eb;
  background: #dbeafe;
}

.is-green {
  color: #16a34a;
  background: #dcfce7;
}

.is-orange {
  color: #ea580c;
  background: #ffedd5;
}

.is-slate {
  color: #475569;
  background: #e2e8f0;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  align-items: stretch;
}

.risk-panel,
.road-panel,
.state-panel {
  min-width: 0;
  display: grid;
  align-content: start;
}

.donut-block,
.road-chart {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 22px;
}

.risk-donut-block {
  grid-template-columns: 1fr;
  justify-items: center;
  align-content: start;
  gap: 16px;
}

.stacked-chart {
  grid-template-columns: 1fr;
  justify-items: center;
  align-content: start;
  gap: 18px;
}

.risk-donut-block .chart-detail-card,
.stacked-chart .chart-detail-card {
  width: 100%;
  max-width: 320px;
}

.donut-shell {
  display: grid;
  place-items: center;
}

.donut {
  position: relative;
  flex: 0 0 auto;
}

.donut.large {
  width: 210px;
  height: 210px;
}

.donut.small {
  width: 154px;
  height: 154px;
}

.donut-svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
  overflow: visible;
}

.donut-track,
.donut-slice {
  fill: none;
}

.donut-track {
  stroke: #e2e8f0;
}

.donut-slice {
  cursor: pointer;
  transition: opacity 0.18s ease, stroke-width 0.18s ease;
  stroke-linecap: butt;
}

.donut-slice:hover,
.donut-slice:focus {
  opacity: 0.88;
  outline: none;
}

.donut-core::before {
  content: "";
  position: absolute;
  inset: 34px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 0 1px #e2e8f0;
  z-index: -1;
}

.donut.small .donut-core::before {
  inset: 28px;
}

.donut-core {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-content: center;
  text-align: center;
  pointer-events: none;
}

.chart-detail-card {
  display: grid;
  align-content: center;
  min-height: 132px;
  padding: 18px 20px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.detail-kicker {
  color: #64748b;
  font-size: 12px;
}

.chart-detail-card strong {
  margin-top: 8px;
  color: #0f172a;
  font-size: 22px;
  line-height: 1.2;
}

.chart-detail-card p,
.chart-detail-card em {
  margin: 8px 0 0;
  color: #334155;
  font-style: normal;
}

.chart-detail-card em {
  color: #64748b;
  font-size: 12px;
}

.donut-core strong {
  color: #0f172a;
  font-size: 30px;
  line-height: 1;
}

.donut-core span {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.state-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.state-list strong {
  color: #0f172a;
  font-size: 13px;
}

.state-list em {
  color: #64748b;
  font-style: normal;
  font-size: 12px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.state-content {
  display: grid;
  gap: 16px;
}

.state-meter-card {
  display: grid;
  gap: 14px;
  padding: 16px 18px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.state-meter {
  display: flex;
  width: 100%;
  height: 24px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.state-meter span {
  min-width: 2px;
}

.state-meter-copy {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.state-meter-copy strong {
  color: #0f172a;
  font-size: 28px;
  line-height: 1;
}

.state-meter-copy span {
  color: #64748b;
  font-size: 12px;
}

.state-list div {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  color: #334155;
  font-size: 14px;
}

.task-split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 22px;
}

.task-split div {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.task-split span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.task-split strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 26px;
}

.empty-state.compact {
  padding: 20px 12px;
}

@media (max-width: 1440px) {
  .overview-band,
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .overview-band {
    grid-template-columns: 1fr;
  }

  .dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .state-panel {
    grid-column: span 2;
  }
}

@media (max-width: 980px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .state-panel {
    grid-column: auto;
  }
}

@media (max-width: 760px) {
  .overview-metrics,
  .donut-block,
  .road-chart,
  .task-split {
    grid-template-columns: 1fr;
  }

  .donut.large,
  .donut.small {
    justify-self: center;
  }
}
</style>
