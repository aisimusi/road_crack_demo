<template>
  <div class="page-shell frame-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">裂缝列表</h1>
        <p class="page-subtitle">分为帧级检测图像与裂缝级复检匹配结果：前者看每一帧证据，后者看同一裂缝身份、状态与更新。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="reloadAll">刷新数据</el-button>
    </div>

    <div class="frame-summary">
      <div v-for="item in summaryStats" :key="item.label" class="surface frame-stat">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <p>{{ item.copy }}</p>
      </div>
    </div>

    <div class="frame-browser">
      <aside class="surface section-card browser-column road-column">
        <div class="column-head">
          <div>
            <h2 class="section-title">道路</h2>
            <p class="meta-text">{{ roads.length }} 条道路</p>
          </div>
        </div>
        <el-input v-model="roadKeyword" clearable placeholder="搜索道路" :prefix-icon="Search" />
        <div v-if="filteredRoads.length" class="road-list">
          <button
            v-for="road in filteredRoads"
            :key="roadKey(road)"
            :class="['road-item', { active: isSelectedRoad(road) }]"
            type="button"
            @click="selectRoad(road)"
          >
            <span>
              <strong>{{ road.road_name }}</strong>
              <small>{{ road.district }}</small>
            </span>
            <em>{{ road.frame_count }} 帧 / {{ road.crack_count }} 条</em>
          </button>
        </div>
        <div v-else class="empty-state">暂无道路检测数据。</div>
      </aside>

      <aside class="surface section-card browser-column date-column">
        <div class="column-head">
          <div>
            <h2 class="section-title">巡检日期</h2>
            <p class="meta-text">{{ selectedRoad ? selectedRoad.road_name : "未选择道路" }}</p>
          </div>
        </div>
        <div v-if="dates.length" class="date-list">
          <button
            v-for="item in dates"
            :key="item.task_id"
            :class="['date-item', { active: selectedDate?.task_id === item.task_id }]"
            type="button"
            @click="selectDate(item)"
          >
            <span>
              <strong>{{ item.detected_date }}</strong>
              <small>{{ item.task_name }}</small>
            </span>
            <em>{{ taskTypeLabel(item.task_type) }}</em>
            <b>{{ item.frame_count }} 帧</b>
            <b>{{ item.crack_count }} 条观测</b>
          </button>
        </div>
        <div v-else class="empty-state">暂无巡检日期。</div>
      </aside>

      <main class="surface section-card frame-workspace" v-loading="workspaceLoading">
        <div class="workspace-head">
          <div>
            <h2 class="section-title">{{ workspaceTitle }}</h2>
            <p class="meta-text">{{ workspaceSubtitle }}</p>
          </div>
          <el-radio-group v-model="activeResultMode" class="result-mode-switch" size="large">
            <el-radio-button label="frames">帧级检测结果</el-radio-button>
            <el-radio-button label="identities">裂缝级复检匹配</el-radio-button>
          </el-radio-group>
        </div>

        <template v-if="activeResultMode === 'frames'">
          <div class="workspace-toolbar">
            <p class="mode-note">按视频帧展示 CrackMamba 分割结果、帧内裂缝数量与图像证据。</p>
            <el-select v-model="frameSeverityFilter" clearable placeholder="严重度" class="severity-select">
              <el-option label="轻微" :value="1" />
              <el-option label="中等" :value="2" />
              <el-option label="严重" :value="3" />
            </el-select>
          </div>

          <div v-if="displayedFrames.length" class="frame-grid">
            <article v-for="frame in displayedFrames" :key="frame.id" class="frame-card">
              <div class="frame-thumb-wrap">
                <img class="frame-thumb" :src="assetUrl(frame.result_image_uri)" :alt="`${frame.frame_code} overlay`" />
                <span :class="['risk-tag', severityClass(frame.max_severity_level)]">{{ frame.max_severity_label }}</span>
              </div>
              <div class="frame-card-body">
                <div>
                  <strong>{{ frame.frame_code }}</strong>
                  <span>{{ formatTime(frame.captured_at) }}</span>
                </div>
                <dl>
                  <div>
                    <dt>裂缝数</dt>
                    <dd>{{ frame.crack_count }}</dd>
                  </div>
                  <div>
                    <dt>总面积</dt>
                    <dd>{{ formatArea(frame.total_area_m2) }} m²</dd>
                  </div>
                  <div>
                    <dt>视频时间</dt>
                    <dd>{{ Number(frame.elapsed_seconds || 0).toFixed(2) }} s</dd>
                  </div>
                </dl>
                <el-button type="primary" plain @click="openFrameDetail(frame.id)">查看帧图像</el-button>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无匹配的帧级检测数据。</div>

          <div class="frame-pagination">
            <span class="meta-text">共 {{ framePagination.total }} 帧，每页 10 条</span>
            <el-pagination
              background
              layout="prev, pager, next"
              :current-page="framePagination.page"
              :page-size="framePagination.page_size"
              :total="framePagination.total"
              :hide-on-single-page="framePagination.total <= framePagination.page_size"
              @current-change="changeFramePage"
            />
          </div>
        </template>

        <template v-else>
          <div class="workspace-toolbar identity-toolbar">
            <div class="identity-overview">
              <span><strong>{{ filteredIdentities.length }}</strong> 条身份结果</span>
              <span><strong>{{ visibleIdentityStats.matched }}</strong> 条匹配历史裂缝</span>
              <span><strong>{{ visibleIdentityStats.newInTask }}</strong> 条本批新增</span>
              <span><strong>{{ visibleIdentityStats.changed }}</strong> 条发生尺寸变化</span>
            </div>
            <div class="identity-filters">
              <el-select v-model="identitySeverityFilter" clearable placeholder="严重度" class="severity-select">
                <el-option label="轻微" :value="1" />
                <el-option label="中等" :value="2" />
                <el-option label="严重" :value="3" />
              </el-select>
              <el-select v-model="identityLifecycleFilter" clearable placeholder="身份状态" class="status-select">
                <el-option label="活跃" value="active" />
                <el-option label="已修复" value="repaired" />
                <el-option label="复发" value="recurred" />
                <el-option label="归档" value="archived" />
              </el-select>
            </div>
          </div>

          <div v-if="selectedDate && !isSelectedReviewTask" class="mode-hint">
            当前批次是普通巡检，裂缝级结果主要表示新建/更新后的身份档案；选择“复检”任务时会重点展示特征匹配和状态更新。
          </div>

          <div v-if="filteredIdentities.length" class="identity-grid">
            <article v-for="identity in filteredIdentities" :key="identity.id" class="identity-card">
              <div class="identity-image">
                <img
                  v-if="identity.latest_result_image_uri"
                  :src="assetUrl(identity.latest_result_image_uri)"
                  :alt="`${identity.identity_code} 最新检测图`"
                />
                <div v-else class="image-placeholder">暂无最新图像</div>
                <span :class="['risk-tag', severityClass(identity.current_severity_level)]">
                  {{ identity.current_severity_label }}
                </span>
              </div>

              <div class="identity-body">
                <div class="identity-title-row">
                  <div>
                    <strong>{{ identity.identity_code }}</strong>
                    <span>{{ identity.road_name }} · {{ identity.crack_type }}</span>
                  </div>
                  <span :class="['status-pill', lifecycleClass(identity.lifecycle_status)]">
                    {{ lifecycleLabel(identity.lifecycle_status) }}
                  </span>
                </div>

                <div class="match-banner">
                  <span :class="['match-dot', matchClass(identity)]" />
                  <div>
                    <strong>{{ matchStatusLabel(identity) }}</strong>
                    <p>{{ matchStatusCopy(identity) }}</p>
                  </div>
                </div>

                <dl class="identity-metrics">
                  <div>
                    <dt>观测次数</dt>
                    <dd>{{ identity.observation_count }}</dd>
                  </div>
                  <div>
                    <dt>面积变化</dt>
                    <dd :class="growthClass(identity.growth_area_m2)">{{ formatSigned(identity.growth_area_m2, 4) }} m²</dd>
                  </div>
                  <div>
                    <dt>长度变化</dt>
                    <dd :class="growthClass(identity.growth_length_m)">{{ formatSigned(identity.growth_length_m, 3) }} m</dd>
                  </div>
                </dl>

                <div class="feature-panel">
                  <div>
                    <span>裂缝特征匹配</span>
                    <strong>{{ featureSummary(identity) }}</strong>
                  </div>
                  <p>{{ identity.remark || "本条记录暂无详细匹配备注。" }}</p>
                </div>

                <div class="identity-footer">
                  <span>最近出现：{{ formatTime(identity.last_seen_at) }}</span>
                  <el-button type="primary" plain @click="openIdentityDetail(identity.id)">查看身份时间线</el-button>
                </div>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无匹配的裂缝级身份结果。</div>
        </template>
      </main>
    </div>

    <el-drawer v-model="frameDetailVisible" :title="drawerTitle" size="82%">
      <template v-if="frameDetail">
        <div class="detail-head">
          <div>
            <p>{{ frameDetail.frame_code }}</p>
            <h2>{{ frameDetail.road_name }} · {{ formatTime(frameDetail.captured_at) }}</h2>
          </div>
          <span :class="['risk-tag', severityClass(frameDetail.max_severity_level)]">{{ frameDetail.max_severity_label }}</span>
        </div>

        <div class="detail-metrics">
          <div>
            <span>裂缝数</span>
            <strong>{{ frameDetail.crack_count }}</strong>
          </div>
          <div>
            <span>总面积</span>
            <strong>{{ formatArea(frameDetail.total_area_m2) }} m²</strong>
          </div>
          <div>
            <span>视频时间</span>
            <strong>{{ Number(frameDetail.elapsed_seconds || 0).toFixed(2) }} s</strong>
          </div>
          <div>
            <span>任务</span>
            <strong>{{ frameDetail.task_name || `#${frameDetail.task_id}` }}</strong>
          </div>
        </div>

        <div class="image-compare-grid">
          <section class="image-panel">
            <h3 class="media-card-title">原图</h3>
            <img :src="assetUrl(frameDetail.original_image_uri)" alt="原图" />
          </section>
          <section class="image-panel">
            <h3 class="media-card-title">Overlay mask</h3>
            <img :src="assetUrl(frameDetail.result_image_uri)" alt="overlay mask" />
          </section>
          <section v-if="frameDetail.mask_image_uri" class="image-panel">
            <h3 class="media-card-title">Mask</h3>
            <img :src="assetUrl(frameDetail.mask_image_uri)" alt="mask" />
          </section>
        </div>

        <section class="crop-section">
          <div class="section-head compact">
            <div>
              <h3 class="media-card-title">裂缝放大图</h3>
              <p class="meta-text">{{ frameDetail.cracks.length }} 条裂缝实例</p>
            </div>
          </div>
          <div v-if="frameDetail.cracks.length" class="crop-grid">
            <article v-for="item in frameDetail.cracks" :key="item.id" class="crop-card">
              <img :src="assetUrl(item.crop_result_image_uri || item.result_image_uri)" :alt="`${item.crack_code} 放大图`" />
              <div class="crop-copy">
                <strong>{{ item.crack_code }}</strong>
                <span>{{ item.identity_code || "未关联身份档案" }}</span>
                <span>{{ item.crack_type }} / {{ item.length_m }} m / {{ formatArea(item.area_m2) }} m²</span>
              </div>
              <span :class="['risk-tag', severityClass(item.severity_level)]">{{ item.severity_label }}</span>
            </article>
          </div>
          <div v-else class="empty-state">这一帧暂无裂缝放大图。</div>
        </section>
      </template>
      <template v-else>
        <div class="empty-state">暂无详情数据。</div>
      </template>
    </el-drawer>

    <el-drawer v-model="identityDetailVisible" :title="identityDrawerTitle" size="82%" v-loading="identityDetailLoading">
      <template v-if="identityDetail">
        <div class="detail-head identity-detail-head">
          <div>
            <p>{{ identityDetail.identity_code }}</p>
            <h2>{{ identityDetail.road_name }} · {{ identityDetail.crack_type }}</h2>
          </div>
          <div class="identity-detail-tags">
            <span :class="['risk-tag', severityClass(identityDetail.current_severity_level)]">
              {{ identityDetail.current_severity_label }}
            </span>
            <span :class="['status-pill', lifecycleClass(identityDetail.lifecycle_status)]">
              {{ lifecycleLabel(identityDetail.lifecycle_status) }}
            </span>
          </div>
        </div>

        <div class="detail-metrics">
          <div>
            <span>观测次数</span>
            <strong>{{ identityDetail.observation_count }}</strong>
          </div>
          <div>
            <span>当前面积</span>
            <strong>{{ formatArea(identityDetail.current_area_m2) }} m²</strong>
          </div>
          <div>
            <span>面积变化</span>
            <strong :class="growthClass(identityDetail.growth_area_m2)">{{ formatSigned(identityDetail.growth_area_m2, 4) }} m²</strong>
          </div>
          <div>
            <span>处置状态</span>
            <strong>{{ maintenanceLabel(identityDetail.maintenance_status) }}</strong>
          </div>
        </div>

        <section class="identity-detail-section">
          <div class="section-head compact">
            <div>
              <h3 class="media-card-title">复检匹配时间线</h3>
              <p class="meta-text">同一身份档案下的历次裂缝观测。</p>
            </div>
          </div>
          <div v-if="identityDetail.records.length" class="identity-timeline">
            <article v-for="record in identityDetail.records" :key="record.id" class="timeline-item">
              <span class="timeline-dot" />
              <div>
                <strong>{{ record.crack_code }} · {{ record.severity_label }}</strong>
                <p>{{ formatTime(record.detected_at) }} / {{ record.crack_type }} / 面积 {{ formatArea(record.area_m2) }} m²</p>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无身份时间线。</div>
        </section>

        <section class="identity-detail-section">
          <div class="section-head compact">
            <div>
              <h3 class="media-card-title">复检证据图</h3>
              <p class="meta-text">{{ identityDetail.observation_images.length }} 张观测图像。</p>
            </div>
          </div>
          <div v-if="identityDetail.observation_images.length" class="observation-grid">
            <article v-for="image in identityDetail.observation_images" :key="image.crack_id" class="observation-card">
              <img :src="assetUrl(image.crop_result_image_uri || image.result_image_uri)" :alt="`${image.crack_code} 证据图`" />
              <div>
                <strong>{{ image.crack_code }}</strong>
                <span>{{ formatTime(image.detected_at) }}</span>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无复检证据图。</div>
        </section>
      </template>
      <template v-else>
        <div class="empty-state">暂无身份详情数据。</div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Refresh, Search } from "@element-plus/icons-vue";

