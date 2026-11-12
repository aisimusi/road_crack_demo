#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-roadcrack}"
ANNOTATION_HOST="${ANNOTATION_HOST:-0.0.0.0}"
ANNOTATION_PORT="${ANNOTATION_PORT:-8766}"
VIDEO_DIR="${VIDEO_DIR:-${SCRIPT_DIR}/dji_videos/seg}"
BASE_MANIFEST="${BASE_MANIFEST:-${SCRIPT_DIR}/annotations/road_crack/annotation_manifest.json}"
OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/annotations/road_crack_weak}"

if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
  CONDA_COMMAND="${CONDA_EXE}"
elif command -v conda >/dev/null 2>&1; then
  CONDA_COMMAND="$(command -v conda)"
elif [[ -x "/home/ubuntu/anaconda3/bin/conda" ]]; then
  CONDA_COMMAND="/home/ubuntu/anaconda3/bin/conda"
else
  echo "错误：未找到 conda。请先安装 Anaconda，或设置 CONDA_EXE。" >&2
  exit 1
fi

if [[ ! -f "${OUTPUT_DIR}/annotation_manifest.json" ]]; then
  echo "生成弱项道路训练/测试加标清单"
  "${CONDA_COMMAND}" run --no-capture-output -n "${CONDA_ENV_NAME}" \
    python "${SCRIPT_DIR}/scripts/prepare_weak_road_annotations.py" \
    --video-dir "${VIDEO_DIR}" \
    --base-manifest "${BASE_MANIFEST}" \
    --output-dir "${OUTPUT_DIR}"
fi

echo "启动弱项道路标注工具"
echo "Conda 环境：${CONDA_ENV_NAME}"
echo "结果目录：${OUTPUT_DIR}"
echo "局域网端口：${ANNOTATION_PORT}"
exec "${CONDA_COMMAND}" run --no-capture-output -n "${CONDA_ENV_NAME}" \
  python "${SCRIPT_DIR}/scripts/annotate_crack_dataset.py" \
  --host "${ANNOTATION_HOST}" \
  --port "${ANNOTATION_PORT}" \
  --video-dir "${VIDEO_DIR}" \
  --output-dir "${OUTPUT_DIR}" \
  --frames-per-video 3 \
  --no-browser \
  "$@"
