<template>
  <div class="page-shell task-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">巡检/复检任务</h1>
        <p class="page-subtitle">创建批次、上传视频与 SRT、触发 CrackMamba 检测。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadTasks" :loading="loading">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="dialogVisible = true">创建任务</el-button>
      </div>
    </div>

    <div class="task-summary">
      <div v-for="item in taskSummary" :key="item.label" class="surface task-stat">
        <div>
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
        <el-icon :class="item.tone"><component :is="item.icon" /></el-icon>
      </div>
    </div>

    <section class="surface section-card task-workbench" v-loading="loading">
      <div class="task-toolbar">
        <div>
          <h2 class="section-title">任务队列</h2>
          <p class="meta-text">{{ filteredTasks.length }} / {{ tasks.length }} 个任务</p>
        </div>
        <el-radio-group v-model="filterType" size="large">
          <el-radio-button label="all">全部</el-radio-button>
          <el-radio-button label="inspection">巡检</el-radio-button>
          <el-radio-button label="review">复检</el-radio-button>
        </el-radio-group>
      </div>

      <div v-if="filteredTasks.length" class="task-card-grid">
        <article v-for="task in filteredTasks" :key="task.id" class="task-card">
          <div class="task-card-head">
            <div class="task-title-block">
              <div class="task-title-line">
                <strong>{{ task.task_name }}</strong>
                <span :class="['status-pill', statusClass(task.status)]">{{ statusLabel(task.status) }}</span>
              </div>
              <p>{{ locationLabel(task) }}</p>
              <div class="task-tags">
                <el-tag size="small" effect="plain" :type="taskTypeTag(task.task_type)">{{ taskTypeLabel(task.task_type) }}</el-tag>
                <el-tag
                  v-if="isReviewTask(task)"
                  size="small"
                  effect="plain"
                  :type="matchStatusTag(task.road_match_status)"
                >
                  {{ matchStatusLabel(task.road_match_status) }}
                </el-tag>
              </div>
            </div>
            <div class="task-crack-count">
              <span>裂缝</span>
              <strong>{{ task.crack_count || 0 }}</strong>
            </div>
          </div>

          <div class="task-meta-grid">
            <div>
              <span>操作员</span>
              <strong>{{ task.operator_name }}</strong>
            </div>
            <div>
              <span>创建时间</span>
              <strong>{{ formatTime(task.created_at) }}</strong>
            </div>
            <div>
              <span>匹配策略</span>
              <strong>{{ reviewHint(task) }}</strong>
            </div>
          </div>

          <div class="task-progress">
            <div class="task-progress-copy">
              <span>{{ taskProgress(task) }}%</span>
              <strong>{{ task.progress_message || statusLabel(task.status) }}</strong>
            </div>
            <el-progress
              :percentage="taskProgress(task)"
              :show-text="false"
              :stroke-width="10"
              :color="progressColor(task.status)"
            />
          </div>

          <div class="task-actions">
            <el-button plain :icon="UploadFilled" @click="openUploadDialog(task)">上传</el-button>
            <el-button
              plain
              :icon="Refresh"
              :loading="Boolean(relocating[task.id])"
              :disabled="task.status === 'detecting'"
              @click="handleRelocateTask(task)"
            >
              SRT 定位
            </el-button>
            <el-select
              v-model="selectedWeights[task.id]"
              class="weight-select"
              :disabled="task.status === 'detecting' || Boolean(detecting[task.id])"
            >
              <el-option
                v-for="option in detectionWeightOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-button
              type="primary"
              :icon="VideoPlay"
              :loading="Boolean(detecting[task.id])"
              :disabled="task.status === 'detecting'"
              @click="handleStartDetection(task)"
            >
              启动检测
            </el-button>
            <el-button
              type="danger"
              plain
              :icon="Delete"
              :loading="Boolean(deleting[task.id])"
              :disabled="task.status === 'detecting'"
              @click="handleDeleteTask(task)"
            >
              删除
            </el-button>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">暂无任务。</div>
    </section>

    <el-dialog v-model="dialogVisible" title="创建任务" width="600px">
      <el-form :model="form" label-position="top">
        <el-form-item label="任务类型">
          <div class="task-type-picker">
            <button
              v-for="item in taskTypeOptions"
              :key="item.value"
              type="button"
              :class="{ active: form.task_type === item.value }"
              @click="form.task_type = item.value"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
              <small>{{ item.copy }}</small>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="任务名称">
          <el-input
            v-model="form.task_name"
            :placeholder="form.task_type === 'review' ? '例如：中山路维修后复检' : '例如：中山路上午巡检'"
          />
        </el-form-item>
        <el-form-item label="操作员">
          <el-input v-model="form.operator_name" placeholder="例如：演示员A" />
        </el-form-item>
        <div class="review-rule" :class="{ review: form.task_type === 'review' }">
          {{ createTaskRule }}
        </div>
        <el-form-item label="任务说明">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreateTask">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDialogVisible" title="上传视频与 SRT" width="620px">
      <div v-if="selectedTask" class="upload-copy">
        <strong>{{ selectedTask.task_name }}</strong>
        <span>{{ locationLabel(selectedTask) }}</span>
      </div>
      <div class="upload-grid">
        <div class="upload-block">
          <p class="upload-label">无人机视频</p>
          <el-upload
            drag
            multiple
            accept=".mp4,.mov,.avi,.mkv,.m4v,video/*"
            :auto-upload="false"
            :show-file-list="true"
            :on-change="handleVideoChange"
            :on-remove="handleVideoChange"
            :limit="10"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽或点击选择视频</div>
          </el-upload>
        </div>
        <div class="upload-block">
          <p class="upload-label">SRT 元数据</p>
          <el-upload
            drag
            multiple
            accept=".srt"
            :auto-upload="false"
            :show-file-list="true"
            :on-change="handleSrtChange"
            :on-remove="handleSrtChange"
            :limit="10"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽或点击选择 SRT</div>
          </el-upload>
        </div>
      </div>
      <template #footer>
        <el-button @click="closeUploadDialog">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  CircleCheckFilled,
  Clock,
  DataAnalysis,
  Delete,
  Plus,
  Refresh,
  UploadFilled,
  VideoPlay,
} from "@element-plus/icons-vue";

