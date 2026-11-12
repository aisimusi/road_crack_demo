#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/HDD3/gty/road-crack-demo/CrackMamba"
CONDA_SH="/home/ubuntu/anaconda3/etc/profile.d/conda.sh"
CONDA_ENV="crackmamba"
GPU_ID="${GPU_ID:-0}"
EPOCHS="${EPOCHS:-1}"
BATCH_SIZE="${BATCH_SIZE:-}"
KEEP_ONLY_BEST="${KEEP_ONLY_BEST:-1}"

DATASET_ID="228"
DATASET_NAME="Dataset228_UAVImageCrack"
if [[ -z "${TRAINER:-}" ]]; then
  if [[ "${EPOCHS}" == "1" ]]; then
    TRAINER="nnUNetTrainerCrackMamba_1epoch"
  elif [[ "${EPOCHS}" == "5" || "${EPOCHS}" == "500" ]]; then
    TRAINER="nnUNetTrainerCrackMamba_${EPOCHS}epochs"
  else
    echo "Unsupported EPOCHS=${EPOCHS}. Use EPOCHS=1, EPOCHS=5, EPOCHS=500, or set TRAINER explicitly." >&2
    exit 2
  fi
fi
PRETRAINED_WEIGHTS="${REPO_ROOT}/CrackSeg9k_checkpoint_best.pth"
PRED_OUTPUT="${REPO_ROOT}/nnUNet_results/${DATASET_NAME}/${TRAINER}__nnUNetPlans__2d/pred_results"
MODEL_FOLDER="${REPO_ROOT}/nnUNet_results/${DATASET_NAME}/${TRAINER}__nnUNetPlans__2d"
BEST_MODEL_FOLDER="${REPO_ROOT}/nnUNet_results/${DATASET_NAME}/best_test"

cd "${REPO_ROOT}"
set +u
source "${CONDA_SH}"
conda activate "${CONDA_ENV}"
set -u

python tools/prepare_uav_crack_nnunet.py \
  --source-root /home/HDD3/gty/datasets/uav-crack \
  --nnunet-raw nnUNet_raw \
  --dataset uav_image

nnUNetv2_plan_and_preprocess \
  -d "${DATASET_ID}" \
  -c 2d \
  --verify_dataset_integrity

if [[ -n "${BATCH_SIZE}" ]]; then
  python tools/set_nnunet_2d_batch_size.py \
    "nnUNet_preprocessed/${DATASET_NAME}/nnUNetPlans.json" \
    "${BATCH_SIZE}"
fi

CUDA_VISIBLE_DEVICES="${GPU_ID}" nnUNetv2_train \
  "${DATASET_ID}" 2d all \
  -tr "${TRAINER}" \
  -pretrained_weights "${PRETRAINED_WEIGHTS}" \
  -num_gpus 1

CUDA_VISIBLE_DEVICES="${GPU_ID}" nnUNetv2_predict \
  -i "nnUNet_raw/${DATASET_NAME}/imagesTs" \
  -o "${PRED_OUTPUT}" \
  -d "${DATASET_ID}" \
  -c 2d \
  -tr "${TRAINER}" \
  -f all \
  -chk checkpoint_best.pth \
  --disable_tta

python evaluation/compute_CrackSeg9k.py \
  --gt_path "nnUNet_raw/${DATASET_NAME}/labelsTs" \
  -s "${PRED_OUTPUT}"

CLEAN_ARG=()
if [[ "${KEEP_ONLY_BEST}" == "1" ]]; then
  CLEAN_ARG+=(--keep-only-global-best-in-checkpoint-dir)
fi

python tools/compare_and_keep_best_checkpoint.py \
  --gt-path "nnUNet_raw/${DATASET_NAME}/labelsTs" \
  --pred-path "${PRED_OUTPUT}" \
  --checkpoint "${MODEL_FOLDER}/fold_all/checkpoint_best.pth" \
  --model-folder "${MODEL_FOLDER}" \
  --best-model-folder "${BEST_MODEL_FOLDER}" \
  --dataset-name "${DATASET_NAME}" \
  --run-name "${TRAINER}" \
  --primary-metric f1 \
  "${CLEAN_ARG[@]}"
