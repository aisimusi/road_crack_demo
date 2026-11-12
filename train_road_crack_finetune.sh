#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CRACKMAMBA_ROOT="${PROJECT_ROOT}/CrackMamba"
ANNOTATION_ROOT="${ANNOTATION_ROOT:-${PROJECT_ROOT}/annotations/road_crack}"
ADDITIONAL_ANNOTATION_ROOT="${ADDITIONAL_ANNOTATION_ROOT:-}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-crackmamba}"

GPU_ID="${GPU_ID:-0}"
DATASET_ID="${DATASET_ID:-230}"
DATASET_SHORT_NAME="${DATASET_SHORT_NAME:-DJIRoadCrack}"
DATASET_NAME="Dataset$(printf '%03d' "${DATASET_ID}")_${DATASET_SHORT_NAME}"
TRAINER="nnUNetTrainerCrackMambaFinetune"
PRETRAINED_WEIGHTS="${PRETRAINED_WEIGHTS:-${CRACKMAMBA_ROOT}/CrackSeg9k_checkpoint_best.pth}"

TEST_FRACTION="${TEST_FRACTION:-0.20}"
VALIDATION_FRACTION="${VALIDATION_FRACTION:-0.10}"
TEST_GROUP_BY="${TEST_GROUP_BY:-source_video}"
SPLIT_SEED="${SPLIT_SEED:-2026}"

FINETUNE_EPOCHS="${FINETUNE_EPOCHS:-100}"
FINETUNE_LR="${FINETUNE_LR:-5e-5}"
FINETUNE_FREEZE_ENCODER_EPOCHS="${FINETUNE_FREEZE_ENCODER_EPOCHS:-5}"
FINETUNE_SAVE_EVERY="${FINETUNE_SAVE_EVERY:-10}"
FINETUNE_TRAIN_ITERS="${FINETUNE_TRAIN_ITERS:-100}"
FINETUNE_VAL_ITERS="${FINETUNE_VAL_ITERS:-25}"
FINETUNE_PATCH_SIZE="${FINETUNE_PATCH_SIZE:-448}"
BATCH_SIZE="${BATCH_SIZE:-2}"

SKIP_DATA_PREP="${SKIP_DATA_PREP:-0}"
REBUILD_DATASET="${REBUILD_DATASET:-0}"
SKIP_PREPROCESS="${SKIP_PREPROCESS:-0}"
CONTINUE_TRAINING="${CONTINUE_TRAINING:-0}"
ENABLE_TTA="${ENABLE_TTA:-1}"
EVAL_WORKERS="${EVAL_WORKERS:-4}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"

NNUNET_RAW="${CRACKMAMBA_ROOT}/nnUNet_raw"
NNUNET_PREPROCESSED="${CRACKMAMBA_ROOT}/nnUNet_preprocessed"
NNUNET_RESULTS="${CRACKMAMBA_ROOT}/nnUNet_results"
RAW_DATASET_DIR="${NNUNET_RAW}/${DATASET_NAME}"
PREPROCESSED_DATASET_DIR="${NNUNET_PREPROCESSED}/${DATASET_NAME}"
MODEL_FOLDER="${NNUNET_RESULTS}/${DATASET_NAME}/${TRAINER}__nnUNetPlans__2d"
FOLD_FOLDER="${MODEL_FOLDER}/fold_0"
EVALUATION_DIR="${MODEL_FOLDER}/test_evaluation/${RUN_ID}"
PREDICTION_DIR="${EVALUATION_DIR}/predictions"
HISTORICAL_PREDICTION_DIR="${EVALUATION_DIR}/historical_predictions"
LOG_DIR="${CRACKMAMBA_ROOT}/runs/dji_road_crack_finetune"
LOG_FILE="${LOG_DIR}/${RUN_ID}.log"

if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
  CONDA_COMMAND="${CONDA_EXE}"
elif command -v conda >/dev/null 2>&1; then
  CONDA_COMMAND="$(command -v conda)"
elif [[ -x "/home/ubuntu/anaconda3/bin/conda" ]]; then
  CONDA_COMMAND="/home/ubuntu/anaconda3/bin/conda"
else
  echo "ERROR: conda was not found. Set CONDA_EXE to the Anaconda conda executable." >&2
  exit 1
fi

CONDA_BASE="$("${CONDA_COMMAND}" info --base)"
set +u
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV_NAME}"
set -u

if [[ ! -f "${PRETRAINED_WEIGHTS}" ]]; then
  echo "ERROR: pretrained checkpoint not found: ${PRETRAINED_WEIGHTS}" >&2
  exit 1
fi
if [[ ! -f "${ANNOTATION_ROOT}/annotation_manifest.json" ]]; then
  echo "ERROR: annotation manifest not found: ${ANNOTATION_ROOT}/annotation_manifest.json" >&2
  exit 1