import { createTask, deleteTask, fetchDetectionProgress, fetchTasks, relocateTask, startDetection, uploadTaskMedia } from "../api/modules";

const loading = ref(false);
const creating = ref(false);
const dialogVisible = ref(false);
const tasks = ref([]);
const filterType = ref("all");
const detecting = reactive({});
const deleting = reactive({});
const relocating = reactive({});
const selectedWeights = reactive({});
const progressTimers = new Map();
const uploadDialogVisible = ref(false);
const uploading = ref(false);
const selectedTask = ref(null);
const videoFiles = ref([]);
const srtFiles = ref([]);
const form = reactive({
  task_type: "inspection",
  task_name: "",
  operator_name: "",
  description: "",
});

const detectionWeightOptions = [
  { label: "crack9k", value: "crack9k" },
  { label: "uav-crack", value: "uav-crack" },
  { label: "earthquake", value: "earthquake" },
];

const taskTypeOptions = [
  {
    value: "inspection",
    label: "巡检任务",
    copy: "建立本次道路检测档案",
    icon: CircleCheckFilled,
  },
  {
    value: "review",
    label: "复检任务",
    copy: "匹配已有路段后追踪变化",
    icon: VideoPlay,
  },
];

const filteredTasks = computed(() => {
  if (filterType.value === "inspection") {
    return tasks.value.filter((item) => !isReviewTask(item));
  }
  if (filterType.value === "review") {
    return tasks.value.filter((item) => isReviewTask(item));
  }
  return tasks.value;
});

