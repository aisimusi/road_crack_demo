import torch
import os

from nnunetv2.training.nnUNetTrainer.nnUNetTrainerCrackMamba import nnUNetTrainerCrackMamba


def _save_every_from_env(default: int = 50) -> int:
    return int(os.environ.get("SAVE_EVERY", default))


class nnUNetTrainerCrackMamba_1epoch(nnUNetTrainerCrackMamba):
    def __init__(self, plans: dict, configuration: str, fold: int, dataset_json: dict, unpack_dataset: bool = True,
                 device: torch.device = torch.device('cuda')):
        super().__init__(plans, configuration, fold, dataset_json, unpack_dataset, device)
        self.num_epochs = 1
        self.save_every = _save_every_from_env()


class nnUNetTrainerCrackMamba_5epochs(nnUNetTrainerCrackMamba):
    def __init__(self, plans: dict, configuration: str, fold: int, dataset_json: dict, unpack_dataset: bool = True,
                 device: torch.device = torch.device('cuda')):
        super().__init__(plans, configuration, fold, dataset_json, unpack_dataset, device)
        self.num_epochs = 5
        self.save_every = _save_every_from_env()


class nnUNetTrainerCrackMamba_500epochs(nnUNetTrainerCrackMamba):
    def __init__(self, plans: dict, configuration: str, fold: int, dataset_json: dict, unpack_dataset: bool = True,
                 device: torch.device = torch.device('cuda')):
        super().__init__(plans, configuration, fold, dataset_json, unpack_dataset, device)
        self.num_epochs = 500
        self.save_every = _save_every_from_env()
