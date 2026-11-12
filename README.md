# 无人机道路裂缝智能巡检系统

无人机道路裂缝检测与巡检演示系统，包含 Vue 前端、FastAPI 后端、裂缝分割与分类模型。

```text
road-crack-demo/
├── backend/     # FastAPI + SQLAlchemy + SQLite
├── frontend/    # Vue 3 + Vite + Element Plus + Leaflet
├── CrackMamba/  # CrackMamba 推理源码
├── models/      # 分类器权重
├── scripts/     # 标注、训练和数据处理脚本
└── README.md
```

模型权重通过 Git LFS 管理。原始巡检视频、数据集、预处理缓存、训练结果、本地数据库和上传目录不在仓库中；运行演示需要自行提供视频及 SRT 文件。

## 克隆与启动

```bash
git lfs install
git clone https://github.com/aisimusi/road_crack_demo.git
cd road_crack_demo
git lfs pull

conda create -n roadcrack python=3.10
conda activate roadcrack
pip install -r backend/requirements.txt
cd CrackMamba && pip install -e . && cd ..
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

编辑两个 `.env` 文件填入自己的 OpenAI 和高德 Key。后端运行于激活的 Conda 环境，因此该环境需要安装 CrackMamba 推理依赖和 PyTorch；GPU 版 PyTorch 请按本机 CUDA 版本安装。前端依赖和开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

后端在另一个终端从项目根目录启动：

```bash
conda activate roadcrack
cd backend
python -m uvicorn app.main:app --reload
```

## 功能概览

- 巡检任务创建、列表查询、详情查看
- 真实视频检测流程：上传 DJI 视频和同名 SRT，2 FPS 抽帧，四宫格裁剪后调用 CrackMamba，拼接 mask 并生成蓝色 overlay，写入裂缝记录
- 裂缝列表、地图点位、统计面板
- 智能查询 Agent：展示 Todo、工具调用轨迹、统计结果、地图高亮和图片证据
- 兼容保留原有规则模板版 `POST /api/nl-query`

## Agent 查询说明

当前版本的智能查询主流程为：

```text
自然语言问题
-> Agent Session
-> Tool Registry
-> LLM 原生 Tool Calling 选择工具
-> 参数化工具查询
-> Observation
-> 最终回答
```

核心接口：

- `POST /api/agent/query`
- `GET /api/agent/session/{session_id}`

返回结果包含：

- `todos`
- `tool_calls`
- `stats`
- `cracks`
- `images`
- `map_geojson`
- `maintenance_advice`
- `debug`

## LLM 配置

支持环境变量：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
```

当前版本不再提供 `Mock LLM` 兜底；未设置 `OPENAI_API_KEY` 时，`/api/agent/*` 接口会直接报错。

## `.env` 配置

后端现在支持自动读取 `.env` 文件，不必每次手动在终端里设置变量。

默认会按下面顺序查找：

```text
road-crack-demo/.env
road-crack-demo/.env.local
road-crack-demo/backend/.env
road-crack-demo/backend/.env.local
```

推荐直接使用：

```text
road-crack-demo/backend/.env
```

可以先参考：

```text
road-crack-demo/backend/.env.example
```

示例内容：

```text
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=90

# 可选：用于 SRT 经纬度自动定位道路名，国内坐标推荐配置高德 Web 服务 Key
AMAP_WEB_SERVICE_KEY=your_amap_web_service_key_here
```

说明：

- 如果 `.env` 和当前终端 / Conda 环境变量同时存在，现有环境变量优先，不会被 `.env` 覆盖
- `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 可以按你的 OpenAI-compatible 平台实际值填写
- `AMAP_WEB_SERVICE_KEY` 用于调用高德 Web 服务逆地理编码、地点检索和周边设施分析。Agent 维修建议会结合周边学校、医院、站点等敏感设施做风险加权
- DJI SRT 经纬度通常是 WGS84，系统会先转换为高德使用的 GCJ02 再请求；如果你传入的本身就是高德坐标，调用接口时设置 `coordinate_system=gcj02`
- 任务上传或重定位 SRT 时会自动把道路名写入任务和裂缝记录；如果未配置高德 Key，会尝试 OpenStreetMap，仍没有返回道路名时保留为 `经纬度定位道路(经度,纬度)`，不会再用中山路、学府路等测试道路名兜底
- 修改 `.env` 后需要重启后端进程

前端地图底图使用高德 JS API，需要在 `frontend/.env` 配置 Web 端 JS API Key：

```text
VITE_AMAP_JS_API_KEY=your_amap_js_api_key_here
VITE_AMAP_SECURITY_JS_CODE=your_amap_security_js_code_here
```

说明：

- `AMAP_WEB_SERVICE_KEY` 是后端调用 Web 服务逆地理编码用的 Key；`VITE_AMAP_JS_API_KEY` 是浏览器加载高德 JS 地图用的 Key
- 高德 2021-12-02 之后申请的 Web 端 JS API Key 需要配套安全密钥，填到 `VITE_AMAP_SECURITY_JS_CODE`
- 前端 `.env` 修改后需要重启 Vite 开发服务
- 数据库和 DJI SRT 中的坐标按 WGS84 保存，前端渲染到高德地图前会转换为 GCJ02，避免点位偏移

也可以直接测试单个点位的“经纬度 -> 道路名”映射：

```bash
curl "http://127.0.0.1:8000/api/geolocation/reverse?longitude=119.513876&latitude=32.201336"
```

返回中的 `road_name` 是最终采用的道路名，`road_candidates` 会列出高德返回的候选道路。

已有历史任务如果曾被错误定位到测试道路名，可以先 dry-run 查看：

```bash
cd road-crack-demo
conda run -n roadcrack python scripts/relocate_tasks_from_srt.py
```

确认输出后再写回数据库：

```bash
conda run -n roadcrack python scripts/relocate_tasks_from_srt.py --apply
```

## 检测超参数配置

CrackMamba 检测相关超参数已经从环境变量迁移到本地配置文件：

```text
road-crack-demo/backend/crack_config.ini
```

常用可调项：

```ini
[crackmamba]
python = python
checkpoint = CrackSeg9k_checkpoint_best.pth
device = cuda
batch_size = 2

