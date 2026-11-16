"""ROS 1: выезд по ArUco, полоса, светофор, картина, возвращение в парковку."""
from math import atan2, degrees, hypot, pi
from time import monotonic, sleep
from threading import Thread
import cv2
import numpy as np
import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, CompressedImage, LaserScan
from simple_pid import PID
from turtlebro_py import TurtleBro

CAMERA, SCAN, ODOM = "/front_camera/image_raw/compressed", "/scan", "/odom"
CAMERA_INFO = "/front_camera/camera_info"
EXIT_ID, TARGET_ID, PARK_ID, BAY_ID = 10, 3, 0, 11
START_ON_ROAD = False  # True: начать сразу с полосы, без поиска выезда.
SPEED, STOP_DISTANCE, MAX_AGE = 0.10, 0.40, 0.5
EDGE_X, FRONT_ANGLE = 0.85, 0.0
MARKER_SIZE, EXIT_RANGE, PARK_RANGE, TARGET_RANGE = 0.15, 0.65, 0.40, 1.50
PARK_ENTRY_RANGE, PARK_SEARCH = 0.8, 0.25  # Порог въезда; + ищет слева, − справа.
DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
data = dict(frame=None, camera_at=0., scan_at=0., odom_at=0., distance=0., clearance=0., heading=0., matrix=None)
mission = dict(phase="EXIT", entered=0., found=False, heading=0., settle_until=0.)
steer = PID(1.8, 0, 0.05, setpoint=0, output_limits=(-0.9, 0.9))


def camera(message):
    frame = cv2.imdecode(np.frombuffer(message.data, np.uint8), cv2.IMREAD_COLOR)
    if frame is not None:
        data.update(frame=frame, camera_at=monotonic())


def laser(message):
    values = np.asarray(message.ranges, dtype=float)
    angles = message.angle_min + np.arange(len(values)) * message.angle_increment
    angles = (angles - FRONT_ANGLE + pi) % (2 * pi) - pi
    values = np.where(np.isposinf(values), message.range_max, values)
    valid = np.isfinite(values) & (values > 0) & (values <= message.range_max)
    front = values[valid & (np.abs(angles) <= np.radians(12))]
    near = values[valid]
    data.update(distance=float(front.min()) if len(front) else 0.,
                clearance=float(near.min()) if len(near) else 0., scan_at=monotonic())


def odometry(message):
    q = message.pose.pose.orientation
    yaw = atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    if np.isfinite(yaw):
        data.update(heading=degrees(yaw), odom_at=monotonic())


def calibration(message):
    k = np.asarray(message.K, dtype=float).reshape(3, 3)
    d = np.asarray(message.D, dtype=float)
    valid = np.isfinite(k).all() and k[0, 0] > 0 and k[1, 1] > 0 and message.width > 0 and message.height > 0
    valid = valid and np.isfinite(d).all() and len(d) in (0, 4, 5, 8, 12, 14)
    valid = valid and message.distortion_model in ("plumb_bob", "rational_polynomial")
    data.update(matrix=k if valid else None, distortion=d,
                size=(message.width, message.height))


def lane(frame):
    h, w = frame.shape[:2]
    mask = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), (0, 0, 150), (180, 65, 255))
    mask[:int(h * 0.55)] = 0
    mask[int(h * 0.90):] = 0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    edges = []
    for contour in contours:
        _, _, width, height = cv2.boundingRect(contour)
        points = contour[:, 0]
        samples = [points[np.abs(points[:, 1] - h * row) < 2, 0] for row in (0.62, 0.65, 0.68)]
        right = [float(xs.max()) for xs in samples if len(xs)]
        if height > h * 0.10 and width > height * 0.3 and len(right) >= 2:
            if cv2.contourArea(contour) < width * height * 0.45:
                edges.append(float(np.median(right)))
    return max(edges) / w - EDGE_X if edges else None


def markers(frame):
    corners, ids, _ = cv2.aruco.detectMarkers(frame, DICTIONARY)
    if ids is None:
        return {}
    k = data["matrix"].copy()
    k[0] *= frame.shape[1] / data["size"][0]
    k[1] *= frame.shape[0] / data["size"][1]
    _, positions, _ = cv2.aruco.estimatePoseSingleMarkers(corners, MARKER_SIZE, k, data["distortion"])
    return {int(number): (atan2(float(p[0]), float(p[2])), hypot(float(p[0]), float(p[2])))
            for number, p in zip(ids.flatten(), positions[:, 0]) if p[2] > 0}


def traffic_light(frame):
    hsv = cv2.cvtColor(frame[:int(frame.shape[0] * 0.55)], cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 140, 150), (12, 255, 255)) | cv2.inRange(hsv, (170, 140, 150), (180, 255, 255))
    green = cv2.inRange(hsv, (40, 140, 150), (90, 255, 255))
    scores = []
    for mask in (red, green):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        round_areas = [cv2.contourArea(c) for c in contours
                       if cv2.arcLength(c, True) > 0 and
                       4 * pi * cv2.contourArea(c) / cv2.arcLength(c, True)**2 > 0.80]
        scores.append(max(round_areas, default=0))
    return "red" if scores[0] > 30 else "green" if scores[1] > 30 else None


def enter(phase, now):
    mission.update(phase=phase, entered=now)
    steer.reset()
    rospy.loginfo("Этап: %s", phase)


