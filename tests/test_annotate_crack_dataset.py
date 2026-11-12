from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from annotate_crack_dataset import (  # noqa: E402
    VideoInfo,
    access_urls,
    build_candidates,
    decode_mask,
    quadrant_bounds,
    sampled_frame_indices,
)


class SamplingTests(unittest.TestCase):
    def test_wildcard_host_uses_loopback_for_local_browser(self) -> None:
        local_url, _ = access_urls("0.0.0.0", 8765)
        self.assertEqual(local_url, "http://127.0.0.1:8765")

    def test_samples_are_evenly_spaced_inside_video(self) -> None:
        self.assertEqual(sampled_frame_indices(10, 3), [2, 4, 7])
        self.assertEqual(sampled_frame_indices(1, 3), [0])

    def test_quadrants_cover_odd_sized_frame_without_overlap(self) -> None:
        bounds = [quadrant_bounds(5, 3, quadrant) for quadrant in ("tl", "tr", "bl", "br")]
        self.assertEqual(bounds, [(0, 0, 2, 1), (2, 0, 5, 1), (0, 1, 2, 3), (2, 1, 5, 3)])
        coverage = np.zeros((3, 5), dtype=np.uint8)
        for x0, y0, x1, y1 in bounds:
            coverage[y0:y1, x0:x1] += 1
        np.testing.assert_array_equal(coverage, np.ones((3, 5), dtype=np.uint8))

    def test_candidate_order_rotates_video_segments(self) -> None:
        videos = [
            VideoInfo("/tmp/a.mp4", "a.mp4", "a", 10.0, 100, 10, 8),
            VideoInfo("/tmp/b.mp4", "b.mp4", "b", 10.0, 100, 10, 8),
            VideoInfo("/tmp/c.mp4", "c.mp4", "c", 10.0, 100, 10, 8),
        ]
        candidates = build_candidates(videos, 2)
        self.assertEqual([item.segment for item in candidates[:6]], ["a", "b", "c", "a", "b", "c"])
        self.assertEqual([item.quadrant for item in candidates[:6]], ["tl"] * 6)
        self.assertEqual(len(candidates), 3 * 2 * 4)


class MaskTests(unittest.TestCase):
    def test_rgba_mask_uses_color_and_alpha_not_alpha_alone(self) -> None:
        image = np.zeros((2, 3, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        image[1, 2, :3] = 255
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        data_url = "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")
        mask = decode_mask(data_url, 3, 2)
        np.testing.assert_array_equal(mask, np.array([[0, 0, 0], [0, 0, 1]], dtype=np.uint8))

    def test_mask_size_must_match_tile(self) -> None:
        image = np.zeros((2, 2), dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        data_url = "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")
        with self.assertRaisesRegex(ValueError, "掩膜尺寸"):
            decode_mask(data_url, 3, 2)


if __name__ == "__main__":
    unittest.main()