import {
  fetchCrackIdentities,
  fetchCrackIdentityDetail,
  fetchFrameDates,
  fetchFrameRoads,
  fetchInspectionFrameDetail,
  fetchInspectionFrames,
} from "../api/modules";
import { assetUrl } from "../api/request";

const PAGE_SIZE = 10;
const RESULT_MODES = {
  frames: "frames",
  identities: "identities",
};

const loading = ref(false);
const frameLoading = ref(false);
const identityLoading = ref(false);
const identityDetailLoading = ref(false);
const roads = ref([]);
const dates = ref([]);
const frames = ref([]);
const identities = ref([]);
const selectedRoad = ref(null);
const selectedDate = ref(null);
const activeResultMode = ref(RESULT_MODES.frames);
const roadKeyword = ref("");
const frameSeverityFilter = ref(null);
const identitySeverityFilter = ref(null);
const identityLifecycleFilter = ref("");
const frameDetailVisible = ref(false);
const frameDetail = ref(null);
const identityDetailVisible = ref(false);
const identityDetail = ref(null);
const framePagination = ref({
  page: 1,
  page_size: PAGE_SIZE,
  total: 0,
  total_pages: 0,
});

const filteredRoads = computed(() => {
  const keyword = roadKeyword.value.trim().toLowerCase();
  if (!keyword) return roads.value;
  return roads.value.filter((item) =>
    [item.road_name, item.district].filter(Boolean).some((value) => String(value).toLowerCase().includes(keyword)),
  );
});

