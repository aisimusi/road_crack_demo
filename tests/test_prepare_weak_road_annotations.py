from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from prepare_weak_road_annotations import select_spaced_frames  # noqa: E402


class WeakRoadSamplingTests(unittest.TestCase):
    def test_selected_frames_stay_in_time_window_and_avoid_old_frames(self) -> None:
        selected = select_spaced_frames(1000, 0.05, 0.60, 5, {200, 400}, 30)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected, sorted(selected))
        self.assertTrue(all(50 <= frame <= 600 for frame in selected))
        self.assertTrue(all(abs(frame - old) >= 30 for frame in selected for old in (200, 400)))
        self.assertTrue(all(b - a >= 30 for a, b in zip(selected, selected[1:])))

    def test_impossible_spacing_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "无法找到"):
            select_spaced_frames(100, 0.0, 0.2, 3, set(), 15)


if __name__ == "__main__":
    unittest.main()