[classifier]
enabled = true
python = python
script = ../scripts/classify_crack_crops.py
checkpoint = ../models/uapd_crack_classifier_efficientnet_v2_s.pt
device = cuda
batch_size = 16
min_confidence = 0.55
embedding_enabled = true
embedding_model_name = efficientnet_penultimate
embedding_similarity_threshold = 0.8
embedding_margin_threshold = 0.05

[detection]
frame_sample_fps = 2
dedup_distance_m = 1.0
dedup_time_seconds = 3.0
dedup_shape_iou_threshold = 0.18
dedup_shape_dice_threshold = 0.48
dedup_center_distance_ratio = 0.45
dedup_orientation_degrees = 45
mask_min_area_px = 24
mask_noise_min_area_px = 6
mask_connect_gap_px = 32
mask_connect_line_width_px = 3
mask_min_component_area_px = 16
mask_min_component_length_px = 12
mask_min_component_elongation = 1.6
identity_match_distance_m = 3.0
identity_shape_dice_threshold = 0.42
identity_area_ratio_min = 0.25
identity_orientation_degrees = 55
identity_candidate_distance_m = 12.0
identity_geo_score_distance_m = 6.0

[dji_camera]
sensor_width_mm = 6.4
sensor_height_mm = 3.6
focal_length_is_35mm_equivalent = true
physical_focal_min_mm = 21
equivalent_focal_min_mm = 113
```

说明：

- `dedup_distance_m` 对应原来的 `CRACK_DEDUP_DISTANCE_M`
- `dedup_time_seconds` 对应原来的 `CRACK_DEDUP_TIME_SECONDS`
- `dedup_shape_iou_threshold`、`dedup_shape_dice_threshold` 用裂缝本体 bbox 内归一化 mask 判断相邻帧是否为同一处裂缝，不再比较整张图像位置
- `dedup_orientation_degrees` 用裂缝主方向进一步约束判重
- `mask_noise_min_area_px` 用于先删除极小散点；`mask_connect_gap_px`、`mask_connect_line_width_px` 用于把断续但方向一致的裂缝片段桥接为同一实例；`mask_min_area_px`、`mask_min_component_area_px`、`mask_min_component_length_px`、`mask_min_component_elongation` 用于过滤短小块状误检
- `identity_match_distance_m`、`identity_shape_dice_threshold`、`identity_area_ratio_min`、`identity_orientation_degrees` 用于跨批次裂缝身份档案匹配
- `identity_candidate_distance_m` 用于候选召回半径；`identity_geo_score_distance_m` 用于把地理接近度折算为软分数，不再把路段和位置作为唯一硬过滤
- `embedding_enabled`、`embedding_similarity_threshold`、`embedding_margin_threshold` 用于开启神经网络特征匹配，并控制 top1 相似度和 top1/top2 margin
- `frame_sample_fps` 对应原来的 `FRAME_SAMPLE_FPS`
- `sensor_width_mm/sensor_height_mm` 当前按 1/2" CMOS 的 16:9 视频有效区域近似
- `physical_focal_min_mm/equivalent_focal_min_mm` 用官网焦距 `21-75 mm` 与等效焦距 `113-405 mm` 的比例，将 SRT 的 35mm 等效焦距换算为物理焦距
- 裂缝长度、宽度和面积会使用 SRT 中的 `rel_alt`、`focal_len`、`dzoom_ratio`、`gb_pitch` 做平面投影估算，当前忽略畸变参数
- 修改 `crack_config.ini` 后需要重启后端进程

## 裂缝身份档案链路

检测结果现在分为两层：

- `crack_identity`：裂缝单体身份档案，保存身份编号、当前状态、维修状态、优先级、最近位置、当前几何指标、增长量和跨批次特征签名
- `crack_record`：一次巡检中的观测记录，挂接到 `identity_id`
- `maintenance_record`：维修处置和复检记录，挂接到裂缝身份档案

检测流程会先过滤极小散点，再用方向性形态学桥接把断续但相邻的裂缝片段合并，之后按桥接后的连通关系拆成裂缝单体候选；每个候选会同时生成几何形状签名和 crop embedding。跨批次匹配时，系统先按更宽的候选半径召回，再综合 embedding 相似度、地理接近度、形状签名和裂缝类型做混合打分。匹配成功时更新同一身份的状态、增长量和 embedding 原型，未匹配时创建新的 `CID-xxxxxx` 档案。

前端“裂缝列表”页默认展示身份档案，可切换到观测记录；身份详情包含跨批次观测时间线和维修/复检记录登记入口。Agent 工具也可以查询身份档案和单条裂缝的时间线，用于回答“是否扩大、是否已维修、是否复发、是否应优先处置”等问题。

## SQL 安全设计

当前版本采用“LLM -> 参数化工具调用 -> ORM / 参数化查询”的方式，不允许 LLM 直接执行 SQL，从架构上降低 SQL 注入、误删除和越权查询风险。

兼容保留的 `text2sql` 示例能力也接入了只读 `sql_guard`，限制为安全的 `SELECT` 查询。

## 后端启动

建议使用你现有的 Anaconda 环境 `roadcrack`：

```powershell
cd D:\Project\crack_detect_sys\road-crack-demo\backend
conda run -n roadcrack pip install -r requirements-crack.txt
conda run -n roadcrack uvicorn app.main:app --reload
```

启动后访问：

- Swagger 文档: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 静态资源前缀: [http://127.0.0.1:8000/uploads](http://127.0.0.1:8000/uploads)

## 前端启动

```powershell
cd D:\Project\crack_detect_sys\road-crack-demo\frontend
npm install
npm run dev
```

默认访问地址通常为：

- [http://127.0.0.1:5173](http://127.0.0.1:5173)

## 推荐演示顺序

1. 启动后端并打开 `/docs`
2. 调用 `POST /api/tasks` 创建巡检任务
3. 调用 `POST /api/media/upload` 上传同名视频和 SRT，或在前端任务页上传
4. 调用 `POST /api/detection/start/{task_id}` 生成 CrackMamba 检测结果
5. 查看 `GET /api/cracks/statistics`、`GET /api/cracks/map`
6. 调用 `POST /api/agent/query` 测试 Agent 查询
7. 启动前端后，在任务页、地图页、裂缝页和智能查询页进行联动演示

## 已实现的关键文件

### 后端

- `backend/app/main.py`
- `backend/app/database.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/routers/tasks.py`
- `backend/app/routers/media.py`
- `backend/app/routers/detection.py`
- `backend/app/routers/cracks.py`
- `backend/app/routers/agent_query.py`
- `backend/app/routers/nl_query.py`
- `backend/app/agent/agent_loop.py`
- `backend/app/agent/llm_client.py`
- `backend/app/agent/prompts.py`
- `backend/app/agent/sql_guard.py`
- `backend/app/agent/tool_registry.py`
- `backend/app/agent/todo_manager.py`
- `backend/app/agent/tools.py`
- `backend/app/services/crackmamba_detector.py`
- `backend/app/services/text2sql.py`

### 前端

- `frontend/src/App.vue`
- `frontend/src/router/index.js`
- `frontend/src/api/request.js`
- `frontend/src/api/modules.js`
- `frontend/src/views/Dashboard.vue`
- `frontend/src/views/TaskList.vue`
- `frontend/src/views/CrackMap.vue`
- `frontend/src/views/CrackList.vue`
- `frontend/src/views/NLQuery.vue`

## 视频数据说明

- `dji_videos/` 中的视频需要和 `.SRT` 文件同名，例如 `DJI_xxx.MP4` 与 `DJI_xxx.SRT`
- SRT 中的经纬度、高度、焦段和时间戳会随抽帧结果写入检测流程
- CrackMamba 本身输出 0/1 mask；当前数据库不再保存人为置信度字段

## 说明

- 仓库里原先已有一个拼写为 `fronted/` 的空目录；当前完整系统实际使用的是 `frontend/`
- 数据库文件会在首次启动后端时自动创建到 `backend/road_crack_demo.db`
- Agent 会话相关数据会写入新增的 `agent_session`、`agent_todo`、`agent_tool_call` 表

## 自有数据标注

`scripts/annotate_crack_dataset.py` 提供本地浏览器标注界面：从 `dji_videos/seg` 的 MP4 分层抽帧，每帧四分，并输出 CrackMamba/nnU-Net 二值分割数据集。

```bash
./start_annotation_tool.sh
```

服务默认监听 `0.0.0.0:8765`，启动后会打印可供同一局域网设备访问的地址。结果统一保存在服务端的 `annotations/road_crack`。

完整说明见 [annotation_tool/README.md](annotation_tool/README.md)。

## 自有数据微调

完成标注后，可使用 `train_road_crack_finetune.sh` 对数据进行分组划分，加载 CrackSeg9K 权重微调，并输出测试集指标：

```bash
./train_road_crack_finetune.sh
```

参数、断点续训和输出说明见 [CrackMamba/FINETUNE_DJI_ROAD_CRACK.md](CrackMamba/FINETUNE_DJI_ROAD_CRACK.md)。
