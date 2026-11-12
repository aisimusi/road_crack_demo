import axios from "axios";

function normalizeBaseUrl(value) {
  if (!value) {
    return "";
  }
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

export const API_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);
export const ASSET_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_ASSET_BASE_URL || API_BASE_URL);

const request = axios.create({
  baseURL: API_BASE_URL || undefined,
  timeout: 15000,
});

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error?.response?.data?.detail || error.message || "请求失败";
    return Promise.reject(new Error(message));
  },
);

export function assetUrl(path) {
  if (!path) {
    return "";
  }
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  if (!ASSET_BASE_URL) {
    return path;
  }
  return `${ASSET_BASE_URL}${path}`;
}

export default request;
