import request from "./request";

export function fetchTasks() {
  return request.get("/api/tasks");
}

export function createTask(payload) {
  return request.post("/api/tasks", payload);
}

export function relocateTask(taskId) {
  return request.post(`/api/tasks/${taskId}/relocate`);
}

export function deleteTask(taskId) {
  return request.delete(`/api/tasks/${taskId}`);
}

export function fetchTaskDetail(taskId) {
  return request.get(`/api/tasks/${taskId}`);
}

export function startDetection(taskId, payload = {}) {
  return request.post(`/api/detection/start/${taskId}`, payload, {
    timeout: 3600000,
  });
}

export function fetchDetectionProgress(taskId) {
  return request.get(`/api/detection/progress/${taskId}`);
}

export function fetchCracks(params = {}) {
  return request.get("/api/cracks", { params });
}

export function fetchCrackDetail(crackId) {
  return request.get(`/api/cracks/${crackId}`);
}

export function fetchCrackIdentities(params = {}) {
  return request.get("/api/cracks/identities", { params });
}

export function fetchCrackIdentityDetail(identityId) {
  return request.get(`/api/cracks/identities/${identityId}`);
}

export function createMaintenanceRecord(identityId, payload) {
  return request.post(`/api/cracks/identities/${identityId}/maintenance`, payload);
}

export function fetchCrackMap(params = {}) {
  return request.get("/api/cracks/map", { params });
}

export function fetchCrackStatistics() {
  return request.get("/api/cracks/statistics");
}

export function fetchFrameRoads() {
  return request.get("/api/cracks/frame-roads");
}

export function fetchFrameDates(params = {}) {
  return request.get("/api/cracks/frame-dates", { params });
}

export function fetchInspectionFrames(params = {}) {
  return request.get("/api/cracks/frames", { params });
}

export function fetchInspectionFrameDetail(frameId) {
  return request.get(`/api/cracks/frames/${frameId}`);
}

export function reverseGeocode(params = {}) {
  return request.get("/api/geolocation/reverse", { params });
}

export function fetchTaskMedia(taskId) {
  return request.get(`/api/media/task/${taskId}`);
}

export function uploadTaskMedia(formData) {
  return request.post("/api/media/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
    timeout: 600000,
  });
}

export function runNLQuery(payload) {
  return request.post("/api/nl-query", payload);
}

export function runAgentQuery(payload) {
  return request.post("/api/agent/query", payload, {
    timeout: 300000,
  });
}

export const AGENT_STREAM_URL = "/api/agent/query/stream";

export function fetchAgentSession(sessionId) {
  return request.get(`/api/agent/session/${sessionId}`, {
    timeout: 60000,
  });
}