const displayedFrames = computed(() => {
  if (!frameSeverityFilter.value) return frames.value;
  return frames.value.filter((item) => item.max_severity_level === frameSeverityFilter.value);
});

const filteredIdentities = computed(() =>
  identities.value.filter((item) => {
    if (identitySeverityFilter.value && item.current_severity_level !== identitySeverityFilter.value) return false;
    if (identityLifecycleFilter.value && item.lifecycle_status !== identityLifecycleFilter.value) return false;
    return true;
  }),
);

const identityStats = computed(() => {
  const matched = identities.value.filter((item) => Number(item.observation_count || 0) > 1).length;
  return {
    total: identities.value.length,
    matched,
    newInTask: Math.max(identities.value.length - matched, 0),
    changed: identities.value.filter(
      (item) => Math.abs(Number(item.growth_area_m2 || 0)) > 0.0001 || Math.abs(Number(item.growth_length_m || 0)) > 0.001,
    ).length,
  };
});

const visibleIdentityStats = computed(() => {
  const matched = filteredIdentities.value.filter((item) => Number(item.observation_count || 0) > 1).length;
  return {
    matched,
    newInTask: Math.max(filteredIdentities.value.length - matched, 0),
    changed: filteredIdentities.value.filter(
      (item) => Math.abs(Number(item.growth_area_m2 || 0)) > 0.0001 || Math.abs(Number(item.growth_length_m || 0)) > 0.001,
    ).length,
  };
});

