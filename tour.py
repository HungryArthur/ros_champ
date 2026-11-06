"""Зрение и этапы экскурсии. Решения принимаются по камере, лидару и pose."""

import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np


PAINTINGS = {
    1: "Перед нами портрет. Обратите внимание на спокойные цвета и выражение лица.",
    2: "Перед нами ночной пейзаж. На картине изображены звёзды и горы.",
    3: "Перед нами парусник. Белые паруса выделяются на фоне синего моря.",
}


def angle_difference(target, current):
    return (target - current + 180) % 360 - 180


class Vision:
    def __init__(self):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    def markers(self, image):
        _, ids, _ = self.detector.detectMarkers(image)
        return [] if ids is None else [int(value) for value in ids.flatten()]

    @staticmethod
    def traffic_light(image):
        # Во время проверки робот смотрит на светофор; пол исключён из области поиска.
        hsv = cv2.cvtColor(image[: int(image.shape[0] * 0.72)], cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 140, 150), (12, 255, 255)) | cv2.inRange(hsv, (170, 140, 150), (180, 255, 255))
        green = cv2.inRange(hsv, (40, 140, 150), (90, 255, 255))
        red_count, green_count = cv2.countNonZero(red), cv2.countNonZero(green)
        if red_count > 20 and red_count > green_count:
            return "red"
        if green_count > 20 and green_count > red_count:
            return "green"
        return None

    @staticmethod
    def road_turn(image, speed=0.17):
        """Ищем непрерывную белую границу и держим центр правой полосы."""
        height, width = image.shape[:2]
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 150), (180, 65, 255))
        mask[: round(height * 0.45)] = 0
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask[:] = 0
        for contour in contours:
            _, y, _, h = cv2.boundingRect(contour)
            if h > height * 0.10 and y < height * 0.66 and y + h > height * 0.61:
                cv2.drawContours(mask, [contour], -1, 255, -1)
        focal = width / (2 * math.tan(math.pi / 6))
        boundary = []
        for ratio in np.linspace(0.56, 0.70, 9):
            row = round(height * ratio)
            binary = mask[row] > 0
            edges = np.diff(np.r_[False, binary, False].astype(np.int8))
            runs = [(a, b - 1) for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]) if b - a >= 2]
            if not runs:
                continue
            left, right = max(runs, key=lambda run: run[1])
            right = (left + right) / 2
            q = (row - height / 2) / focal
            depth = 0.105 / (math.sin(0.12) + q * math.cos(0.12))
            forward = depth * math.cos(0.12) - 0.105 * math.sin(0.12) + 0.108
            right_distance = (right - width / 2) / focal * depth
            boundary.append((forward, -right_distance))
        if len(boundary) < 3:
            return None
        x, y = np.array(boundary).T
        curve = np.polyfit(x, y, 2)
        ahead = float(np.clip(0.52, x.min(), x.max()))
        slope = float(np.clip(2 * curve[0] * ahead + curve[1], -3, 3))
        # Отступаем от границы по её нормали, в том числе на повороте.
        normal = math.hypot(1, slope)
        target_x = ahead - 0.22 * slope / normal
        target_y = float(np.polyval(curve, ahead)) + 0.22 / normal
        angular = 2 * speed * target_y / (target_x * target_x + target_y * target_y)
        return float(np.clip(angular, -1.2, 1.2))


