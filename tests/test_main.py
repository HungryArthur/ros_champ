"""Проверки сценария без установленного ROS и без движения настоящего робота."""

import math
import queue  # Загружаем Queue до подмены часов в тестах ожидания.
from pathlib import Path
import runpy
import sys
from threading import Event
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

PROGRAM = Path(__file__).resolve().parents[1] / "main.py"


def marker(number):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    generate = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    square = generate(dictionary, number, 180)
    image = np.full((480, 640, 3), 255, np.uint8)
    image[100:280, 200:380] = cv2.cvtColor(square, cv2.COLOR_GRAY2BGR)
    return image


class Robot:
    """Только методы, которые есть в оригинальной библиотеке производителя."""

    def __init__(self, ids=(1, 2, 3), green=True, distance=1.0):
        self.initial = (2.0, -3.0, 37.0)
        self.position = self.initial
        self.ids = iter(ids)
        self.first_frame = True
        self.green = green
        self.distance = distance
        self.stops = 0
        self.spoken = []
        self.colors = []
        self.vel_pub = SimpleNamespace(publish=self.zero_velocity)

    def zero_velocity(self):
        self.stops += 1

    @property
    def pose(self):
        return self.position

    @property
    def photo(self):
        if self.first_frame or not self.green:
            self.first_frame = False
            image = np.zeros((480, 640, 3), np.uint8)
            cv2.circle(image, (300, 140), 25, (0, 255, 0) if self.green else (0, 0, 255), -1)
            return image
        return marker(next(self.ids))

    def goto(self, x, y):
        px, py, heading = self.position
        if math.hypot(x - px, y - py) > 0.0001:
            heading = math.degrees(math.atan2(y - py, x - px))
        self.position = (x, y, heading)

    def turn(self, angle):
        x, y, heading = self.position
        self.position = (x, y, (heading + angle + 180) % 360 - 180)

    def speed(self, name):
        assert name == "fastest"

    def color(self, name):
        self.colors.append(name)

    def say(self, text):
        self.spoken.append(text)

    def wait(self, seconds):
        pass

    def lidar_distance(self):
        return self.distance


class ScriptTests(unittest.TestCase):
    def execute(self, robot):
        with patch.dict(sys.modules, {"turtlebro_py": SimpleNamespace(TurtleBro=lambda: robot)}):
            runpy.run_path(str(PROGRAM), run_name="__main__")

    def test_complete_tour_returns_to_rotated_start_and_stops(self):
        robot = Robot()
        self.execute(robot)
        self.assertAlmostEqual(robot.pose[0], robot.initial[0])
        self.assertAlmostEqual(robot.pose[1], robot.initial[1])
        self.assertAlmostEqual(robot.pose[2], robot.initial[2])
        self.assertEqual(robot.colors[-1], "green")
        self.assertIn("номер 3", robot.spoken[0])
        self.assertGreater(robot.stops, 0)

    def test_missing_target_stops_without_claiming_success(self):
        robot = Robot(ids=(4, 5, 6))
        with self.assertRaisesRegex(RuntimeError, "маркер"):
            self.execute(robot)
        self.assertGreater(robot.stops, 0)
        self.assertNotIn("green", robot.colors)

    def test_red_light_times_out_and_stops(self):
        robot = Robot(green=False)
        with patch("time.monotonic", side_effect=(0, 26)), self.assertRaises(TimeoutError):
            self.execute(robot)
        self.assertGreaterEqual(robot.stops, 2)
        self.assertFalse(robot.spoken)

    def test_missing_lidar_reading_does_not_allow_passing(self):
        robot = Robot(distance=0)
        with patch("time.monotonic", side_effect=(0, 0, 26)), self.assertRaises(TimeoutError):
            self.execute(robot)
        self.assertGreaterEqual(robot.stops, 2)
        self.assertFalse(robot.spoken)

    def test_lost_camera_times_out_independently_and_stops(self):
        release = Event()

        class CameraLost(Robot):
            @property
            def photo(self):
                release.wait()
                return np.zeros((480, 640, 3), np.uint8)

        robot = CameraLost()
        started = monotonic()
        try:
            with self.assertRaisesRegex(TimeoutError, "Камера"):
                self.execute(robot)
        finally:
            release.set()
        self.assertLess(monotonic() - started, 6)
        self.assertGreater(robot.stops, 0)


if __name__ == "__main__":
    unittest.main()