const isSelectedReviewTask = computed(() => isReviewTaskType(selectedDate.value?.task_type));
const workspaceLoading = computed(() =>
  activeResultMode.value === RESULT_MODES.frames ? frameLoading.value : identityLoading.value,
);

const summaryStats = computed(() => [
  { label: "道路数", value: roads.value.length, copy: "已有帧级检测" },
  { label: "巡检/复检批次", value: dates.value.length, copy: selectedRoad.value ? selectedRoad.value.road_name : "选择道路后展示" },
  {
    label: "当前检测帧",
    value: framePagination.value.total,
    copy: selectedDate.value ? `${selectedDate.value.detected_date} · ${taskTypeLabel(selectedDate.value.task_type)}` : "所选批次帧数",
  },
  {
    label: "当前裂缝身份",
    value: identityStats.value.total,
    copy: isSelectedReviewTask.value ? "复检匹配/更新结果" : "所选批次身份档案",
  },
]);

const framePanelSubtitle = computed(() => {
  if (!selectedRoad.value) return "请选择道路。";
  if (!selectedDate.value) return `${selectedRoad.value.road_name} 暂无巡检日期。`;
  return `${selectedRoad.value.road_name} / ${selectedDate.value.detected_date} / ${selectedDate.value.task_name}`;
});

