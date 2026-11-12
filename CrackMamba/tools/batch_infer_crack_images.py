#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from batchgenerators.utilities.file_and_folder_operations import maybe_mkdir_p
from skimage import io

from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
from nnunetv2.nets.CrackMamba import get_crackmamba_from_plans
from nnunetv2.utilities.label_handling.label_handling import determine_num_input_channels
from nnunetv2.utilities.plans_handling.plans_handler import PlansManager


def build_predictor(checkpoint_path: Path, device: torch.device) -> nnUNetPredictor:
    ckpt = torch.load(checkpoint_path, map_location="cpu")
    dataset_json = ckpt["init_args"]["dataset_json"]
    plans = ckpt["init_args"]["plans"]
    configuration = ckpt["init_args"]["configuration"]

    plans_manager = PlansManager(plans)
    configuration_manager = plans_manager.get_configuration(configuration)
    num_input_channels = determine_num_input_channels(plans_manager, configuration_manager, dataset_json)

    network = get_crackmamba_from_plans(
        plans_manager,
        dataset_json,
        configuration_manager,
        num_input_channels,
        deep_supervision=False,
        use_pretrain=False,
    )

    state_dict = ckpt["network_weights"]
    try:
        network.load_state_dict(state_dict, strict=True)
    except RuntimeError:
        state_dict = {k.removeprefix("module."): v for k, v in state_dict.items()}
        network.load_state_dict(state_dict, strict=True)

    network.to(device)
    network.eval()

    predictor = nnUNetPredictor(
        tile_step_size=0.5,
        use_gaussian=True,
        use_mirroring=True,
        perform_everything_on_device=(device.type == "cuda"),
        device=device,
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=False,
    )
    predictor.manual_initialization(
        network,
        plans_manager,
        configuration_manager,
        [state_dict],
        dataset_json,
        ckpt.get("trainer_name", "CrackMamba"),
        ckpt.get("inference_allowed_mirroring_axes"),
    )
    return predictor


def prepare_image(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 3, axis=2)
    elif image.ndim == 3 and image.shape[2] == 1:
        image = np.repeat(image, 3, axis=2)
    elif image.ndim == 3 and image.shape[2] >= 4:
        image = image[:, :, :3]
    elif image.ndim != 3:
        raise ValueError(f"Unsupported image shape: {image.shape}")

    image = np.ascontiguousarray(image)
    data = image.transpose(2, 0, 1)[:, None].astype(np.float32)
    return image, data


def make_overlay(image: np.ndarray, mask: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    image = image.astype(np.float32)
    if image.max() > 1:
        image = image / 255.0

    overlay = image.copy()
    blue = np.zeros_like(overlay)
    blue[..., 2] = 1.0
    mask = mask > 0
    overlay[mask] = (1 - alpha) * overlay[mask] + alpha * blue[mask]
    return (np.clip(overlay, 0, 1) * 255).astype(np.uint8)


def summarize_mask(mask: np.ndarray) -> dict:
    ys, xs = np.where(mask > 0)
    area_px = int(mask.sum())
    has_crack = area_px > 0

    if not has_crack:
        return {
            "has_crack": False,
            "bbox": {"x": 0, "y": 0, "width": 0, "height": 0},
            "crack_type": "none",
            "severity_level": 0,
            "severity_label": "未检测到",
            "severity_score": 0.0,
            "length_m": 0.0,
            "avg_width_cm": 0.0,
            "max_width_cm": 0.0,
            "area_m2": 0.0,
        }

    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    bbox = {"x": x1, "y": y1, "width": x2 - x1 + 1, "height": y2 - y1 + 1}
    crack_type = "longitudinal" if bbox["width"] >= bbox["height"] else "transverse"
    severity_level = 3 if area_px > 2500 else 2 if area_px > 800 else 1
    severity_label = {1: "轻微", 2: "中等", 3: "严重"}[severity_level]

    return {
        "has_crack": True,
        "bbox": bbox,
        "crack_type": crack_type,
        "severity_level": severity_level,
        "severity_label": severity_label,
        "severity_score": float(min(0.99, 0.25 + area_px / max(mask.size, 1))),
        "length_m": round(max(bbox["width"], bbox["height"]) / 100.0, 2),
        "avg_width_cm": round(max(1.0, min(15.0, area_px / max(max(bbox["width"], bbox["height"]), 1) / 10.0)), 2),
        "max_width_cm": round(max(1.0, min(20.0, area_px / max(min(bbox["width"], bbox["height"]) + 1, 1) / 8.0)), 2),
        "area_m2": round(area_px / 10000.0, 4),
    }


def infer_one_image(predictor: nnUNetPredictor, image_path: Path, output_dir: Path) -> dict:
    image = io.imread(image_path)
    image, data = prepare_image(image)
    props = {"spacing": (999, 1, 1)}
    pred = predictor.predict_single_npy_array(data, props, None, None, False)
    pred = np.asarray(pred)

    if pred.ndim == 3 and pred.shape[0] == 1:
        pred = pred[0]
    if pred.ndim != 2:
        raise RuntimeError(f"Unexpected prediction shape for {image_path.name}: {pred.shape}")

    mask = (pred > 0).astype(np.uint8)
    result_path = output_dir / f"{image_path.stem}_result.png"
    overlay_path = output_dir / f"{image_path.stem}_overlay.png"
    io.imsave(result_path, (mask * 255).astype(np.uint8), check_contrast=False)
    io.imsave(overlay_path, make_overlay(image, mask), check_contrast=False)

    summary = summarize_mask(mask)
    return {
        "image_name": image_path.name,
        "result_image": result_path.name,
        "overlay_image": overlay_path.name,
        **summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--checkpoint", default="CrackSeg9k_checkpoint_best.pth")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    maybe_mkdir_p(output_dir)

    device = torch.device(args.device)
    predictor = build_predictor(Path(args.checkpoint), device)

    _ = max(1, args.batch_size)
    results = []
    for image_path in sorted(input_dir.iterdir()):
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            continue
        results.append(infer_one_image(predictor, image_path, output_dir))

    (output_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