const taskSummary = computed(() => [
  { label: "任务总数", value: tasks.value.length, icon: DataAnalysis, tone: "is-blue" },
  { label: "巡检任务", value: tasks.value.filter((item) => !isReviewTask(item)).length, icon: CircleCheckFilled, tone: "is-green" },
  { label: "复检任务", value: tasks.value.filter((item) => isReviewTask(item)).length, icon: VideoPlay, tone: "is-orange" },
  { label: "待启动", value: tasks.value.filter((item) => item.status === "pending").length, icon: Clock, tone: "is-slate" },
]);

const createTaskRule = computed(() => {
  if (form.task_type === "review") {
    return "复检任务会先用 SRT 经纬度匹配系统已有路段；匹配成功后才进行裂缝身份档案匹配和变化计算。";
  }
  return "巡检任务会根据 SRT 自动定位道路，并为检测到的裂缝建立新的身份档案。";
});

async function loadTasks() {
  loading.value = true;
  try {
    tasks.value = await fetchTasks();
    tasks.value.forEach((task) => {
      if (!selectedWeights[task.id]) {
        selectedWeights[task.id] = "crack9k";
      }
    });
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    loading.value = false;
  }
}

function patchTaskProgress(progress) {
  const task = tasks.value.find((item) => item.id === progress.task_id);
  if (!task) return;
  task.status = progress.status;
  task.progress_percent = progress.progress_percent;
  task.progress_message = progress.progress_message;
  task.crack_count = progress.crack_count;
  task.started_at = progress.started_at;
  task.finished_at = progress.finished_at;
}

function startProgressPolling(taskId) {
  stopProgressPolling(taskId);
  progressTimers.set(
    taskId,
    window.setInterval(async () => {
      try {
        const progress = await fetchDetectionProgress(taskId);
        patchTaskProgress(progress);
        if (progress.status === "finished" || progress.status === "failed") {
          stopProgressPolling(taskId);
          detecting[taskId] = false;
          await loadTasks();
        }
      } catch {
        stopProgressPolling(taskId);
      }
    }, 1200),
  );
}

function stopProgressPolling(taskId) {
  const timer = progressTimers.get(taskId);
  if (timer) {
    window.clearInterval(timer);
    progressTimers.delete(taskId);
  }
}

async function handleCreateTask() {
  if (!form.task_name || !form.operator_name) {
    ElMessage.warning("请先填写完整任务信息");
    return;
  }

  creating.value = true;
  try {
    await createTask({ ...form });
    ElMessage.success("任务已创建");
    dialogVisible.value = false;
    Object.assign(form, {
      task_type: "inspection",
      task_name: "",
      operator_name: "",
      description: "",
    });
    await loadTasks();
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    creating.value = false;
  }
}

async function handleStartDetection(row) {
  const weightName = selectedWeights[row.id] || "crack9k";
  detecting[row.id] = true;
  row.status = "detecting";
  row.progress_percent = 3;
  row.progress_message = `检测任务已启动（${weightName}）`;
  startProgressPolling(row.id);
  try {
    const result = await startDetection(row.id, { weight_name: weightName });
    ElMessage.success(`检测完成，共生成 ${result.crack_count} 条裂缝记录`);
    await loadTasks();
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    detecting[row.id] = false;
    stopProgressPolling(row.id);
  }
}

async function handleDeleteTask(row) {
  if (row.status === "detecting") {
    ElMessage.warning("检测中的任务暂不能删除");
    return;
  }

  try {
    await ElMessageBox.confirm(`确定删除任务“${row.task_name}”吗？相关媒体和检测结果会一并删除。`, "删除任务", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
      confirmButtonClass: "el-button--danger",
    });
  } catch {
    return;
  }

  deleting[row.id] = true;
  try {
    stopProgressPolling(row.id);
    await deleteTask(row.id);
    ElMessage.success("任务已删除");
    await loadTasks();
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    deleting[row.id] = false;
  }
}

