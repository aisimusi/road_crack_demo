from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image


HEURISTIC_CLASS_NAMES = [
    "alligator_crack",
    "longitudinal_crack",
    "oblique_crack",
    "repair_or_pothole",
    "transverse_crack",
]
RESAMPLE_BILINEAR = getattr(getattr(Image, "Resampling", Image), "BILINEAR")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch classify crack crops into UAPD-style classes.")
    parser.add_argument("--input-json", type=Path, required=True, help="JSON list describing crop image paths and optional fallback labels.")
    parser.add_argument("--output-json", type=Path, required=True, help="Where to write predictions.")
    parser.add_argument("--checkpoint", type=Path, required=True, help="Torch checkpoint produced by train_uapd_crack_classifier.py.")
    parser.add_argument("--device", default="cuda", help="Torch device string, e.g. cuda or cpu.")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--emit-embeddings", action="store_true", help="Also export penultimate-layer embeddings.")
    return parser.parse_args()


def _load_items(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mask_bbox_from_item(item: dict[str, object]) -> dict[str, int]:
    bbox = item.get("bbox") or {}
    return {
        "x": int(bbox.get("x", 0)),
        "y": int(bbox.get("y", 0)),
        "width": int(bbox.get("width", 0)),
        "height": int(bbox.get("height", 0)),
    }


def _heuristic_predict(item: dict[str, object]) -> tuple[str, float]:
    bbox = _mask_bbox_from_item(item)
    width = max(1, bbox["width"])
    height = max(1, bbox["height"])
    aspect_ratio = max(width, height) / max(min(width, height), 1)
    fallback = str(item.get("fallback_crack_type") or "longitudinal_crack")
    if width * height <= 0:
        return fallback, 0.0
    if aspect_ratio < 1.4:
        return "alligator_crack", 0.6
    if fallback == "transverse_crack":
        return "transverse_crack", 0.58
    if fallback == "longitudinal_crack":
        return "longitudinal_crack", 0.58
    return fallback, 0.4


def _load_model(checkpoint_path: Path, device_name: str):
    import torch
    from torchvision import models

    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    class_names = checkpoint.get("class_names") or HEURISTIC_CLASS_NAMES
    model_name = str(checkpoint.get("model_name") or "mobilenet_v3_small")
    if model_name == "mobilenet_v3_small":
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(class_names))
    elif model_name == "efficientnet_b0":
        model = models.efficientnet_b0(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(class_names))
    elif model_name == "efficientnet_v2_s":
        model = models.efficientnet_v2_s(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(class_names))
    elif model_name == "convnext_tiny":
        model = models.convnext_tiny(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = torch.nn.Linear(in_features, len(class_names))
    else:
        raise ValueError(f"Unsupported model_name in checkpoint: {model_name}")
    model.load_state_dict(checkpoint["model_state"])
    device = torch.device(device_name if device_name == "cpu" or torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    image_size = int(checkpoint.get("image_size") or 224)
    normalization = checkpoint.get("normalization") or {
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
    }
    return torch, model, class_names, image_size, normalization, device, model_name


def _extract_backbone_features(model, batch, model_name: str):
    if model_name == "mobilenet_v3_small":
        features = model.features(batch)
        features = model.avgpool(features)
        return features.flatten(1)
    if model_name in {"efficientnet_b0", "efficientnet_v2_s"}:
        features = model.features(batch)
        features = model.avgpool(features)
        return features.flatten(1)
    if model_name == "convnext_tiny":
        features = model.features(batch)
        features = model.avgpool(features)
        return model.classifier[0](features.flatten(1))
    raise ValueError(f"Unsupported model_name for embedding extraction: {model_name}")


def _normalize_embedding(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return values
    return [value / norm for value in values]


def _preprocess_image(image_path: Path, image_size: int, normalization: dict[str, list[float]]):
    import numpy as np
    import torch

    with Image.open(image_path) as image:
        rgb = image.convert("RGB").resize((image_size, image_size), RESAMPLE_BILINEAR)
    tensor = torch.from_numpy(np.array(rgb, dtype="float32") / 255.0).permute(2, 0, 1)
    mean = torch.tensor(normalization["mean"], dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(normalization["std"], dtype=torch.float32).view(3, 1, 1)
    return (tensor - mean) / std


def classify_items(args: argparse.Namespace) -> dict[str, object]:
    items = _load_items(args.input_json)
    if not items:
        result = {"predictions": [], "model_available": args.checkpoint.exists()}
        args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    if not args.checkpoint.exists():
        predictions = []
        for item in items:
            label, confidence = _heuristic_predict(item)
            predictions.append(
                {
                    "record_id": item.get("record_id"),
                    "predicted_class": label,
                    "confidence": round(confidence, 4),
                    "used_fallback": True,
                    "fallback_reason": "checkpoint_missing",
                    "embedding": None,
                }
            )
        result = {"predictions": predictions, "model_available": False}
        args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    torch, model, class_names, image_size, normalization, device, model_name = _load_model(args.checkpoint, args.device)
    tensors = []
    valid_items = []
    predictions: list[dict[str, object]] = []
    for item in items:
        image_path = Path(str(item["image_path"]))
        if not image_path.exists():
            label, confidence = _heuristic_predict(item)
            predictions.append(
                {
                    "record_id": item.get("record_id"),
                    "predicted_class": label,
                    "confidence": round(confidence, 4),
                    "used_fallback": True,
                    "fallback_reason": "image_missing",
                    "embedding": None,
                }
            )
            continue
        tensors.append(_preprocess_image(image_path, image_size, normalization))
        valid_items.append(item)

    if valid_items:
        with torch.no_grad():
            for start in range(0, len(valid_items), args.batch_size):
                end = min(start + args.batch_size, len(valid_items))
                batch = torch.stack(tensors[start:end]).to(device)
                embedding_batch = _extract_backbone_features(model, batch, model_name)
                logits = model(batch)
                probabilities = torch.softmax(logits, dim=1).cpu()
                embeddings = embedding_batch.cpu().tolist() if args.emit_embeddings else [None] * len(valid_items[start:end])
                for item, probs, embedding in zip(valid_items[start:end], probabilities, embeddings):
                    confidence, class_index = probs.max(dim=0)
                    predicted_class = class_names[int(class_index)]
                    used_fallback = False
                    fallback_reason = ""
                    if float(confidence) < args.min_confidence:
                        predicted_class, fallback_confidence = _heuristic_predict(item)
                        confidence = torch.tensor(max(float(confidence), fallback_confidence))
                        used_fallback = True
                        fallback_reason = "low_confidence"
                    predictions.append(
                        {
                            "record_id": item.get("record_id"),
                            "predicted_class": predicted_class,
                            "confidence": round(float(confidence), 4),
                            "used_fallback": used_fallback,
                            "fallback_reason": fallback_reason,
                            "embedding": _normalize_embedding([float(value) for value in embedding]) if embedding is not None else None,
                        }
                    )

    predictions.sort(key=lambda item: int(item.get("record_id") or 0))
    result = {
        "predictions": predictions,
        "model_available": True,
        "class_names": class_names,
        "model_name": model_name,
    }
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    args = parse_args()
    result = classify_items(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
