"""Реальные OpenCV/PID; ROS и привод заменены, физику робота эти тесты не проверяют."""
import importlib.util
import math
from pathlib import Path
import sys
from threading import Event
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class Twist:
    def __init__(self):
        self.linear = NS(x=0., y=0., z=0.)
        self.angular = NS(x=0., y=0., z=0.)


class Robot:
    def __init__(self):
        self.sent, self.spoken, self.colors = [], [], []
        self.vel_pub = NS(publish=lambda m: self.sent.append((m.linear.x, m.angular.z)))

    def say(self, text):
        self.spoken.append(text)

    def color(self, name):
        self.colors.append(name)


def load(folder):
    robot = Robot()
    ros = NS(is_shutdown=lambda: False, on_shutdown=lambda f: None,
             Subscriber=lambda *a, **k: None, loginfo=lambda *a: None,
             logwarn_throttle=lambda *a: None)
    modules = {"rospy": ros, "turtlebro_py": NS(TurtleBro=lambda: robot)}
    for package, messages in (("geometry_msgs", {"Twist": Twist}),
                              ("sensor_msgs", dict.fromkeys(("CameraInfo", "CompressedImage", "LaserScan"), NS)),
                              ("nav_msgs", {"Odometry": NS})):
        modules[package] = ModuleType(package)
        modules[package + ".msg"] = NS(**messages)
    spec = importlib.util.spec_from_file_location(folder, ROOT / folder / "main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    module.monotonic = lambda: 10.
    return module, robot, ros


def road(x=540, stop_line=False):
    image = np.zeros((480, 640, 3), np.uint8)
    cv2.line(image, (x - 51, 210), (x + 84, 479), (255, 255, 255), 6)
    if stop_line:
        cv2.line(image, (30, 390), (639, 390), (255, 255, 255), 6)
    return image


def scan(front=2., rear=2.):
    ranges = np.full(721, 2.)
    ranges[360], ranges[0] = front, rear
    return NS(ranges=ranges, angle_min=-math.pi, angle_increment=math.pi / 360,
              range_min=.1, range_max=8.)


def info(**changes):
    fields = dict(K=[600, 0, 320, 0, 600, 240, 0, 0, 1], D=[0.] * 5,
                  width=640, height=480, distortion_model="plumb_bob")
    fields.update(changes)
    return NS(**fields)


class SensorsTests(unittest.TestCase):
    def test_steering_sign_and_line_loss_in_both_scripts(self):
        for folder in ("basic", "full"):
            with self.subTest(folder=folder):
                m, tb, _ = load(folder)
                for x, sign in ((470, 1), (590, -1)):
                    m.steer.reset()  # Независимые кадры; не ждём sample_time настоящего PID.
                    m.data.update(frame=road(x), camera_at=10., scan_at=10., distance=2.)
                    if folder == "full":
                        m.calibration(info())
                        m.data.update(odom_at=10., clearance=2.)
                        m.enter("ROAD", 10.)
                    movement = m.command(10.) if folder == "basic" else m.command(tb, 10.)
                    self.assertGreater(movement.linear.x, 0)
                    self.assertGreater(movement.angular.z * sign, 0)
                m.data["frame"][:] = 0
                movement = m.command(10.) if folder == "basic" else m.command(tb, 10.)
                self.assertEqual((movement.linear.x, movement.angular.z), (0, 0))

    def test_boundary_stays_stable_when_it_meets_stop_line(self):
        for folder in ("basic", "full"):
            m, _, _ = load(folder)
            self.assertAlmostEqual(m.lane(road()), m.lane(road(stop_line=True)), delta=.015)

    def test_white_post_and_poster_are_not_road_edges(self):
        m, _, _ = load("basic")
        for a, b in (((500, 270), (505, 430)), ((430, 270), (610, 430))):
            frame = np.zeros((480, 640, 3), np.uint8)
            cv2.rectangle(frame, a, b, (255, 255, 255), -1)
            self.assertIsNone(m.lane(frame))

    def test_lidar_uses_angle_min_and_configurable_front(self):
        for folder in ("basic", "full"):
            m, _, _ = load(folder)
            m.laser(scan(front=.25, rear=.12))
            self.assertAlmostEqual(m.data["distance"], .25)
            m.FRONT_ANGLE = math.pi
            m.laser(scan(front=.25, rear=.12))
            self.assertAlmostEqual(m.data["distance"], .12)
            if folder == "full":
                self.assertAlmostEqual(m.data["clearance"], .12)

    def test_infinite_clear_lidar_and_invalid_sector(self):
        for folder in ("basic", "full"):
            m, _, _ = load(folder)
            message = scan()
            message.ranges[:] = np.inf
            m.laser(message)
            self.assertEqual(m.data["distance"], 8.)
            for invalid in (0., np.nan, -np.inf):
                message.ranges[:] = invalid
                m.laser(message)
                self.assertEqual(m.data["distance"], 0.)

    def test_real_compressed_camera_decode_and_rejected_image(self):
        m, _, _ = load("basic")
        ok, encoded = cv2.imencode(".jpg", road())
        self.assertTrue(ok)
        m.camera(NS(data=encoded.tobytes()))
        self.assertEqual(m.data["camera_at"], 10.)
        self.assertIsNotNone(m.lane(m.data["frame"]))
        m.monotonic = lambda: 11.
        m.camera(NS(data=b"not an image"))
        self.assertEqual(m.data["camera_at"], 10.)

    def test_basic_stops_and_resumes_on_obstacle_and_stale_sensor(self):
        m, _, _ = load("basic")
        m.data.update(frame=road(), camera_at=10., scan_at=10., distance=2.)
        self.assertGreater(m.command(10.).linear.x, 0)
        for key, value in (("distance", .2), ("camera_at", 9.), ("scan_at", 9.)):
            with patch.dict(m.data, {key: value}):
                move = m.command(10.)
                self.assertEqual((move.linear.x, move.angular.z), (0, 0))
            self.assertGreater(m.command(10.).linear.x, 0)


class FullTests(unittest.TestCase):
    def setUp(self):
        self.m, self.tb, self.ros = load("full")
        self.m.calibration(info())
        self.m.data.update(frame=road(), distance=2., clearance=2.)
        self.m.enter("ROAD", 10.)

    def step(self, now=10., visible=None, light=None):
        self.m.data.update(camera_at=now, scan_at=now, odom_at=now)
        with patch.object(self.m, "markers", return_value=visible or {}), \
                patch.object(self.m, "traffic_light", return_value=light):
            return self.m.command(self.tb, now)

    def finish_speech(self, now):
        self.m.mission["speech"].join(timeout=1)
        self.assertFalse(self.m.mission["speech"].is_alive())
        return self.step(now)

    def test_entire_mission_uses_observations_and_relative_heading(self):
        m = self.m
        m.enter("EXIT", 10.)
        self.assertEqual(self.step(visible={10: (0., .64)}).linear.x, 0.)
        self.assertEqual(m.mission["phase"], "ROAD")
        self.step(10.1, visible={3: (.2, .8)})
        self.assertEqual(m.mission["phase"], "LOOK")
        self.assertLess(self.step(10.2, visible={3: (.2, .8)}).angular.z, 0.)
        self.step(10.4, visible={3: (0., .8)})
        self.assertEqual(m.mission["phase"], "SPEAK")
        self.finish_speech(10.5)
        self.assertTrue(m.mission["found"])
        self.assertEqual(m.mission["phase"], "RETURN")
        m.data["heading"] = -20.
        self.assertGreater(self.step(10.6).angular.z, 0.)
        m.data["heading"] = 0.
        self.step(10.7)
        self.assertEqual(m.mission["phase"], "ROAD")
        self.assertEqual(self.step(10.8).linear.x, 0.)  # Пауза после разворота.
        self.step(11., visible={0: (0., .7)})
        self.assertEqual(m.mission["phase"], "FIND_BAY")
        self.assertGreater(self.step(11.1).angular.z, 0.)
        self.step(11.2, visible={11: (.1, .8)})
        self.assertEqual(m.mission["phase"], "PARK")
        self.assertGreater(self.step(11.3, visible={11: (0., .8)}).linear.x, 0.)
        self.step(11.4, visible={11: (0., .39)})
        self.finish_speech(11.5)
        self.assertEqual(m.mission["phase"], "DONE")
        self.assertEqual(self.tb.colors[-1], "green")
        self.assertIn("номер 3", self.tb.spoken[0])
        self.assertIn("парковке", self.tb.spoken[1])
        self.assertTrue(all(pair == (0., 0.) for pair in self.tb.sent))  # Стоп перед речью.

    def test_red_latches_until_positive_green(self):
        self.step(light="red")
        self.assertEqual(self.m.mission["phase"], "RED")
        self.assertEqual(self.step(11.).linear.x, 0.)
        self.assertEqual(self.m.mission["phase"], "RED")
        self.step(12., light="green")
        self.assertEqual(self.m.mission["phase"], "ROAD")
        self.assertGreater(self.step(12.1).linear.x, 0.)

    def test_no_parking_until_painting_was_seen(self):
        self.step(visible={0: (0., .5)})
        self.assertEqual(self.m.mission["phase"], "ROAD")

    def test_exit_and_parking_cross_arrival_threshold_in_finite_time(self):
        for phase, number, threshold in (("EXIT", 10, self.m.EXIT_RANGE), ("PARK", 11, self.m.PARK_RANGE)):
            self.m.enter(phase, 10.)
            distance, now = threshold + .10, 10.
            while self.m.mission["phase"] == phase and now < 15.:
                movement = self.step(now, visible={number: (0., distance)})
                distance -= movement.linear.x * .05
                now += .05
            self.assertNotEqual(self.m.mission["phase"], phase)
            if self.m.mission["phase"] == "SPEAK":
                self.finish_speech(now)

    def test_missing_marker_stops_then_times_out_without_success(self):
        self.m.enter("PARK", 10.)
        movement = self.step(11.)
        self.assertEqual((movement.linear.x, movement.angular.z), (0, 0))
        with self.assertRaises(TimeoutError):
            self.step(41.)
        self.assertNotIn("green", self.tb.colors)

    def test_obstacle_and_side_clearance_stop_motion(self):
        self.m.data["distance"] = .2
        self.assertEqual(self.step().linear.x, 0.)
        self.m.data.update(distance=2., clearance=.1)
        self.m.enter("RETURN", 10.)
        self.m.data["heading"] = 30.
        self.assertEqual(self.step().angular.z, 0.)
        self.m.enter("FIND_BAY", 10.)
        self.assertEqual(self.step().angular.z, 0.)

    def test_stale_odometry_and_absent_calibration_stop_rotation(self):
        self.m.enter("RETURN", 10.)
        self.m.data.update(camera_at=10., scan_at=10., odom_at=9., heading=30.)
        self.assertEqual(self.m.command(self.tb, 10.).angular.z, 0.)
        self.m.data.update(odom_at=10., matrix=None)
        self.assertEqual(self.m.command(self.tb, 10.).angular.z, 0.)

    def test_blocked_speech_is_bounded_and_never_claims_success(self):
        release = Event()
        self.tb.say = lambda text: release.wait()
        try:
            self.m.speak(self.tb, "test", "DONE", 10.)
            self.assertEqual(self.step(11.).linear.x, 0.)
            with self.assertRaises(TimeoutError):
                self.step(41.)
            self.assertNotIn("green", self.tb.colors)
        finally:
            release.set()
            self.m.mission["speech"].join(timeout=1)

    def test_speech_exception_is_reported(self):
        def fail(text):
            raise RuntimeError("speech unavailable")
        self.tb.say = fail
        self.m.speak(self.tb, "test", "DONE", 10.)
        with self.assertRaisesRegex(RuntimeError, "speech unavailable"):
            self.finish_speech(11.)

    def test_real_aruco_pose_with_camera_calibration(self):
        generate = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
        square = generate(self.m.DICTIONARY, 3, 180)
        frame = np.full((480, 640, 3), 255, np.uint8)
        frame[150:330, 330:510] = cv2.cvtColor(square, cv2.COLOR_GRAY2BGR)
        bearing, distance = self.m.markers(frame)[3]
        self.assertGreater(bearing, 0.)  # Маркер справа; поворот вправо.
        self.assertAlmostEqual(distance, math.hypot(.15 * 99.5 / 179, 600 * .15 / 179), delta=.01)
        smaller = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_NEAREST)
        self.assertAlmostEqual(self.m.markers(smaller)[3][1], distance, delta=.02)

    def test_invalid_camera_calibration_is_rejected(self):
        for changes in ({"K": [0.] * 9}, {"D": [float("nan")] * 5},
                        {"distortion_model": "equidistant"}, {"width": 0}):
            self.m.calibration(info(**changes))
            self.assertIsNone(self.m.data["matrix"])

    def test_odometry_wraps_heading_correctly(self):
        angle = math.radians(170)
        q = NS(x=0., y=0., z=math.sin(angle / 2), w=math.cos(angle / 2))
        self.m.odometry(NS(pose=NS(pose=NS(orientation=q))))
        self.assertAlmostEqual(self.m.data["heading"], 170.)
        self.m.mission.update(phase="RETURN", heading=-170.)
        self.assertGreater(self.step().angular.z, 0.)

    def test_real_traffic_colors_and_red_square_rejection(self):
        for color, expected in (((0, 0, 255), "red"), ((0, 255, 0), "green")):
            frame = np.zeros((480, 640, 3), np.uint8)
            cv2.circle(frame, (320, 120), 14, color, -1)
            self.assertEqual(self.m.traffic_light(frame), expected)
        frame[:] = 0
        cv2.rectangle(frame, (300, 100), (340, 140), (0, 0, 255), -1)
        self.assertIsNone(self.m.traffic_light(frame))


class CleanupTests(unittest.TestCase):
    def test_keyboard_interrupt_publishes_final_zero_velocity(self):
        for folder in ("basic", "full"):
            m, tb, _ = load(folder)
            m.data.update(frame=road(), distance=2., camera_at=10., scan_at=10.)
            if folder == "full":
                m.calibration(info())
                m.data.update(odom_at=10., clearance=2.)
                m.START_ON_ROAD = True
            with patch.object(m, "sleep", side_effect=[KeyboardInterrupt, None]):
                with self.assertRaises(KeyboardInterrupt):
                    m.main()
            self.assertGreater(tb.sent[0][0], 0.)
            self.assertEqual(tb.sent[-1], (0., 0.))


if __name__ == "__main__":
    unittest.main()