class MuseumGuide:
    EXIT_DISTANCE = 1.025

    def __init__(self, robot, target=3):
        if target not in PAINTINGS:
            raise ValueError("Номер картины должен быть 1, 2 или 3")
        self.tb, self.target = robot, target
        self.vision = Vision()
        self.light_done = False
        self.found = False
        self.scanned_stations = set()
        self.seen_ids = []
        self.light_colors = []
        self.obstacle_stops = 0
        self.distance = 0.0
        self.frames = 0
        self.trace = []
        self.output = Path(__file__).resolve().parent / "output"
        self.output.mkdir(exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.report_path = self.output / "tour-result.json"
        self.report_path.write_text(json.dumps({"run_id": self.run_id, "target": target,
                                               "completed": False, "status": "running"}), encoding="utf-8")
        self.started = self.tb.simulation_time
        self.deadline = self.started + 180

    def record_failure(self, message, status="failed"):
        self.report_path.write_text(json.dumps({"run_id": self.run_id, "target": self.target,
                                               "completed": False, "status": status,
                                               "error": message}, ensure_ascii=False, indent=2), encoding="utf-8")

    def face(self, heading):
        correction = angle_difference(heading, self.tb.pose[2])
        if abs(correction) > 0.3:
            self.tb.turn(correction)

    def leave_parking(self):
        print("Выезжаем с парковки.", flush=True)
        self.tb.speed("fastest")
        self.tb.color("blue")
        self.tb.forward(self.EXIT_DISTANCE)
        self.tb.left(90)

    def wait_for_green(self):
        print("Светофор: останавливаемся и ждём зелёный.", flush=True)
        self.tb.stop()
        x, y, heading = self.tb.pose
        # Координаты светофора относительно стартовой парковки.
        self.face(math.degrees(math.atan2(0.1 - y, 1.7 - x)))
        self.tb.wait(0.15)
        self.tb.save_photo("traffic-light")
        deadline = min(self.deadline, self.tb.simulation_time + 25)
        while self.tb.simulation_time < deadline:
            color = self.vision.traffic_light(self.tb.photo)
            if color and (not self.light_colors or self.light_colors[-1] != color):
                self.light_colors.append(color)
                print("Светофор:", color, flush=True)
            if color == "green":
                self.light_done = True
                self.face(heading)
                return
            self.tb.wait(0.1)
        raise RuntimeError("Зелёный сигнал не обнаружен за 25 секунд. См. output/photos/traffic-light.jpg")

    def wait_for_obstacle(self):
        print("Препятствие впереди: ждём открытия шлагбаума.", flush=True)
        self.tb.stop()
        self.obstacle_stops += 1
        deadline = min(self.deadline, self.tb.simulation_time + 25)
        while self.tb.simulation_time < deadline:
            ranges = self.tb.lidar_distance(360)
            if min(ranges[:11] + ranges[-10:]) > 0.55:
                print("Путь свободен.", flush=True)
                return
            self.tb.wait(0.1)
        raise RuntimeError("Препятствие не исчезло за 25 секунд; робот остановлен")

    def inspect_painting(self, station):
        self.tb.stop()
        self.scanned_stations.add(station)
        self.face(90)
        self.tb.wait(0.2)
        ids = self.vision.markers(self.tb.photo)
        print("Камера прочитала ArUco:", ids, flush=True)
        if not ids:
            self.tb.save_photo("unreadable-marker")
            raise RuntimeError("Не удалось прочитать маркер картины; см. output/photos/unreadable-marker.jpg")
        self.seen_ids.extend(ids)
        if self.target in ids:
            self.found = True
            self.tb.color("yellow")
            self.tb.save_photo("selected-painting")
            self.tb.say(PAINTINGS[self.target])
            self.tb.color("blue")
        self.face(180)

    def follow_road(self):
        deadline = self.deadline
        previous = self.tb.pose
        lost_frames = 0
        while self.tb.simulation_time < deadline:
            x, y, yaw = self.tb.pose
            self.trace.append([x, y, yaw])
            self.distance += math.hypot(x - previous[0], y - previous[1])
            previous = (x, y, yaw)
            if not self.light_done and x > 1.1 and y > -0.60:
                self.wait_for_green()
            if y > 1.05 and abs(yaw) > 140 and not self.found:
                for station, station_x in enumerate((0.65, 0, -0.65), 1):
                    if station not in self.scanned_stations and station_x - 0.20 < x < station_x + 0.08:
                        self.inspect_painting(station)
                        break
            # Возвращаемся к съезду только после полного круга и найденной картины.
            if self.distance > 6 and math.hypot(x, y + self.EXIT_DISTANCE) < 0.13 and abs(yaw) < 30:
                self.tb.stop()
                if not self.found:
                    raise RuntimeError("Круг завершён, но нужная картина не найдена")
                return
            ranges = self.tb.lidar_distance(360)
            if min(ranges[:11] + ranges[-10:]) < 0.36:
                self.wait_for_obstacle()
            frame = self.tb.photo
            self.frames += 1
            angular = self.vision.road_turn(frame)
            if angular is None:
                self.tb.stop()
                lost_frames += 1
                if lost_frames >= 8:
                    self.tb.save_photo("lost-road")
                    raise RuntimeError("Камера потеряла дорогу; см. output/photos/lost-road.jpg")
            else:
                lost_frames = 0
                self.tb.drive(0.17, angular)
            self.tb.wait(0.035)
        raise RuntimeError("Превышено время заезда: 180 секунд")

    def park(self):
        if not self.found or not self.light_done:
            raise RuntimeError("Экскурсия не завершена: проверьте картину и светофор")
        print("Возвращаемся на парковку.", flush=True)
        self.tb.stop()
        self.tb.goto(0, -self.EXIT_DISTANCE)
        self.face(90)
        self.tb.forward(self.EXIT_DISTANCE)
        self.face(-90)
        self.tb.color("green")
        self.tb.say("Экскурсия завершена. Мы вернулись на парковку.")
        finish_pose = self.tb.pose
        duration = self.tb.simulation_time - self.started
        if math.hypot(*finish_pose[:2]) > 0.05 or abs(angle_difference(-90, finish_pose[2])) > 3:
            raise RuntimeError("Не удалось точно вернуться в парковку")
        if duration > 180:
            raise RuntimeError("Парковка завершена, но превышен лимит 180 секунд")
        result = {"run_id": self.run_id, "target": self.target, "marker_ids_seen": self.seen_ids,
                  "light_colors_seen": self.light_colors, "obstacle_stops": self.obstacle_stops,
                  "road_distance_m": self.distance, "camera_frames": self.frames,
                  "finish_pose": finish_pose, "completed": True, "status": "completed",
                  "duration_sim_seconds": duration}
        self.report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output / "tour-trace.json").write_text(json.dumps(self.trace), encoding="utf-8")
        print("Готово. Отчёт: output/tour-result.json", flush=True)
        return result
