import { createRouter, createWebHistory } from "vue-router";

import Dashboard from "../views/Dashboard.vue";
import TaskList from "../views/TaskList.vue";
import CrackMap from "../views/CrackMap.vue";
import CrackList from "../views/CrackList.vue";
import NLQuery from "../views/NLQuery.vue";

const routes = [
  {
    path: "/",
    redirect: "/dashboard",
  },
  {
    path: "/dashboard",
    name: "dashboard",
    component: Dashboard,
    meta: { title: "首页看板", description: "聚合裂缝统计、风险分布和最近记录，作为演示总控台。" },
  },
  {
    path: "/tasks",
    name: "tasks",
    component: TaskList,
    meta: { title: "巡检任务", description: "创建任务、上传无人机媒体并触发 CrackMamba 检测。" },
  },
  {
    path: "/map",
    name: "map",
    component: CrackMap,
    meta: { title: "地图展示", description: "按道路和风险等级查看裂缝点位与影像证据。" },
  },
  {
    path: "/cracks",
    name: "cracks",
    component: CrackList,
    meta: { title: "裂缝列表", description: "集中检索裂缝编号、几何指标、严重度和检测结果图像。" },
  },
  {
    path: "/nl-query",
    name: "nl-query",
    component: NLQuery,
    meta: { title: "智能查询", description: "通过自然语言驱动 Agent 查询、统计、地图高亮与维修建议。" },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.afterEach((to) => {
  document.title = `${to.meta.title || "系统"} - 无人机道路裂缝智能巡检系统`;
});

export default router;
