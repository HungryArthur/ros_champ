from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tour import MuseumGuide, Vision, angle_difference


class TourVisionTests(unittest.TestCase):
    def setUp(self):
        self.vision = Vision()

    def test_all_printed_gallery_markers_are_readable_after_perspective_change(self):
        root = Path(__file__).resolve().parent / "webots/worlds/textures"
        for marker_id in (1, 2, 3):
            with self.subTest(marker_id=marker_id):
                image = cv2.imread(str(root / ("marker-%d.png" % marker_id)))
                self.assertIsNotNone(image)
                matrix = cv2.getPerspectiveTransform(
                    np.float32([[0, 0], [383, 0], [383, 383], [0, 383]]),
                    np.float32([[130, 75], [370, 100], [400, 345], [110, 370]]),
                )
                view = cv2.warpPerspective(image, matrix, (640, 480), borderValue=(180, 180, 180))
                self.assertIn(marker_id, self.vision.markers(view))

    def test_road_controller_ignores_dark_pedestal_outside_white_boundary(self):
        image = np.full((480, 640, 3), 135, np.uint8)
        cv2.rectangle(image, (0, 216), (545, 479), (50, 50, 50), -1)
        cv2.line(image, (440, 216), (635, 400), (180, 180, 180), 7)
        baseline = self.vision.road_turn(image)
        cv2.rectangle(image, (590, 230), (639, 400), (10, 10, 10), -1)
        self.assertIsNotNone(baseline)
        self.assertAlmostEqual(self.vision.road_turn(image), baseline, places=6)

    def test_blank_image_is_not_treated_as_a_road(self):
        self.assertIsNone(self.vision.road_turn(np.full((480, 640, 3), 135, np.uint8)))

    def test_signal_color_and_green_parking_are_not_confused(self):
        image = np.full((480, 640, 3), 50, np.uint8)
        cv2.rectangle(image, (0, 380), (639, 479), (0, 255, 0), -1)
        self.assertIsNone(self.vision.traffic_light(image))
        cv2.circle(image, (320, 160), 20, (0, 0, 255), -1)
        self.assertEqual(self.vision.traffic_light(image), "red")
        cv2.circle(image, (320, 160), 20, (0, 255, 0), -1)
        self.assertEqual(self.vision.traffic_light(image), "green")

    def test_turn_across_angle_boundary_takes_short_path(self):
        self.assertEqual(angle_difference(-179, 179), 2)
        self.assertEqual(angle_difference(179, -179), -2)

    def test_new_or_failed_run_cannot_keep_previous_success_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "output").mkdir()
            result = root / "output/tour-result.json"
            result.write_text('{"completed": true}', encoding="utf-8")
            with patch("tour.__file__", str(root / "tour.py")):
                guide = MuseumGuide(Mock(simulation_time=0.0))
            self.assertFalse(json.loads(result.read_text(encoding="utf-8"))["completed"])
            guide.record_failure("lost road")
            report = json.loads(result.read_text(encoding="utf-8"))
            self.assertFalse(report["completed"])
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["error"], "lost road")


if __name__ == "__main__":
    unittest.main()
