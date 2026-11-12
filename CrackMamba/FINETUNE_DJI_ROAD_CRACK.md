# DJI 道路裂缝数据微调

项目根目录的 `train_road_crack_finetune.sh` 会依次完成：

1. 读取 `annotations/road_crack/annotation_manifest.json`，检查所有样本是否已完成标注。
2. 按组划分训练、验证和测试数据，生成 `Dataset230_DJIRoadCrack`。
3. 执行 nnU-Net 2D 规划与预处理。
4. 加载 `CrackMamba/CrackSeg9k_checkpoint_best.pth`，微调 CrackMamba。
5. 使用验证集选择 `checkpoint_best.pth`，然后在隔离的测试集上推理一次。
6. 输出 nnU-Net 官方指标、二值像素指标和逐图 CSV。

## 数据划分

默认划分规则侧重防止数据泄漏：

- 测试集按原始 DJI 视频分组。同一次航拍对应的所有 `segXXX`、帧和四分图只能全部位于训练池或测试集的一侧。
- 训练池内部按 30 秒视频片段分出验证集。同一帧的四张图不会跨集合。
- 默认请求比例是测试集 20%，训练池中的验证集 10%。分组大小不一致时，实际数量会接近但不保证严格等于该比例。
- 划分种子默认为 `2026`，详细样本列表写入 `split_report.json`。

若只要求按 30 秒视频片段隔离测试集，可设置 `TEST_GROUP_BY=segment`。这会获得更接近目标比例的测试集，但相邻视频片段可能来自同一次航拍，评价严格性低于默认设置。

## 启动

脚本使用 Anaconda 的 `crackmamba` 环境。在项目根目录执行：

```bash
./train_road_crack_finetune.sh
```

默认训练参数：

```text
GPU_ID=0
FINETUNE_EPOCHS=100
FINETUNE_LR=5e-5
FINETUNE_FREEZE_ENCODER_EPOCHS=5
FINETUNE_TRAIN_ITERS=100
FINETUNE_VAL_ITERS=25
FINETUNE_PATCH_SIZE=448
BATCH_SIZE=2
ENABLE_TTA=1
```

可以通过环境变量覆盖，例如：

```bash
GPU_ID=1 \
FINETUNE_EPOCHS=150 \
BATCH_SIZE=2 \
./train_road_crack_finetune.sh
```

首次执行会创建数据集编号 `230`。如果该编号已被其他数据集使用，可修改：

```bash
DATASET_ID=231 ./train_road_crack_finetune.sh
```

## 中断后继续

数据已经准备和预处理完成、训练中途被中断时：

```bash
SKIP_DATA_PREP=1 \
SKIP_PREPROCESS=1 \
CONTINUE_TRAINING=1 \
FINETUNE_EPOCHS=150 \
./train_road_crack_finetune.sh
```

`FINETUNE_EPOCHS` 是训练结束时的总轮数，不是额外增加的轮数。

## Patch 尺寸

CrackMamba 的 Snake Scan 实现要求二维 patch 为正方形。DJI 四分图尺寸是 960×540，nnU-Net 会自动规划出矩形 patch，因此启动脚本会在规划完成后把训练 patch 固定为与 CrackSeg9K 预训练一致的 `448×448`，并把 batch size 默认设为 `2`。不要直接使用 nnU-Net 自动生成的矩形 patch；否则会在 `CrackMamba.py` 的 Snake Scan 中出现无效 reshape，并被 torchinfo 包装为 `Failed to run torchinfo`。

如果此前已经遇到这个 torchinfo 错误，说明训练在网络初始化阶段停止，尚无 checkpoint。复用划分和预处理、从预训练权重重新开始即可：

```bash
SKIP_DATA_PREP=1 \
SKIP_PREPROCESS=1 \
./train_road_crack_finetune.sh
```

这种情况不要设置 `CONTINUE_TRAINING=1`，因为还没有可恢复的训练 checkpoint。

如果只准备了数据但尚未开始训练，可省略 `CONTINUE_TRAINING=1`。需要主动重新生成数据划分时使用 `REBUILD_DATASET=1`；它会替换对应的 nnU-Net raw 数据集目录，因此不要在训练过程中使用。

## 输出

主要输出位置：

```text
CrackMamba/nnUNet_raw/Dataset230_DJIRoadCrack/
├── split_report.json
├── imagesTr/
├── labelsTr/
├── imagesTs/
└── labelsTs/

CrackMamba/nnUNet_results/Dataset230_DJIRoadCrack/
└── nnUNetTrainerCrackMambaFinetune__nnUNetPlans__2d/
    ├── fold_0/checkpoint_best.pth
    └── test_evaluation/TIMESTAMP/
        ├── metrics_nnunet.json
        ├── metrics_binary.json
        ├── metrics_per_case.csv
        └── predictions/
```

`metrics_nnunet.json` 是 nnU-Net 官方 Dice/IoU 结果。`metrics_binary.json` 包含全测试集的 Pixel Accuracy、Precision、Recall/Sensitivity、Specificity、Balanced Accuracy、F1/Dice、Crack IoU、Background IoU 和 mIoU；`metrics_per_case.csv` 是逐图结果。

每次运行的完整终端日志保存在 `CrackMamba/runs/dji_road_crack_finetune/`。
