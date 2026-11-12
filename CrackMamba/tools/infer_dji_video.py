#!/usr/bin/env python3
from pathlib import Path
import argparse
import subprocess

import torch
from batchgenerators.utilities.file_and_folder_operations import maybe_mkdir_p
from skimage import io

from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
from nnunetv2.nets.CrackMamba import get_crackmamba_from_plans
from nnunetv2.utilities.label_handling.label_handling import determine_num_input_channels
from nnunetv2.utilities.plans_handling.plans_handler import PlansManager


def extract_frames(video_path: Path, frames_dir: Path) -> None:
    maybe_mkdir_p(frames_dir)
    pattern = str(frames_dir / "frame_%06d.png")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", "fps=1", pattern],
        check=True,
    )


def split_frames_into_quadrants(frames_dir: Path, tiles_dir: Path) -> None:
    maybe_mkdir_p(tiles_dir)
    frame_paths = sorted(frames_dir.glob("frame_*.png"))
    quadrant_names = ("tl", "tr", "bl", "br")

    for frame_path in frame_paths:
        image = io.imread(frame_path)
        height, width = image.shape[:2]
        half_h = height // 2
        half_w = width // 2

        tiles = (
            image[:half_h, :half_w],
            image[:half_h, half_w:],
            image[half_h:, :half_w],
            image[half_h:, half_w:],
        )

        frame_stem = frame_path.stem
        for quadrant_name, tile in zip(quadrant_names, tiles):
            tile_path = tiles_dir / f"{frame_stem}_{quadrant_name}_0000.png"
            io.imsave(tile_path, tile, check_contrast=False)


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
        allow_tqdm=True,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default="DJI_20260609164611_0003_Z - Trim.mp4")
    parser.add_argument("--checkpoint", default="CrackSeg9k_checkpoint_best.pth")
    parser.add_argument("--output-dir", default="runs/DJI_imgs")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--npp", type=int, default=3)
    parser.add_argument("--nps", type=int, default=3)
    args = parser.parse_args()

    video_path = Path(args.video)
    checkpoint_path = Path(args.checkpoint)
    output_dir = Path(args.output_dir)
    frames_dir = output_dir / "frames"
    tiles_dir = output_dir / "tiles"

    maybe_mkdir_p(output_dir)
    extract_frames(video_path, frames_dir)
    split_frames_into_quadrants(frames_dir, tiles_dir)

    device = torch.device(args.device)
    predictor = build_predictor(checkpoint_path, device)
    predictor.predict_from_files(
        str(tiles_dir),
        str(output_dir),
        overwrite=True,
        num_processes_preprocessing=args.npp,
        num_processes_segmentation_export=args.nps,
        folder_with_segs_from_prev_stage=None,
        num_parts=1,
        part_id=0,
        save_probabilities=False,
    )


if __name__ == "__main__":
    main()
