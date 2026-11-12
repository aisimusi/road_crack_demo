from __future__ import annotations

import os

import torch

from nnunetv2.training.nnUNetTrainer.nnUNetTrainerCrackMamba import (
    nnUNetTrainerCrackMamba,
)


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {value}")
    return value


def _non_negative_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {value}")
    return value


class nnUNetTrainerCrackMambaFinetune(nnUNetTrainerCrackMamba):
    """CrackMamba fine-tuning settings for the small DJI road-crack dataset."""

    def __init__(
        self,
        plans: dict,
        configuration: str,
        fold: int,
        dataset_json: dict,
        unpack_dataset: bool = True,
        device: torch.device = torch.device("cuda"),
    ):
        super().__init__(plans, configuration, fold, dataset_json, unpack_dataset, device)
        patch_size = tuple(int(value) for value in self.configuration_manager.patch_size)
        if len(patch_size) != 2 or patch_size[0] != patch_size[1]:
            raise ValueError(
                "CrackMamba Snake Scan requires a square 2D patch, but the plan uses "
                f"{patch_size}. Run tools/configure_crackmamba_2d_plan.py first."
            )
        self.num_epochs = _positive_int("FINETUNE_EPOCHS", 100)
        self.initial_lr = _positive_float("FINETUNE_LR", 5e-5)
        self.freeze_encoder_epochs = _non_negative_int(
            "FINETUNE_FREEZE_ENCODER_EPOCHS", 5
        )
        self.save_every = _positive_int("FINETUNE_SAVE_EVERY", 10)
        self.num_iterations_per_epoch = _positive_int("FINETUNE_TRAIN_ITERS", 100)
        self.num_val_iterations_per_epoch = _positive_int("FINETUNE_VAL_ITERS", 25)
