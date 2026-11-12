#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

import numpy as np
from skimage import io


DATASETS = {
    "uav_image": {
        "id": 228,
        "name": "UAVImageCrack",
    },
    "earthquake_crack": {
        "id": 229,
        "name": "EarthquakeCrack",
    },
}


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_dataset_json(dataset_dir: Path, dataset_name: str, num_training: int) -> None:
    dataset_json = {
        "channel_names": {"0": "R", "1": "G", "2": "B"},
        "labels": {"background": 0, "crack": 1},
        "numTraining": num_training,
        "file_ending": ".png",
        "name": dataset_name,
        "overwrite_image_reader_writer": "NaturalImage2DIO",
    }
    (dataset_dir / "dataset.json").write_text(json.dumps(dataset_json, indent=4), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    image = io.imread(path)
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 3, axis=2)
    elif image.ndim == 3 and image.shape[2] == 1:
        image = np.repeat(image, 3, axis=2)
    elif image.ndim == 3 and image.shape[2] >= 4:
        image = image[:, :, :3]
    elif image.ndim != 3:
        raise ValueError(f"Unsupported image shape for {path}: {image.shape}")
    return image.astype(np.uint8, copy=False)


def _read_mask(path: Path) -> np.ndarray:
    mask = io.imread(path, as_gray=True)
    mask = (mask > 0).astype(np.uint8)
    return mask


def _copy_case(image_path: Path, label_path: Path, images_dir: Path, labels_dir: Path, case_id: str) -> None:
    io.imsave(images_dir / f"{case_id}_0000.png", _read_rgb(image_path), check_contrast=False)
    io.imsave(labels_dir / f"{case_id}.png", _read_mask(label_path), check_contrast=False)


def _paired_cases(image_dir: Path, label_dir: Path, image_suffix: str = ".jpg", label_suffix: str = ".png") -> list[str]:
    image_ids = {p.stem for p in image_dir.glob(f"*{image_suffix}") if p.is_file()}
    label_ids = {p.stem for p in label_dir.glob(f"*{label_suffix}") if p.is_file()}
    return sorted(image_ids & label_ids)


def prepare_uav_image(source_root: Path, nnunet_raw: Path, seed: int, train_fraction: float) -> None:
    cfg = DATASETS["uav_image"]
    dataset_dir = nnunet_raw / f"Dataset{cfg['id']:03d}_{cfg['name']}"
    images_tr = dataset_dir / "imagesTr"
    labels_tr = dataset_dir / "labelsTr"
    images_ts = dataset_dir / "imagesTs"
    labels_ts = dataset_dir / "labelsTs"
    for folder in (images_tr, labels_tr, images_ts, labels_ts):
        _reset_dir(folder)

    source = source_root / "UAV_image"
    ids = _paired_cases(source / "img", source / "labels")
    rng = random.Random(seed)
    rng.shuffle(ids)
    train_count = int(round(len(ids) * train_fraction))
    train_ids = sorted(ids[:train_count])
    test_ids = sorted(ids[train_count:])

    for case_id in train_ids:
        _copy_case(source / "img" / f"{case_id}.jpg", source / "labels" / f"{case_id}.png", images_tr, labels_tr, case_id)
    for case_id in test_ids:
        _copy_case(source / "img" / f"{case_id}.jpg", source / "labels" / f"{case_id}.png", images_ts, labels_ts, case_id)

    _write_dataset_json(dataset_dir, cfg["name"], len(train_ids))
    print(f"{dataset_dir}: train={len(train_ids)} test={len(test_ids)}")


def prepare_earthquake_crack(source_root: Path, nnunet_raw: Path) -> None:
    cfg = DATASETS["earthquake_crack"]
    dataset_dir = nnunet_raw / f"Dataset{cfg['id']:03d}_{cfg['name']}"
    images_tr = dataset_dir / "imagesTr"
    labels_tr = dataset_dir / "labelsTr"
    images_ts = dataset_dir / "imagesTs"
    labels_ts = dataset_dir / "labelsTs"
    for folder in (images_tr, labels_tr, images_ts, labels_ts):
        _reset_dir(folder)

    source = source_root / "earthquake_crack"
    train_ids = []
    for split in ("train", "val"):
        ids = _paired_cases(source / split, source / f"{split}_labels")
        for case_id in ids:
            out_id = f"{split}_{case_id}"
            _copy_case(source / split / f"{case_id}.jpg", source / f"{split}_labels" / f"{case_id}.png", images_tr, labels_tr, out_id)
        train_ids.extend(f"{split}_{case_id}" for case_id in ids)

    test_ids = _paired_cases(source / "test", source / "test_labels")
    for case_id in test_ids:
        _copy_case(source / "test" / f"{case_id}.jpg", source / "test_labels" / f"{case_id}.png", images_ts, labels_ts, case_id)

    _write_dataset_json(dataset_dir, cfg["name"], len(train_ids))
    print(f"{dataset_dir}: train={len(train_ids)} test={len(test_ids)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare UAV crack datasets in nnU-Net raw format.")
    parser.add_argument("--source-root", type=Path, default=Path("/home/HDD3/gty/datasets/uav-crack"))
    parser.add_argument("--nnunet-raw", type=Path, default=Path("nnUNet_raw"))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--train-fraction", type=float, default=0.8)
    parser.add_argument(
        "--dataset",
        choices=("all", "uav_image", "earthquake_crack"),
        default="all",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 < args.train_fraction < 1:
        raise ValueError("--train-fraction must be between 0 and 1")

    source_root = args.source_root.resolve()
    nnunet_raw = args.nnunet_raw.resolve()
    nnunet_raw.mkdir(parents=True, exist_ok=True)

    if args.dataset in ("all", "uav_image"):
        prepare_uav_image(source_root, nnunet_raw, args.seed, args.train_fraction)
    if args.dataset in ("all", "earthquake_crack"):
        prepare_earthquake_crack(source_root, nnunet_raw)


if __name__ == "__main__":
    main()
