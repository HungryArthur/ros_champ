import atexit
import unittest
from unittest.mock import patch

from simulation.client import TurtleBro
from simulation.launcher import ROOT, health


class WebotsApiTests(unittest.TestCase):
    def setUp(self):
        self.start = patch("simulation.client.ensure_running").start()
        self.request = patch("simulation.client.request").start()
        self.robot = TurtleBro()
        atexit.unregister(self.robot._stop_at_exit)
        self.request.reset_mock()
        self.addCleanup(patch.stopall)

    def test_distances_and_angles_use_the_same_units_and_signs_as_robot(self):
        self.robot.forward(0.2)
        self.request.assert_called_with("move", [0.2])
        self.robot.backward(0.1)
        self.request.assert_called_with("move", [-0.1])
        self.robot.left(450)
        self.request.assert_called_with("turn", [450.0])
        self.robot.right(90)
        self.request.assert_called_with("turn", [-90.0])

    def test_invalid_movement_does_not_reach_the_simulator(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.robot.forward(value)
        self.request.assert_not_called()

    def test_invalid_continuous_speed_is_rejected_before_reaching_the_simulator(self):
        for linear, angular in ((0.21, 0), (0, 1.21), (float("nan"), 0), (0, float("inf"))):
            with self.subTest(linear=linear, angular=angular), self.assertRaises(ValueError):
                self.robot.drive(linear, angular)
        self.request.assert_not_called()

    def test_keyboard_interrupt_sends_stop(self):
        self.request.side_effect = [KeyboardInterrupt, None]
        with self.assertRaises(KeyboardInterrupt):
            self.robot.forward(0.2)
        self.request.assert_called_with("stop", [])

    def test_camera_color_matches_opencv_bgr_format(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("NumPy is optional for the basic API")
        import base64
        self.request.return_value = {"width": 1, "height": 1,
                                     "data": base64.b64encode(bytes([10, 20, 30, 255])).decode()}
        image = self.robot.photo
        self.assertEqual(image.tolist(), [[[10, 20, 30]]])
        self.assertEqual(image.shape, (1, 1, 3))

    def test_connection_error_cancels_pending_movement(self):
        self.request.side_effect = [RuntimeError("paused"), None]
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.robot.forward(0.2)
        self.request.assert_called_with("stop", timeout=2)

    def test_callbacks_are_registered_without_executing_user_code(self):
        callback = unittest.mock.Mock()
        self.robot.call(callback, 24)
        callback.assert_not_called()
        self.assertEqual(self.robot.callbacks[24], callback)

    def test_health_refuses_a_controller_from_another_project(self):
        with patch("simulation.launcher.HTTP.open") as opening, \
                patch("simulation.launcher.json.load", return_value={"robot": "TurtleBro", "project": str(ROOT / "other")}):
            with self.assertRaisesRegex(RuntimeError, "другой папки"):
                health()


if __name__ == "__main__":
    unittest.main()
