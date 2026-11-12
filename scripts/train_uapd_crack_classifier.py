from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageEnhance


CLASS_NAME_MAP = {
    "Longitudinal crack": "longitudinal_crack",
    "Transverse crack": "transverse_crack",
    "Oblique crack": "oblique_crack",
    "Alligator crack": "alligator_crack",
    "Repair": "repair_or_pothole",
    "Pothole": "repair_or_pothole",
}
IGNORED_CLASSES = {"Block crack"}
CLASS_ORDER = [
    "alligator_crack",
    "longitudinal_crack",
    "oblique_crack",
    "repair_or_pothole",
    "transverse_crack",
]
RESAMPLE_BILINEAR = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
MODEL_CHOICES = ("mobilenet_v3_small", "efficientnet_b0", "efficientnet_v2_s", "convnext_tiny")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and train a lightweight UAPD crack classifier.")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("/home/HDD3/gty/datasets/UAPD_final"),
        help="UAPD dataset root containing JPEGImages/ and Annotations/.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/home/HDD3/gty/road-crack-demo/models/uapd_classifier"),
        help="Directory to store prepared crops, manifests, and checkpoints.",
    )
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--padding-ratio", type=float, default=0.25)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=18)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--model-name", choices=MODEL_CHOICES, default="efficientnet_v2_s")
    parser.add_argument("--selection-metric", choices=("accuracy", "macro_accuracy"), default="macro_accuracy")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only prepare grouped train/val crops and metadata, skip training.",
    )
    return parser.parse_args()


def _safe_parent_id(filename: str) -> str:
    return filename.split("_", 1)[0]


def _resolve_label(raw_name: str) -> str | None:
    if raw_name in IGNORED_CLASSES:
        return None
    return CLASS_NAME_MAP.get(raw_name)