async function handleRelocateTask(row) {
  relocating[row.id] = true;
  try {
    const updated = await relocateTask(row.id);
    row.road_name = updated.road_name;
    row.district = updated.district;
    row.road_segment_id = updated.road_segment_id;
    row.road_match_status = updated.road_match_status;
    row.progress_message = updated.progress_message;
    if (isReviewTask(updated) && updated.road_match_status === "matched_existing") {
      ElMessage.success("复检路段已匹配到系统已有路段");
    } else if (isReviewTask(updated)) {
      ElMessage.warning("复检路段未匹配到系统已有路段");
    } else {
      ElMessage.success("已按 SRT 经纬度定位道路");
    }
    await loadTasks();
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    relocating[row.id] = false;
  }
}

function openUploadDialog(row) {
  selectedTask.value = row;
  videoFiles.value = [];
  srtFiles.value = [];
  uploadDialogVisible.value = true;
}

function closeUploadDialog() {
  uploadDialogVisible.value = false;
  selectedTask.value = null;
  videoFiles.value = [];
  srtFiles.value = [];
}

function handleVideoChange(file, fileList) {
  videoFiles.value = fileList.map((item) => item.raw).filter(Boolean);
}

function handleSrtChange(file, fileList) {
  srtFiles.value = fileList.map((item) => item.raw).filter(Boolean);
}

function fileStem(file) {
  const name = file?.name || "";
  return name.replace(/\.[^.]+$/, "");
}

function hasMatchingPairs() {
  const srtStems = new Set(srtFiles.value.map(fileStem));
  return videoFiles.value.every((file) => srtStems.has(fileStem(file)));
}

async function submitUpload() {
  if (!selectedTask.value) {
    ElMessage.warning("请先选择任务");
    return;
  }
  if (!videoFiles.value.length || !srtFiles.value.length) {
    ElMessage.warning("请同时选择视频和 SRT 文件");
    return;
  }
  if (!hasMatchingPairs()) {
    ElMessage.warning("每个视频都需要上传同名 SRT 文件");
    return;
  }

  uploading.value = true;
  try {
    for (const file of videoFiles.value) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("task_id", selectedTask.value.id);
      formData.append("asset_type", "video");
      formData.append("category", "uploaded");
      await uploadTaskMedia(formData);
    }
    for (const file of srtFiles.value) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("task_id", selectedTask.value.id);
      formData.append("asset_type", "srt");
      formData.append("category", "uploaded");
      await uploadTaskMedia(formData);
    }
    ElMessage.success(`已上传 ${videoFiles.value.length} 段视频和 ${srtFiles.value.length} 个 SRT`);
    closeUploadDialog();
    await loadTasks();
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    uploading.value = false;
  }
}

function statusClass(status) {
  if (status === "finished") return "is-success";
  if (status === "detecting") return "is-warning";
  if (status === "failed") return "is-danger";
  return "is-info";
}

function statusLabel(status) {
  const map = {
    pending: "待检测",
    detecting: "检测中",
    finished: "已完成",
    failed: "失败",
  };
  return map[status] || status;
}

function taskProgress(row) {
  if (typeof row.progress_percent === "number") {
    return row.progress_percent;
  }
  const map = {
    pending: 0,
    detecting: 55,
    finished: 100,
    failed: 100,
  };
  return map[row.status] ?? 0;
}

function isReviewTask(rowOrType) {
  const taskType = typeof rowOrType === "string" ? rowOrType : rowOrType?.task_type;
  return taskType === "review" || taskType === "reinspection";
}

function taskTypeLabel(taskType) {
  return isReviewTask(taskType) ? "复检" : "巡检";
}

function taskTypeTag(taskType) {
  return isReviewTask(taskType) ? "warning" : "success";
}

