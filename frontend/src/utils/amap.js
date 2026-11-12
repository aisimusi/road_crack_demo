const AMAP_API_VERSION = "2.0";
const AMAP_LOADER_ID = "amap-jsapi-loader";
const AMAP_LOADER_URL = "https://webapi.amap.com/loader.js";
const DEFAULT_CENTER = [119.5142, 32.1989];
const DEFAULT_ZOOM = 14;

let loaderPromise = null;

export function amapConfig() {
  return {
    key: import.meta.env.VITE_AMAP_JS_API_KEY || "",
    securityJsCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE || "",
  };
}

export function hasAmapKey() {
  return Boolean(amapConfig().key);
}

function loadLoaderScript() {
  if (window.AMapLoader) {
    return Promise.resolve();
  }

  const existingScript = document.getElementById(AMAP_LOADER_ID);
  if (existingScript) {
    return new Promise((resolve, reject) => {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("高德地图 Loader 加载失败")), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = AMAP_LOADER_ID;
    script.src = AMAP_LOADER_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图 Loader 加载失败"));
    document.head.appendChild(script);
  });
}

export async function loadAmap() {
  const config = amapConfig();
  if (!config.key) {
    throw new Error("请在 frontend/.env 中配置 VITE_AMAP_JS_API_KEY");
  }
  if (config.securityJsCode) {
    window._AMapSecurityConfig = {
      securityJsCode: config.securityJsCode,
    };
  }

  if (!loaderPromise) {
    loaderPromise = loadLoaderScript().then(() =>
      window.AMapLoader.load({
        key: config.key,
        version: AMAP_API_VERSION,
      }),
    );
  }
  return loaderPromise;
}

export async function createAmap(container, options = {}) {
  const AMap = await loadAmap();
  return new AMap.Map(container, {
    viewMode: "2D",
    resizeEnable: true,
    zoom: options.zoom || DEFAULT_ZOOM,
    center: options.center || DEFAULT_CENTER,
    mapStyle: "amap://styles/normal",
  });
}

export function wgs84ToGcj02(longitude, latitude) {
  const lng = Number(longitude);
  const lat = Number(latitude);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return [lng, lat];
  }
  if (lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271) {
    return [lng, lat];
  }

  const axis = 6378245.0;
  const ee = 0.006693421622965943;
  const x = lng - 105.0;
  const y = lat - 35.0;
  let dLat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  dLat += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  dLat += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0;
  dLat += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0;

  let dLng = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  dLng += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
  dLng += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0;
  dLng += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0;

  const radLat = (lat / 180.0) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - ee * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / (((axis * (1 - ee)) / (magic * sqrtMagic)) * Math.PI);
  dLng = (dLng * 180.0) / ((axis / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return [lng + dLng, lat + dLat];
}

export function clearMapObjects(map, objects) {
  if (!map || !objects.length) return;
  map.remove(objects);
  objects.length = 0;
}

export function fitAmapBounds(map, positions, fallbackCenter = DEFAULT_CENTER, objects = []) {
  if (!map) return;
  if (!positions.length) {
    map.setZoomAndCenter(DEFAULT_ZOOM, fallbackCenter);
    return;
  }
  if (positions.length === 1) {
    map.setZoomAndCenter(17, positions[0]);
    return;
  }
  map.setFitView(objects.length ? objects : null, false, [70, 70, 70, 70]);
}

export function markerContent(color, size = 18, count = 1) {
  const label = count > 1
    ? `
      <span style="
        position:absolute;
        inset:0;
        display:grid;
        place-items:center;
        color:#fff;
        font-size:12px;
        font-weight:800;
        line-height:1;
      ">${count}</span>
    `
    : "";
  return `
    <span style="
      position:relative;
      display:block;
      width:${size}px;
      height:${size}px;
      border-radius:999px;
      background:${color};
      border:3px solid #fff;
      box-shadow:0 10px 18px rgba(15,23,42,.25);
    ">${label}</span>
  `;
}

export function attachPopupPager(container, selector, stateMap, renderContent, keyAttribute = "data-crack-popup") {
  if (!container) return;
  container.querySelectorAll(selector).forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = button.getAttribute(keyAttribute);
      const dir = Number(button.getAttribute("data-dir") || 1);
      const state = stateMap.get(key);
      if (!state) return;
      state.index = (state.index + dir + state.group.items.length) % state.group.items.length;
      state.infoWindow.setContent(renderContent(state.group, state.index));
      setTimeout(() => {
        attachPopupPager(container, selector, stateMap, renderContent, keyAttribute);
      }, 0);
    });
  });
}

export { DEFAULT_CENTER, DEFAULT_ZOOM };