const workspaceTitle = computed(() =>
  activeResultMode.value === RESULT_MODES.frames ? "检测帧数据" : "裂缝身份匹配与更新",
);

const workspaceSubtitle = computed(() => {
  if (activeResultMode.value === RESULT_MODES.frames) return framePanelSubtitle.value;
  if (!selectedRoad.value) return "请选择道路后查看裂缝身份。";
  if (!selectedDate.value) return `${selectedRoad.value.road_name} 暂无巡检/复检批次。`;
  const modeText = isSelectedReviewTask.value ? "复检任务" : "巡检任务";
  return `${selectedRoad.value.road_name} / ${selectedDate.value.detected_date} / ${selectedDate.value.task_name} / ${modeText}`;
});

const drawerTitle = computed(() => (frameDetail.value ? `${frameDetail.value.frame_code} 检测详情` : "帧检测详情"));
const identityDrawerTitle = computed(() =>
  identityDetail.value ? `${identityDetail.value.identity_code} 身份档案` : "裂缝身份档案",
);

async function reloadAll() {
  loading.value = true;
  try {
    roads.value = await fetchFrameRoads();
    if (roads.value.length) {
      const currentKey = selectedRoad.value ? roadKey(selectedRoad.value) : null;
      const nextRoad = roads.value.find((item) => roadKey(item) === currentKey) || roads.value[0];
      await selectRoad(nextRoad);
    } else {
      selectedRoad.value = null;
      selectedDate.value = null;
      dates.value = [];
      frames.value = [];
      identities.value = [];
      resetFramePagination();
    }
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    loading.value = false;
  }
}