fi
if [[ -n "${ADDITIONAL_ANNOTATION_ROOT}" \
      && ! -f "${ADDITIONAL_ANNOTATION_ROOT}/annotation_manifest.json" ]]; then
  echo "ERROR: additional annotation manifest not found: ${ADDITIONAL_ANNOTATION_ROOT}/annotation_manifest.json" >&2
  exit 1
fi
if [[ "${CONTINUE_TRAINING}" != "1" && -d "${FOLD_FOLDER}" ]]; then
  if compgen -G "${FOLD_FOLDER}/*.pth" >/dev/null; then
    echo "ERROR: model checkpoints already exist: ${FOLD_FOLDER}" >&2
    echo "Use CONTINUE_TRAINING=1 to resume, or move the old model folder first." >&2
    exit 1
  fi
  echo "Reusing a failed training folder that contains no checkpoints: ${FOLD_FOLDER}"
fi
if [[ "${CONTINUE_TRAINING}" == "1" \
      && ! -f "${FOLD_FOLDER}/checkpoint_latest.pth" \
      && ! -f "${FOLD_FOLDER}/checkpoint_final.pth" \
      && ! -f "${FOLD_FOLDER}/checkpoint_best.pth" ]]; then
  echo "ERROR: CONTINUE_TRAINING=1 but no checkpoint exists in ${FOLD_FOLDER}" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}" "${EVALUATION_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "Run ID: ${RUN_ID}"
echo "Conda environment: ${CONDA_ENV_NAME}"
echo "GPU: ${GPU_ID}"
echo "Dataset: ${DATASET_NAME}"
if [[ -n "${ADDITIONAL_ANNOTATION_ROOT}" ]]; then
  echo "Additional annotations: ${ADDITIONAL_ANNOTATION_ROOT}"
fi
echo "Pretrained checkpoint: ${PRETRAINED_WEIGHTS}"
echo "Epochs: ${FINETUNE_EPOCHS}, learning rate: ${FINETUNE_LR}"
echo "Patch size: ${FINETUNE_PATCH_SIZE}x${FINETUNE_PATCH_SIZE}, batch size: ${BATCH_SIZE}"

cd "${CRACKMAMBA_ROOT}"

if [[ "${SKIP_DATA_PREP}" != "1" ]]; then
  PREPARE_ARGS=(
    --annotation-root "${ANNOTATION_ROOT}"
    --nnunet-raw "${NNUNET_RAW}"
    --dataset-id "${DATASET_ID}"
    --dataset-name "${DATASET_SHORT_NAME}"
    --test-fraction "${TEST_FRACTION}"
    --validation-fraction "${VALIDATION_FRACTION}"
    --test-group-by "${TEST_GROUP_BY}"
    --seed "${SPLIT_SEED}"
  )
  if [[ "${REBUILD_DATASET}" == "1" ]]; then
    PREPARE_ARGS+=(--overwrite)
  fi
  if [[ -n "${ADDITIONAL_ANNOTATION_ROOT}" ]]; then
    PREPARE_ARGS+=(--additional-annotation-root "${ADDITIONAL_ANNOTATION_ROOT}")
  fi
  python tools/prepare_dji_road_crack_nnunet.py "${PREPARE_ARGS[@]}"
elif [[ ! -f "${RAW_DATASET_DIR}/split_report.json" ]]; then
  echo "ERROR: SKIP_DATA_PREP=1 but the prepared dataset is missing: ${RAW_DATASET_DIR}" >&2
  exit 1
fi

if [[ "${SKIP_PREPROCESS}" != "1" ]]; then
  nnUNetv2_plan_and_preprocess \
    -d "${DATASET_ID}" \
    -c 2d \
    --verify_dataset_integrity
elif [[ ! -f "${PREPROCESSED_DATASET_DIR}/nnUNetPlans.json" ]]; then
  echo "ERROR: SKIP_PREPROCESS=1 but preprocessing output is missing." >&2
  exit 1
fi

# nnU-Net reads custom folds from the preprocessed dataset directory.
cp "${RAW_DATASET_DIR}/splits_final.json" "${PREPROCESSED_DATASET_DIR}/splits_final.json"

# CrackMamba's diagonal Snake Scan assumes square feature maps. nnU-Net plans
# rectangular patches for the 960x540 tiles, so enforce the pretrained model's
# 448x448 patch size after planning and before trainer initialization.
python tools/configure_crackmamba_2d_plan.py \
  "${PREPROCESSED_DATASET_DIR}/nnUNetPlans.json" \
  --patch-size "${FINETUNE_PATCH_SIZE}" \
  --batch-size "${BATCH_SIZE}"

export FINETUNE_EPOCHS
export FINETUNE_LR
export FINETUNE_FREEZE_ENCODER_EPOCHS
export FINETUNE_SAVE_EVERY
export FINETUNE_TRAIN_ITERS
export FINETUNE_VAL_ITERS
export CUDA_VISIBLE_DEVICES="${GPU_ID}"

TRAIN_ARGS=(
  "${DATASET_ID}" 2d 0
  -tr "${TRAINER}"
  -num_gpus 1
)
if [[ "${CONTINUE_TRAINING}" == "1" ]]; then
  TRAIN_ARGS+=(--c)
else
  TRAIN_ARGS+=(-pretrained_weights "${PRETRAINED_WEIGHTS}")
fi

nnUNetv2_train "${TRAIN_ARGS[@]}"

BEST_CHECKPOINT="${FOLD_FOLDER}/checkpoint_best.pth"
if [[ ! -f "${BEST_CHECKPOINT}" ]]; then
  echo "ERROR: training finished without checkpoint_best.pth: ${BEST_CHECKPOINT}" >&2
  exit 1
fi

PREDICT_ARGS=(
  -i "${RAW_DATASET_DIR}/imagesTs"
  -o "${PREDICTION_DIR}"
  -d "${DATASET_ID}"
  -c 2d
  -tr "${TRAINER}"
  -f 0
  -chk checkpoint_best.pth
)
if [[ "${ENABLE_TTA}" != "1" ]]; then
  PREDICT_ARGS+=(--disable_tta)
fi
nnUNetv2_predict "${PREDICT_ARGS[@]}"

# Official nnU-Net Dice/IoU report.
nnUNetv2_evaluate_folder \
  "${RAW_DATASET_DIR}/labelsTs" \
  "${PREDICTION_DIR}" \
  -djfile "${RAW_DATASET_DIR}/dataset.json" \
  -pfile "${MODEL_FOLDER}/plans.json" \
  -o "${EVALUATION_DIR}/metrics_nnunet.json" \
  -np "${EVAL_WORKERS}"

# Additional binary pixel metrics and one row per test image.
python evaluation/evaluate_dji_road_crack.py \
  --ground-truth "${RAW_DATASET_DIR}/labelsTs" \
  --predictions "${PREDICTION_DIR}" \
  --output-json "${EVALUATION_DIR}/metrics_binary.json" \
  --output-csv "${EVALUATION_DIR}/metrics_per_case.csv"

if [[ -d "${RAW_DATASET_DIR}/imagesTsHistorical" ]]; then
  HISTORICAL_PREDICT_ARGS=(
    -i "${RAW_DATASET_DIR}/imagesTsHistorical"
    -o "${HISTORICAL_PREDICTION_DIR}"
    -d "${DATASET_ID}"
    -c 2d
    -tr "${TRAINER}"
    -f 0
    -chk checkpoint_best.pth
  )
  if [[ "${ENABLE_TTA}" != "1" ]]; then
    HISTORICAL_PREDICT_ARGS+=(--disable_tta)
  fi
  nnUNetv2_predict "${HISTORICAL_PREDICT_ARGS[@]}"
  nnUNetv2_evaluate_folder \
    "${RAW_DATASET_DIR}/labelsTsHistorical" \
    "${HISTORICAL_PREDICTION_DIR}" \
    -djfile "${RAW_DATASET_DIR}/dataset.json" \
    -pfile "${MODEL_FOLDER}/plans.json" \
    -o "${EVALUATION_DIR}/metrics_historical_nnunet.json" \
    -np "${EVAL_WORKERS}"
  python evaluation/evaluate_dji_road_crack.py \
    --ground-truth "${RAW_DATASET_DIR}/labelsTsHistorical" \
    --predictions "${HISTORICAL_PREDICTION_DIR}" \
    --output-json "${EVALUATION_DIR}/metrics_historical_binary.json" \
    --output-csv "${EVALUATION_DIR}/metrics_historical_per_case.csv"
fi

echo
echo "Fine-tuning and test evaluation completed."
echo "Best checkpoint: ${BEST_CHECKPOINT}"
echo "Split report: ${RAW_DATASET_DIR}/split_report.json"
echo "Official metrics: ${EVALUATION_DIR}/metrics_nnunet.json"
echo "Binary metrics: ${EVALUATION_DIR}/metrics_binary.json"
echo "Per-case metrics: ${EVALUATION_DIR}/metrics_per_case.csv"
if [[ -f "${EVALUATION_DIR}/metrics_historical_binary.json" ]]; then
  echo "Historical test metrics: ${EVALUATION_DIR}/metrics_historical_binary.json"
fi
echo "Full log: ${LOG_FILE}"
