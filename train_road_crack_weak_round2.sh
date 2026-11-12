#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export ANNOTATION_ROOT="${ANNOTATION_ROOT:-${PROJECT_ROOT}/annotations/road_crack}"
export ADDITIONAL_ANNOTATION_ROOT="${ADDITIONAL_ANNOTATION_ROOT:-${PROJECT_ROOT}/annotations/road_crack_weak}"
export DATASET_ID="${DATASET_ID:-231}"
export DATASET_SHORT_NAME="${DATASET_SHORT_NAME:-DJIRoadCrackWeakRound2}"
export PRETRAINED_WEIGHTS="${PRETRAINED_WEIGHTS:-${PROJECT_ROOT}/CrackMamba/nnUNet_results/Dataset230_DJIRoadCrack/nnUNetTrainerCrackMambaFinetune__nnUNetPlans__2d/fold_0/checkpoint_best.pth}"

export FINETUNE_EPOCHS="${FINETUNE_EPOCHS:-50}"
export FINETUNE_LR="${FINETUNE_LR:-2e-5}"
export FINETUNE_FREEZE_ENCODER_EPOCHS="${FINETUNE_FREEZE_ENCODER_EPOCHS:-0}"
export FINETUNE_SAVE_EVERY="${FINETUNE_SAVE_EVERY:-10}"
export FINETUNE_TRAIN_ITERS="${FINETUNE_TRAIN_ITERS:-100}"
export FINETUNE_VAL_ITERS="${FINETUNE_VAL_ITERS:-25}"
export FINETUNE_PATCH_SIZE="${FINETUNE_PATCH_SIZE:-448}"
export BATCH_SIZE="${BATCH_SIZE:-2}"
export REBUILD_DATASET="${REBUILD_DATASET:-0}"

exec "${PROJECT_ROOT}/train_road_crack_finetune.sh" "$@"