async function selectRoad(road) {
  selectedRoad.value = road;
  selectedDate.value = null;
  frames.value = [];
  identities.value = [];
  frameSeverityFilter.value = null;
  identitySeverityFilter.value = null;
  identityLifecycleFilter.value = "";
  resetFramePagination();
  try {
    dates.value = await fetchFrameDates(roadParams(road));
    if (dates.value.length) {
      await selectDate(dates.value[0]);
    }
  } catch (error) {
    ElMessage.error(error.message);
  }
}

async function selectDate(item) {
  selectedDate.value = item;
  framePagination.value.page = 1;
  frameSeverityFilter.value = null;
  identitySeverityFilter.value = null;
  identityLifecycleFilter.value = "";
  activeResultMode.value = isReviewTaskType(item.task_type) ? RESULT_MODES.identities : RESULT_MODES.frames;
  await Promise.all([loadFrames(1), loadIdentities()]);
}

async function loadFrames(page = framePagination.value.page) {
  if (!selectedRoad.value || !selectedDate.value) {
    frames.value = [];
    resetFramePagination();
    return;
  }
  frameLoading.value = true;
  try {
    const result = await fetchInspectionFrames({
      ...roadParams(selectedRoad.value),
      task_id: selectedDate.value.task_id,
      page,
      page_size: PAGE_SIZE,
    });
    frames.value = result.items || [];
    framePagination.value = {
      page: result.page || page,
      page_size: result.page_size || PAGE_SIZE,
      total: result.total || 0,
      total_pages: result.total_pages || 0,
    };
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    frameLoading.value = false;
  }
}

async function loadIdentities() {
  if (!selectedRoad.value || !selectedDate.value) {
    identities.value = [];
    return;
  }
  identityLoading.value = true;
  try {
    identities.value = await fetchCrackIdentities({
      ...roadParams(selectedRoad.value),
      task_id: selectedDate.value.task_id,
    });
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    identityLoading.value = false;
  }
}

async function changeFramePage(page) {
  await loadFrames(page);
}

async function openFrameDetail(frameId) {
  try {
    frameDetail.value = await fetchInspectionFrameDetail(frameId);
    frameDetailVisible.value = true;
  } catch (error) {
    ElMessage.error(error.message);
  }
}

async function openIdentityDetail(identityId) {
  identityDetailVisible.value = true;
  identityDetailLoading.value = true;
  try {
    identityDetail.value = await fetchCrackIdentityDetail(identityId);
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    identityDetailLoading.value = false;
  }
}

function resetFramePagination() {
  framePagination.value = {
    page: 1,
    page_size: PAGE_SIZE,
    total: 0,
    total_pages: 0,
  };
}

function roadParams(road) {
  if (road?.road_segment_id) {
    return { road_segment_id: road.road_segment_id };
  }
  return { road_name: road?.road_name };
}

function roadKey(road) {
  return `${road.road_segment_id || "name"}-${road.road_name}-${road.district}`;
}

function isSelectedRoad(road) {
  return selectedRoad.value && roadKey(road) === roadKey(selectedRoad.value);
}

function isReviewTaskType(taskType) {
  return taskType === "review" || taskType === "reinspection";
}

function taskTypeLabel(taskType) {
  return isReviewTaskType(taskType) ? "复检" : "巡检";
}

function lifecycleLabel(status) {
  const map = {
    active: "活跃",
    repaired: "已修复",
    recurred: "复发",
    archived: "归档",
  };
  return map[status] || status || "未知";
}

function lifecycleClass(status) {
  if (status === "repaired") return "is-success";
  if (status === "recurred") return "is-danger";
  if (status === "archived") return "is-info";
  return "is-warning";
}

function maintenanceLabel(status) {
  const map = {
    unrepaired: "未处置",
    planned: "待维修",
    in_progress: "维修中",
    working: "维修中",
    completed: "已完成",
    repaired: "已修复",
  };
  return map[status] || status || "未知";
}

function matchStatusLabel(identity) {
  if (identity.lifecycle_status === "recurred") return "维修后复发";
  if (!isSelectedReviewTask.value) return Number(identity.observation_count || 0) > 1 ? "身份持续更新" : "新建身份档案";
  if (Number(identity.observation_count || 0) > 1) return "已匹配历史裂缝";
  return "复检新增裂缝";
}

