# DJI 道路裂缝标注工具

这个工具从 `dji_videos/seg` 的分段视频中均匀抽帧，把每帧切成左上、右上、左下、右下四张图，并生成 CrackMamba/nnU-Net 可直接读取的二值分割数据集。

## 启动

项目使用 Anaconda 环境。在项目根目录执行一键启动脚本：

```bash
./start_annotation_tool.sh
```

脚本默认使用 `roadcrack` Conda 环境并监听 `0.0.0.0:8765`。启动后终端会打印本机地址和局域网地址；同一局域网内的电脑或平板直接打开局域网地址即可标注。例如本机地址为 `192.168.0.105` 时，访问 `http://192.168.0.105:8765`。

服务不包含账号认证，只应在可信局域网内运行。所有访问端的标注都会由服务端保存到本机项目目录，浏览器端不需要安装 Python。

常用参数：

```bash
python scripts/annotate_crack_dataset.py \
  --video-dir dji_videos/seg \
  --output-dir annotations/road_crack \
  --frames-per-video 3 \
  --host 0.0.0.0 \
  --port 8765
```

启动脚本可以通过环境变量调整配置：

```bash
ANNOTATION_PORT=8877 FRAMES_PER_VIDEO=4 ./start_annotation_tool.sh
```

`--frames-per-video 3` 表示每个视频片段取 3 帧，每帧生成 4 个图块。19 个视频片段会生成 `19 × 3 × 4 = 228` 个候选图块。候选按视频片段轮询排列，连续标注时会优先看到不同路段。

## 标注

- 用画笔覆盖裂缝像素，用橡皮修正；调整滑块可改变笔刷宽度。
- 放大后可直接拖动滚动条；按住空格并拖动画布可快速平移到任意边缘区域。
- 有裂缝时选择“保存并下一张”。掩膜为空时不会误存为正样本。
- 确认没有裂缝时选择“标为空白”，保留为训练所需的负样本。
- 模糊、遮挡或不适合训练的图块选择“跳过”。
- 每次保存都会立即写入磁盘。再次用相同命令启动会从清单中的待标样本继续。

快捷键包括 `B` 画笔、`E` 橡皮、`Space` 平移、`Ctrl+Z` 撤销、`Ctrl+Y` 重做、左右方向键切换、`Enter` 保存和 `N` 标为空白。

## 输出

默认输出到：

```text
annotations/road_crack/
├── annotation_manifest.json
├── dataset.json
├── imagesTr/
│   └── SAMPLE_ID_0000.png
└── labelsTr/
    └── SAMPLE_ID.png
```

原图为四分后的 RGB 图块。标签为单通道 PNG，背景像素值是 `0`，裂缝像素值是 `1`。`annotation_manifest.json` 保存源视频、帧号、时间、象限、状态和输出路径，便于复查与追溯。

需要改变抽帧数时，建议使用新的 `--output-dir`。尚未开始标注的目录也可以加 `--rebuild` 重建清单。
# 弱项道路加标

针对当前模型召回率和 F1 较低的 `DJI_20260609164848_0004_Z_seg001`、
`DJI_20260609164848_0004_Z_seg003`，使用独立任务启动：

```bash
./start_weak_road_annotation_tool.sh
```

默认访问端口为 `8766`，输出到 `annotations/road_crack_weak`。任务包含 64 个新增训练图块和
32 个新增测试图块；页面可按“新增训练集 / 新增测试集”筛选。测试帧位于每段视频的后部时间窗，
并与新增训练帧及原标注帧保留时间间隔。不要手工把标记为 `test` 的样本加入训练集。
