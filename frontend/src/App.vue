<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="brand-mark">
          <img :src="brandLogo" alt="路瞳智维 logo" class="brand-logo" />
        </div>
        <div>
          <h1 class="brand-title">路瞳智维</h1>
          <p class="brand-copy">低空视觉识别与智能养护平台</p>
        </div>
      </div>

      <el-menu :default-active="route.path" class="nav-menu" router>
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-status">
        <div class="status-line">
          <span class="status-dot" />
          <span>联动服务就绪</span>
        </div>
        <p class="status-copy">任务创建、媒体上传、CrackMamba 检测、地图点位和 Agent 查询已整合到同一工作台。</p>
        <div class="status-metrics">
          <span>v2.0</span>
          <span>FastAPI</span>
        </div>
      </div>
    </aside>

    <main class="main-shell">
      <section class="content-area">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup>
import { useRoute } from "vue-router";
import {
  ChatLineRound,
  HomeFilled,
  MapLocation,
  Management,
  Tickets,
} from "@element-plus/icons-vue";
import brandLogo from "../ChatGPT_Image_2026年6月30日_13_45_34-removebg-preview.png";

const route = useRoute();

const navItems = [
  { path: "/dashboard", title: "首页看板", icon: HomeFilled },
  { path: "/tasks", title: "巡检任务", icon: Tickets },
  { path: "/map", title: "地图展示", icon: MapLocation },
  { path: "/cracks", title: "裂缝列表", icon: Management },
  { path: "/nl-query", title: "智能查询", icon: ChatLineRound },
];
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: #f5f7fb;
}

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  display: flex;
  flex-direction: column;
  width: 264px;
  padding: 24px 16px;
  background: #0f172a;
  color: #fff;
  box-shadow: 12px 0 34px rgba(15, 23, 42, 0.12);
  z-index: 20;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px 22px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}

.brand-logo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  display: block;
}

.brand-title {
  margin: 0;
  color: #f8fafc;
  font-size: 21px;
  font-weight: 800;
  line-height: 1.2;
}

.brand-copy {
  margin: 6px 0 0;
  color: #94a3b8;
  font-size: 12px;
}

.nav-menu {
  flex: 1;
  margin-top: 22px;
  border-right: none;
  background: transparent;
}

:deep(.nav-menu .el-menu-item) {
  height: 46px;
  margin-bottom: 7px;
  border-radius: 8px;
  color: #cbd5e1;
  font-size: 14px;
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}

:deep(.nav-menu .el-menu-item:hover) {
  color: #fff;
  background: rgba(30, 41, 59, 0.92);
}

:deep(.nav-menu .el-menu-item.is-active) {
  color: #fff;
  background: #2563eb;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
}

.sidebar-status {
  margin-top: auto;
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.7);
}

.status-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #f8fafc;
  font-weight: 700;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 5px rgba(34, 197, 94, 0.12);
}

.status-copy {
  margin: 10px 0 0;
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.7;
}

.status-metrics {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.status-metrics span {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: #cbd5e1;
  font-size: 12px;
}

.main-shell {
  min-height: 100vh;
  margin-left: 264px;
}

.content-area {
  padding: 28px 32px 34px;
}

@media (max-width: 1080px) {
  .app-shell {
    display: block;
  }

  .sidebar {
    position: static;
    width: 100%;
    min-height: auto;
  }

  .main-shell {
    margin-left: 0;
  }

  .content-area {
    padding: 20px;
  }
}
</style>