function matchStatusCopy(identity) {
  if (identity.lifecycle_status === "recurred") return "已完成处置后再次出现，需要复核维修效果。";
  if (Number(identity.observation_count || 0) > 1) {
    return `累计 ${identity.observation_count} 次观测，最新一次已写回身份档案。`;
  }
  return isSelectedReviewTask.value ? "本次复检未匹配到历史身份，已作为新裂缝建档。" : "首次检测生成的裂缝身份档案。";
}

function matchClass(identity) {
  if (identity.lifecycle_status === "recurred") return "is-danger";
  if (Number(identity.observation_count || 0) > 1) return "is-success";
  return "is-warning";
}

function featureSummary(identity) {
  const evidence = matchEvidence(identity);
  if (!evidence.length) return Number(identity.observation_count || 0) > 1 ? "已更新身份特征" : "等待后续复检";
  return evidence.map((item) => `${item.label} ${item.value}`).join(" / ");
}

function matchEvidence(identity) {
  const remark = identity.remark || "";
  const distanceMatch = remark.match(/distance=([0-9.]+)/);
  const diceMatch = remark.match(/shape_dice=([0-9.]+)/);
  const evidence = [];
  if (distanceMatch) evidence.push({ label: "空间距离", value: `${distanceMatch[1]}m` });
  if (diceMatch) evidence.push({ label: "形状Dice", value: diceMatch[1] });
  return evidence;
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function formatArea(value) {
  return Number(value || 0).toFixed(4);
}

function formatSigned(value, digits = 2) {
  const numeric = Number(value || 0);
  if (Math.abs(numeric) < 10 ** -digits) return numeric.toFixed(digits);
  return `${numeric > 0 ? "+" : ""}${numeric.toFixed(digits)}`;
}

function growthClass(value) {
  const numeric = Number(value || 0);
  if (numeric > 0) return "is-growth-up";
  if (numeric < 0) return "is-growth-down";
  return "is-growth-flat";
}

function severityClass(level) {
  if (level === 3) return "is-severe";
  if (level === 2) return "is-medium";
  return "is-minor";
}

onMounted(reloadAll);
</script>

<style scoped>
.frame-page {
  gap: 20px;
}

.frame-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.frame-stat {
  padding: 18px;
}

.frame-stat span {
  color: #64748b;
  font-size: 13px;
}

.frame-stat strong {
  display: block;
  margin-top: 10px;
  color: #0f172a;
  font-size: 30px;
  line-height: 1;
}

.frame-stat p {
  margin: 8px 0 0;
  color: #2563eb;
  font-size: 13px;
}

.frame-browser {
  display: grid;
  grid-template-columns: 280px 280px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.browser-column,
.frame-workspace {
  min-width: 0;
}

.column-head,
.workspace-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.workspace-head .section-title {
  margin-bottom: 6px;
}

.result-mode-switch {
  flex-shrink: 0;
}

.workspace-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.mode-note {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.identity-toolbar {
  align-items: flex-start;
}

.identity-overview {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.identity-overview span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 10px;
  border-radius: 999px;
  background: #fff;
  color: #64748b;
  font-size: 12px;
}

.identity-overview strong {
  color: #0f172a;
  font-size: 14px;
}

.identity-filters {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.mode-hint {
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 13px;
}

.road-list,
.date-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  max-height: calc(100vh - 330px);
  overflow: auto;
  padding-right: 4px;
}

.road-item,
.date-item {
  width: 100%;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  cursor: pointer;
  text-align: left;
}

.road-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
}

.date-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 12px;
  padding: 12px;
}

.road-item.active,
.date-item.active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #0f172a;
}