function matchStatusLabel(status) {
  const map = {
    pending: "待匹配路段",
    matched_existing: "已匹配路段",
    unmatched: "未匹配路段",
    not_required: "无需匹配",
  };
  return map[status] || "待匹配路段";
}

function matchStatusTag(status) {
  if (status === "matched_existing") return "success";
  if (status === "unmatched") return "danger";
  return "info";
}

function reviewHint(row) {
  if (!isReviewTask(row)) return "新建裂缝档案";
  if (row.road_match_status === "matched_existing") return "身份匹配启用";
  if (row.road_match_status === "unmatched") return "仅保存检测结果";
  return "等待 SRT 匹配";
}

function locationLabel(row) {
  if (!row?.road_name || row.road_name === "待导入SRT定位") {
    return isReviewTask(row) ? "等待上传 SRT 匹配已有路段" : "等待上传 SRT 自动定位";
  }
  return `${row.road_name} / ${row.district || "未知区域"}`;
}

function progressColor(status) {
  if (status === "finished") return "#16a34a";
  if (status === "detecting") return "#f97316";
  if (status === "failed") return "#dc2626";
  return "#94a3b8";
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

onMounted(async () => {
  await loadTasks();
  tasks.value
    .filter((item) => item.status === "detecting")
    .forEach((item) => startProgressPolling(item.id));
});

onBeforeUnmount(() => {
  progressTimers.forEach((timer) => window.clearInterval(timer));
  progressTimers.clear();
});
</script>

<style scoped>
.task-page {
  gap: 20px;
}

.task-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.task-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 18px;
}

.task-stat span {
  color: #64748b;
  font-size: 13px;
}

.task-stat strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 30px;
  line-height: 1;
}

.task-stat .el-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 8px;
  font-size: 24px;
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

.task-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.task-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.task-card {
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.task-card-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.task-title-block {
  min-width: 0;
}

.task-title-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.task-title-line strong {
  color: #0f172a;
  font-size: 17px;
  overflow-wrap: anywhere;
}

.task-title-block p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 13px;
}

.task-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.task-crack-count {
  display: grid;
  place-items: center;
  flex: 0 0 74px;
  width: 74px;
  height: 74px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.task-crack-count span {
  color: #64748b;
  font-size: 12px;
}

.task-crack-count strong {
  color: #0f172a;
  font-size: 28px;
  line-height: 1;
}

.task-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.task-meta-grid div {
  min-width: 0;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
}

.task-meta-grid span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.task-meta-grid strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.task-progress-copy {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 13px;
}

.task-progress-copy strong {
  color: #334155;
  font-size: 13px;
  text-align: right;
}

.task-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.task-actions .el-button {
  margin-left: 0;
}

.weight-select {
  width: 132px;
}

.task-type-picker {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}

.task-type-picker button {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 6px 12px;
  align-items: center;
  padding: 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  text-align: left;
  cursor: pointer;
}

.task-type-picker button.active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #0f172a;
}

.task-type-picker .el-icon {
  grid-row: 1 / span 2;
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #e2e8f0;
  color: #2563eb;
  font-size: 22px;
}

.task-type-picker span {
  font-weight: 800;
}

.task-type-picker small {
  color: #64748b;
}

.review-rule {
  margin-bottom: 18px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.review-rule.review {
  background: #fff7ed;
  color: #9a3412;
}

.upload-copy {
  display: grid;
  gap: 4px;
  margin-bottom: 16px;
  color: #64748b;
}

.upload-copy strong {
  color: #0f172a;
}

.upload-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.upload-label {
  margin: 0 0 8px;
  color: #334155;
  font-size: 14px;
  font-weight: 700;
}

@media (max-width: 1320px) {
  .task-card-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .task-summary,
  .task-meta-grid,
  .task-type-picker,
  .upload-grid {
    grid-template-columns: 1fr;
  }

  .task-toolbar,
  .task-card-head {
    flex-direction: column;
  }
}
</style>