def speak(tb, text, after, now):
    tb.vel_pub.publish(Twist())
    mission.update(speech_error=None, after_speech=after)
    def worker():
        try:
            tb.say(text)
        except Exception as error:
            mission["speech_error"] = str(error)
    mission["speech"] = Thread(target=worker, daemon=True)
    enter("SPEAK", now)
    mission["speech"].start()


def command(tb, now):
    result = Twist()
    phase = mission["phase"]
    if phase not in ("ROAD", "DONE") and now - mission["entered"] > 30:
        raise TimeoutError("Не завершён этап " + phase)
    fresh = all(now - data[key] < MAX_AGE for key in ("camera_at", "scan_at", "odom_at"))
    if not fresh or data["frame"] is None or data["distance"] <= 0 or data["matrix"] is None:
        rospy.logwarn_throttle(2, "Стоп: нужны свежие камера/лидар/одометрия и калибровка CameraInfo")
        return result
    if now < mission["settle_until"] or phase == "DONE":
        return result
    frame = data["frame"]
    visible, error = markers(frame), lane(frame)
    light = traffic_light(frame)

    if phase == "ROAD" and light == "red":
        enter("RED", now)  # Отсутствие красного не считается зелёным.
        return result
    if phase == "RED":
        if light == "green":
            enter("ROAD", now)
        return result

    if phase == "SPEAK":
        if not mission["speech"].is_alive():
            if mission["speech_error"] is not None:
                raise RuntimeError("Ошибка речи: " + mission["speech_error"])
            after = mission["after_speech"]
            mission["found"] = mission["found"] or after == "RETURN"
            if after == "DONE":
                tb.color("green")
            enter(after, now)
        return result
    if phase == "FIND_BAY":
        if BAY_ID in visible:
            enter("PARK", now)
        elif data["clearance"] >= 0.18:
            result.angular.z = PARK_SEARCH
        return result

    if phase in ("EXIT", "PARK"):
        target = visible.get(EXIT_ID if phase == "EXIT" else BAY_ID)
        if target is None:
            return result  # Потеряли ориентир — стоим, а не едем наугад.
        bearing, distance = target
        limit = EXIT_RANGE if phase == "EXIT" else PARK_RANGE
        if phase == "EXIT" and distance <= limit and error is not None:
            enter("ROAD", now)
            return result
        if phase == "PARK" and distance <= limit and abs(bearing) < 0.06:
            speak(tb, "Экскурсия завершена. Мы на парковке.", "DONE", now)
            return result
        result.angular.z = float(np.clip(-1.6 * bearing, -0.6, 0.6))
        if abs(bearing) < 0.20 and distance > limit:
            result.linear.x = 0.05

    elif phase == "LOOK":
        target = visible.get(TARGET_ID)
        if target is None:
            return result
        bearing, _ = target
        result.angular.z = float(np.clip(-1.6 * bearing, -0.6, 0.6))
        if abs(bearing) < 0.06 and now - mission["entered"] > 0.25:
            tb.color("yellow")
            speak(tb, "Перед нами картина номер " + str(TARGET_ID), "RETURN", now)
            return Twist()

    elif phase == "RETURN":
        angle = (mission["heading"] - data["heading"] + 180) % 360 - 180
        if abs(angle) < 2:
            tb.color("blue")
            enter("ROAD", now)
            mission["settle_until"] = now + 0.25
            return result
        result.angular.z = float(np.clip(angle * 0.04, -0.6, 0.6))

    elif phase == "ROAD":
        if mission["found"] and PARK_ID in visible and visible[PARK_ID][1] <= PARK_ENTRY_RANGE:
            enter("FIND_BAY", now)
            return result
        if not mission["found"] and TARGET_ID in visible and visible[TARGET_ID][1] < TARGET_RANGE:
            mission["heading"] = data["heading"]
            enter("LOOK", now)
            return result
        if error is not None:
            result.angular.z = steer(error)
            result.linear.x = SPEED * (1 - 0.6 * abs(result.angular.z) / 0.9)
        else:
            steer.reset()

    if result.linear.x > 0 and data["distance"] < STOP_DISTANCE:
        return Twist()  # В том числе перед закрытым шлагбаумом.
    if result.angular.z != 0 and data["clearance"] < 0.18:
        return Twist()
    return result


def main():
    tb = TurtleBro()

    def stop():
        tb.vel_pub.publish(Twist())
        sleep(0.1)

    rospy.on_shutdown(stop)
    rospy.Subscriber(CAMERA, CompressedImage, camera, queue_size=1, buff_size=2**20)
    rospy.Subscriber(CAMERA_INFO, CameraInfo, calibration, queue_size=1)
    rospy.Subscriber(SCAN, LaserScan, laser, queue_size=1)
    rospy.Subscriber(ODOM, Odometry, odometry, queue_size=1)
    mission.update(found=False, settle_until=0.)
    enter("ROAD" if START_ON_ROAD else "EXIT", monotonic())
    deadline = monotonic() + 180
    try:
        tb.color("blue")
        while not rospy.is_shutdown() and mission["phase"] != "DONE":
            if monotonic() > deadline:
                raise TimeoutError("Превышен лимит заезда 180 секунд")
            tb.vel_pub.publish(command(tb, monotonic()))
            sleep(0.05)
    finally:
        if not rospy.is_shutdown():
            stop()


if __name__ == "__main__":
    main()