.road-item strong,
.date-item strong {
  display: block;
  overflow: hidden;
  color: inherit;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.road-item small,
.date-item small {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.road-item em,
.date-item em,
.date-item b {
  color: #2563eb;
  font-style: normal;
  font-weight: 700;
  font-size: 12px;
  white-space: nowrap;
}

.date-item em {
  color: #f97316;
}

.date-item b {
  grid-column: 1 / -1;
  color: #64748b;
}

.severity-select,
.status-select {
  width: 128px;
}

.frame-grid,
.identity-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.frame-card,
.identity-card {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.frame-thumb-wrap,
.identity-image {
  position: relative;
  background: #f8fafc;
}

.frame-thumb,
.identity-image img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}

.frame-thumb-wrap .risk-tag,
.identity-image .risk-tag {
  position: absolute;
  left: 10px;
  top: 10px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
}

.image-placeholder {
  display: grid;
  width: 100%;
  aspect-ratio: 16 / 9;
  place-items: center;
  color: #94a3b8;
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  font-size: 13px;
}

.frame-card-body,
.identity-body {
  display: grid;
  gap: 14px;
  padding: 14px;
}

.frame-card-body strong,
.identity-title-row strong {
  display: block;
  color: #0f172a;
  font-size: 15px;
}

.frame-card-body span,
.identity-title-row span,
.identity-footer span {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.frame-card-body dl,
.identity-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.frame-card-body dl div,
.identity-metrics div {
  min-width: 0;
  padding: 8px;
  border-radius: 8px;
  background: #f8fafc;
}

.frame-card-body dt,
.identity-metrics dt {
  color: #64748b;
  font-size: 12px;
}

.frame-card-body dd,
.identity-metrics dd {
  margin: 6px 0 0;
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.identity-title-row,
.identity-footer,
.identity-detail-tags {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.match-banner {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
}

.match-banner strong {
  color: #0f172a;
  font-size: 14px;
}

.match-banner p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.match-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: #f97316;
}

.match-dot.is-success {
  background: #16a34a;
}

.match-dot.is-danger {
  background: #dc2626;
}

.feature-panel {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px dashed #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
}

.feature-panel span {
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.feature-panel strong {
  display: block;
  margin-top: 3px;
  color: #0f172a;
  font-size: 13px;
}

.feature-panel p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.is-growth-up {
  color: #dc2626 !important;
}

.is-growth-down {
  color: #16a34a !important;
}

.is-growth-flat {
  color: #0f172a !important;
}

.frame-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid #e2e8f0;
}

.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 18px;
}

.detail-head p {
  margin: 0;
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
}

.detail-head h2 {
  margin: 8px 0 0;
  color: #0f172a;
  font-size: 24px;
}

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.detail-metrics div {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.detail-metrics span {
  color: #64748b;
  font-size: 13px;
}

.detail-metrics strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 20px;
}

.image-compare-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.image-panel {
  overflow: hidden;
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.image-panel img {
  width: 100%;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.crop-section,
.identity-detail-section {
  margin-top: 20px;
}

.section-head.compact {
  margin-bottom: 14px;
}

.crop-grid,
.observation-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.crop-card,
.observation-card {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.crop-card img,
.observation-card img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  background: #f8fafc;
}

.crop-copy,
.observation-card div {
  display: grid;
  gap: 4px;
  padding: 14px 14px 0;
}

.crop-copy strong,
.observation-card strong {
  color: #0f172a;
  font-size: 14px;
}

.crop-copy span,
.observation-card span {
  color: #64748b;
  font-size: 12px;
}

.crop-card .risk-tag {
  margin: 14px;
}

.observation-card div {
  padding-bottom: 14px;
}

.identity-timeline {
  display: grid;
  gap: 12px;
}

.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: #2563eb;
}

.timeline-item strong {
  color: #0f172a;
  font-size: 14px;
}

.timeline-item p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 1440px) {
  .frame-grid,
  .identity-grid,
  .crop-grid,
  .observation-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1280px) {
  .frame-browser {
    grid-template-columns: 240px 240px minmax(0, 1fr);
  }

  .workspace-head,
  .workspace-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .identity-filters {
    flex-wrap: wrap;
  }
}

@media (max-width: 1080px) {
  .frame-summary,
  .detail-metrics,
  .image-compare-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .frame-grid,
  .identity-grid,
  .crop-grid,
  .observation-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .frame-browser {
    grid-template-columns: 1fr;
  }

  .frame-pagination,
  .identity-footer {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 768px) {
  .frame-summary,
  .detail-metrics,
  .image-compare-grid {
    grid-template-columns: 1fr;
  }

  .result-mode-switch {
    width: 100%;
  }
}
</style>