def _iter_annotations(annotations_dir: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for xml_path in sorted(annotations_dir.glob("*.xml")):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        filename = (root.findtext("filename") or xml_path.with_suffix(".JPG").name).strip()
        image_width = int(root.findtext("size/width") or 0)
        image_height = int(root.findtext("size/height") or 0)
        objects: list[dict[str, object]] = []
        for obj in root.findall("object"):
            raw_name = (obj.findtext("name") or "").strip()
            label = _resolve_label(raw_name)
            if not label:
                continue
            bbox_node = obj.find("bndbox")
            if bbox_node is None:
                continue
            xmin = int(float(bbox_node.findtext("xmin") or 0))
            ymin = int(float(bbox_node.findtext("ymin") or 0))
            xmax = int(float(bbox_node.findtext("xmax") or 0))
            ymax = int(float(bbox_node.findtext("ymax") or 0))
            if xmax <= xmin or ymax <= ymin:
                continue
            objects.append(
                {
                    "raw_name": raw_name,
                    "label": label,
                    "bbox": [xmin, ymin, xmax, ymax],
                }
            )
        if not objects:
            continue
        records.append(
            {
                "xml_path": str(xml_path),
                "image_name": filename,
                "parent_id": _safe_parent_id(Path(filename).stem),
                "width": image_width,
                "height": image_height,
                "objects": objects,
            }
        )
    return records


def _group_split(records: list[dict[str, object]], val_ratio: float, seed: int) -> tuple[set[str], set[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        parent_id = str(record["parent_id"])
        for obj in record["objects"]:  # type: ignore[index]
            grouped[parent_id][obj["label"]] += 1  # type: ignore[index]

    rng = random.Random(seed)
    parent_ids = list(grouped.keys())
    rng.shuffle(parent_ids)

    total_counts = Counter()
    for counts in grouped.values():
        total_counts.update(counts)
    target_val = {key: count * val_ratio for key, count in total_counts.items()}
    val_counts = Counter()

    train_ids: set[str] = set()
    val_ids: set[str] = set()
    for parent_id in parent_ids:
        counts = grouped[parent_id]
        current_gap = sum(max(target_val[key] - val_counts[key], 0.0) for key in CLASS_ORDER)
        next_gap = sum(max(target_val[key] - (val_counts[key] + counts.get(key, 0)), 0.0) for key in CLASS_ORDER)
        place_in_val = len(val_ids) == 0 or next_gap < current_gap
        if place_in_val:
            val_ids.add(parent_id)
            val_counts.update(counts)
        else:
            train_ids.add(parent_id)

    if not train_ids:
        train_ids = set(parent_ids[:-1])
        val_ids = {parent_ids[-1]}
    if not val_ids:
        val_ids = {parent_ids[-1]}
        train_ids.discard(parent_ids[-1])
    return train_ids, val_ids


def _crop_box(image_width: int, image_height: int, bbox: list[int], padding_ratio: float) -> tuple[int, int, int, int]:
    xmin, ymin, xmax, ymax = bbox
    box_width = xmax - xmin
    box_height = ymax - ymin
    pad_x = max(8, int(round(box_width * padding_ratio)))
    pad_y = max(8, int(round(box_height * padding_ratio)))
    left = max(0, xmin - pad_x)
    top = max(0, ymin - pad_y)
    right = min(image_width, xmax + pad_x)
    bottom = min(image_height, ymax + pad_y)
    return left, top, right, bottom


def _prepare_dataset(records: list[dict[str, object]], dataset_root: Path, work_dir: Path, image_size: int, padding_ratio: float, seed: int, val_ratio: float) -> dict[str, object]:
    prepared_root = work_dir / "prepared"
    if prepared_root.exists():
        shutil.rmtree(prepared_root)
    train_ids, val_ids = _group_split(records, val_ratio=val_ratio, seed=seed)
    splits = {"train": train_ids, "val": val_ids}
    split_counts: dict[str, Counter[str]] = {"train": Counter(), "val": Counter()}
    manifest: list[dict[str, object]] = []

    for split_name, parent_ids in splits.items():
        for class_name in CLASS_ORDER:
            (prepared_root / split_name / class_name).mkdir(parents=True, exist_ok=True)

        for record in records:
            parent_id = str(record["parent_id"])
            if parent_id not in parent_ids:
                continue
            image_path = dataset_root / "JPEGImages" / str(record["image_name"])
            if not image_path.exists():
                continue
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
                for obj_index, obj in enumerate(record["objects"]):  # type: ignore[index]
                    class_name = str(obj["label"])
                    box = _crop_box(rgb.width, rgb.height, obj["bbox"], padding_ratio)  # type: ignore[index]
                    crop = rgb.crop(box).resize((image_size, image_size), RESAMPLE_BILINEAR)
                    crop_name = f"{Path(str(record['image_name'])).stem}_obj{obj_index:02d}.jpg"
                    crop_path = prepared_root / split_name / class_name / crop_name
                    crop.save(crop_path, format="JPEG", quality=95)
                    split_counts[split_name][class_name] += 1
                    manifest.append(
                        {
                            "split": split_name,
                            "class_name": class_name,
                            "crop_path": str(crop_path),
                            "image_name": record["image_name"],
                            "parent_id": parent_id,
                            "bbox": obj["bbox"],
                            "raw_name": obj["raw_name"],
                        }
                    )

    summary = {
        "class_order": CLASS_ORDER,
        "train_counts": dict(split_counts["train"]),
        "val_counts": dict(split_counts["val"]),
        "train_groups": sorted(train_ids),
        "val_groups": sorted(val_ids),
        "samples": manifest,
    }
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _import_training_modules():
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset
    from torchvision import models

    return torch, nn, DataLoader, Dataset, models


class SimpleCrackDataset:
    def __init__(self, items: list[tuple[Path, int]], image_size: int, training: bool = False) -> None:
        self.items = items
        self.image_size = image_size
        self.training = training

    def __len__(self) -> int:
        return len(self.items)

    def _augment(self, image: Image.Image) -> Image.Image:
        if random.random() < 0.5:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if random.random() < 0.2:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if random.random() < 0.8:
            image = ImageEnhance.Brightness(image).enhance(random.uniform(0.85, 1.15))
            image = ImageEnhance.Contrast(image).enhance(random.uniform(0.85, 1.2))
        return image

    def __getitem__(self, index: int):
        import torch

        path, label = self.items[index]
        with Image.open(path) as image:
            rgb = image.convert("RGB").resize((self.image_size, self.image_size), RESAMPLE_BILINEAR)
            if self.training:
                rgb = self._augment(rgb)
            tensor = torch.from_numpy(__import__("numpy").array(rgb, dtype="float32") / 255.0).permute(2, 0, 1)
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        tensor = (tensor - mean) / std
        return tensor, label


def _build_items(prepared_root: Path) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    train_items: list[tuple[Path, int]] = []
    val_items: list[tuple[Path, int]] = []
    for class_index, class_name in enumerate(CLASS_ORDER):
        train_items.extend((path, class_index) for path in sorted((prepared_root / "train" / class_name).glob("*.jpg")))
        val_items.extend((path, class_index) for path in sorted((prepared_root / "val" / class_name).glob("*.jpg")))
    return train_items, val_items


def _build_model(models_module, num_classes: int, model_name: str):
    torch = __import__("torch")
    if model_name == "mobilenet_v3_small":
        model = models_module.mobilenet_v3_small(weights=models_module.MobileNet_V3_Small_Weights.DEFAULT)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
        return model
    if model_name == "efficientnet_b0":
        model = models_module.efficientnet_b0(weights=models_module.EfficientNet_B0_Weights.DEFAULT)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
        return model
    if model_name == "efficientnet_v2_s":
        model = models_module.efficientnet_v2_s(weights=models_module.EfficientNet_V2_S_Weights.DEFAULT)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
        return model
    if model_name == "convnext_tiny":
        model = models_module.convnext_tiny(weights=models_module.ConvNeXt_Tiny_Weights.DEFAULT)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, num_classes)
        return model
    raise ValueError(f"Unsupported model_name: {model_name}")


def _build_weighted_sampler(train_items: list[tuple[Path, int]], torch_module):
    class_counts = Counter(label for _, label in train_items)
    sample_weights = [1.0 / max(class_counts[label], 1) for _, label in train_items]
    sample_weights_tensor = torch_module.tensor(sample_weights, dtype=torch_module.float32)
    return torch_module.utils.data.WeightedRandomSampler(
        weights=sample_weights_tensor,
        num_samples=len(train_items),
        replacement=True,
    )
    return model


def _evaluate(model, data_loader, device, torch_module):
    model.eval()
    total = 0
    correct = 0
    loss_total = 0.0
    criterion = torch_module.nn.CrossEntropyLoss()
    per_class_total = Counter()
    per_class_correct = Counter()
    with torch_module.no_grad():
        for images, labels in data_loader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            loss = criterion(logits, labels)
            predictions = logits.argmax(dim=1)
            total += labels.numel()
            correct += int((predictions == labels).sum().item())
            loss_total += float(loss.item()) * labels.size(0)
            for label, pred in zip(labels.cpu().tolist(), predictions.cpu().tolist()):
                per_class_total[int(label)] += 1
                if label == pred:
                    per_class_correct[int(label)] += 1
    per_class_accuracy = {
        CLASS_ORDER[class_index]: round(per_class_correct[class_index] / max(per_class_total[class_index], 1), 4)
        for class_index in range(len(CLASS_ORDER))
    }
    macro_accuracy = round(sum(per_class_accuracy.values()) / max(len(per_class_accuracy), 1), 4)
    return {
        "loss": round(loss_total / max(total, 1), 4),
        "accuracy": round(correct / max(total, 1), 4),
        "macro_accuracy": macro_accuracy,
        "per_class_accuracy": per_class_accuracy,
    }


def train_classifier(
    work_dir: Path,
    image_size: int,
    epochs: int,
    batch_size: int,
    lr: float,
    num_workers: int,
    model_name: str,
    selection_metric: str,
) -> dict[str, object]:
    torch, nn, DataLoader, Dataset, models = _import_training_modules()
    prepared_root = work_dir / "prepared"
    train_items, val_items = _build_items(prepared_root)
    if not train_items or not val_items:
        raise RuntimeError("Prepared dataset is empty. Please verify UAPD dataset conversion.")

    class _TorchDataset(Dataset):
        def __init__(self, wrapped: SimpleCrackDataset) -> None:
            self.wrapped = wrapped

        def __len__(self) -> int:
            return len(self.wrapped)

        def __getitem__(self, index: int):
            return self.wrapped[index]

    train_dataset = _TorchDataset(SimpleCrackDataset(train_items, image_size=image_size, training=True))
    val_dataset = _TorchDataset(SimpleCrackDataset(val_items, image_size=image_size, training=False))
    train_sampler = _build_weighted_sampler(train_items, torch)
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        sampler=train_sampler,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _build_model(models, len(CLASS_ORDER), model_name=model_name).to(device)
    class_counts = Counter(label for _, label in train_items)
    max_count = max(class_counts.values())
    weights = torch.tensor(
        [max_count / max(class_counts.get(class_index, 1), 1) for class_index in range(len(CLASS_ORDER))],
        dtype=torch.float32,
        device=device,
    )
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(epochs, 1))

    best_state = None
    best_score = -math.inf
    history: list[dict[str, object]] = []

    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        total = 0
        correct = 0
        for images, labels in train_loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            running_loss += float(loss.item()) * labels.size(0)
            predictions = logits.argmax(dim=1)
            total += labels.numel()
            correct += int((predictions == labels).sum().item())
        scheduler.step()

        train_metrics = {
            "loss": round(running_loss / max(total, 1), 4),
            "accuracy": round(correct / max(total, 1), 4),
        }
        val_metrics = _evaluate(model, val_loader, device, torch)
        epoch_metrics = {"epoch": epoch, "train": train_metrics, "val": val_metrics}
        history.append(epoch_metrics)
        print(json.dumps(epoch_metrics, ensure_ascii=False))

        current_score = float(val_metrics[selection_metric])
        if current_score > best_score:
            best_score = current_score
            best_state = {
                "model_state": model.state_dict(),
                "model_name": model_name,
                "class_names": CLASS_ORDER,
                "image_size": image_size,
                "normalization": {
                    "mean": [0.485, 0.456, 0.406],
                    "std": [0.229, 0.224, 0.225],
                },
                "selection_metric": selection_metric,
                "best_val_accuracy": float(val_metrics["accuracy"]),
                "best_val_macro_accuracy": float(val_metrics["macro_accuracy"]),
                "best_val_score": current_score,
            }

    if best_state is None:
        raise RuntimeError("Training did not produce a checkpoint.")

    checkpoint_path = work_dir / "best.pt"
    work_dir.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, checkpoint_path)
    latest_path = work_dir.parent / f"uapd_crack_classifier_{model_name}.pt"
    shutil.copy2(checkpoint_path, latest_path)
    summary = {
        "checkpoint_path": str(checkpoint_path),
        "latest_checkpoint_path": str(latest_path),
        "model_name": model_name,
        "selection_metric": selection_metric,
        "best_val_accuracy": round(float(best_state["best_val_accuracy"]), 4),
        "best_val_macro_accuracy": round(float(best_state["best_val_macro_accuracy"]), 4),
        "best_val_score": round(float(best_state["best_val_score"]), 4),
        "history": history,
    }
    (work_dir / "train_history.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    records = _iter_annotations(args.dataset_root / "Annotations")
    summary = _prepare_dataset(
        records=records,
        dataset_root=args.dataset_root,
        work_dir=args.work_dir,
        image_size=args.image_size,
        padding_ratio=args.padding_ratio,
        seed=args.seed,
        val_ratio=args.val_ratio,
    )
    print(json.dumps({"prepared": True, "summary_path": str(args.work_dir / "dataset_summary.json")}, ensure_ascii=False))
    if args.prepare_only:
        return
    result = train_classifier(
        work_dir=args.work_dir,
        image_size=args.image_size,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        num_workers=args.num_workers,
        model_name=args.model_name,
        selection_metric=args.selection_metric,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
