#!/usr/bin/env python3
from pathlib import Path
import argparse

import numpy as np
from skimage import io


def make_overlay(image: np.ndarray, mask: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if image.ndim == 2:
        image = np.repeat(image[:, :, None], 3, axis=2)
    image = image.astype(np.float32)
    if image.max() > 1:
        image = image / 255.0

    overlay = image.copy()
    red = np.zeros_like(overlay)
    red[..., 0] = 1.0
    mask = mask > 0
    overlay[mask] = (1 - alpha) * overlay[mask] + alpha * red[mask]
    return (np.clip(overlay, 0, 1) * 255).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="runs/DJI_imgs")
    parser.add_argument("--output-dir", default="runs/DJI_imgs/overlays")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for mask_path in sorted(input_dir.glob("frame_*.png")):
        if mask_path.parent.name in {"frames", "tiles", "overlays"}:
            continue
        tile_name = mask_path.name
        image_path = input_dir / "tiles" / f"{mask_path.stem}_0000.png"
        if not image_path.exists():
            continue
        image = io.imread(image_path)
        mask = io.imread(mask_path)
        overlay = make_overlay(image, mask)
        io.imsave(output_dir / tile_name, overlay, check_contrast=False)


if __name__ == "__main__":
    main()
