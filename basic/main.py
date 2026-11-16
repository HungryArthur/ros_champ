"""ROS 1: правая граница полосы + остановка перед препятствием."""
from time import monotonic, sleep
import cv2
import numpy as np
import rospy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import CompressedImage, LaserScan
from simple_pid import PID
from turtlebro_py import TurtleBro

CAMERA = "/front_camera/image_raw/compressed"
SCAN = "/scan"
SPEED, STOP_DISTANCE, MAX_AGE = 0.10, 0.40, 0.5
EDGE_X, FRONT_ANGLE = 0.85, 0.0  # Доля ширины кадра; направление лидара, рад.
data = dict(frame=None, camera_at=0.0, distance=0.0, scan_at=0.0)
steer = PID(1.8, 0, 0.05, setpoint=0, output_limits=(-0.9, 0.9))


def camera(message):
    frame = cv2.imdecode(np.frombuffer(message.data, np.uint8), cv2.IMREAD_COLOR)
    if frame is not None:
        data.update(frame=frame, camera_at=monotonic())


def laser(message):
    values = np.asarray(message.ranges, dtype=float)
    angles = message.angle_min + np.arange(len(values)) * message.angle_increment
    angles = (angles - FRONT_ANGLE + np.pi) % (2 * np.pi) - np.pi
    values = values[np.abs(angles) <= np.radians(12)]
    values = np.where(np.isposinf(values), message.range_max, values)
    values = values[np.isfinite(values) & (values > 0) & (values <= message.range_max)]
    data.update(distance=float(values.min()) if len(values) else 0.0, scan_at=monotonic())


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


def command(now):
    result = Twist()  # По умолчанию обе скорости нулевые.
    fresh = now - data["camera_at"] < MAX_AGE and now - data["scan_at"] < MAX_AGE
    if fresh and data["frame"] is not None and data["distance"] > STOP_DISTANCE:
        error = lane(data["frame"])
        if error is not None:
            result.angular.z = steer(error)
            result.linear.x = SPEED * (1 - 0.6 * abs(result.angular.z) / 0.9)
    if result.linear.x == 0:
        steer.reset()
    return result


def main():
    tb = TurtleBro()  # Сам создаёт ROS-узел и издателя /cmd_vel.

    def stop():
        tb.vel_pub.publish(Twist())
        sleep(0.1)

    rospy.on_shutdown(stop)
    rospy.Subscriber(CAMERA, CompressedImage, camera, queue_size=1, buff_size=2**20)
    rospy.Subscriber(SCAN, LaserScan, laser, queue_size=1)
    try:
        while not rospy.is_shutdown():
            movement = command(monotonic())
            if movement.linear.x == 0:
                rospy.logwarn_throttle(2, "Стоп: препятствие, потеря линии или нет свежих датчиков")
            tb.vel_pub.publish(movement)
            sleep(0.05)
    finally:
        if not rospy.is_shutdown():
            stop()


if __name__ == "__main__":
    main()
