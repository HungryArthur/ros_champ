from math import cos, radians, sin
from time import monotonic
from queue import Empty, Queue
from signal import SIGINT, default_int_handler, signal
from threading import Thread
import cv2
from turtlebro_py import TurtleBro

TARGET = 3  # Номер картины: 1, 2 или 3.
tb = TurtleBro()
signal(SIGINT, default_int_handler)  # Обычный Ctrl+C, затем остановка в finally.
tb.speed("fastest")
x0, y0, yaw0 = tb.pose
a = radians(yaw0 + 90)  # Оси карты относительно начального направления робота.
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def go(x, y):
    tb.goto(x0 + x * cos(a) - y * sin(a), y0 + x * sin(a) + y * cos(a))


def face(degrees):
    tb.turn((degrees + yaw0 + 90 - tb.pose[2] + 180) % 360 - 180)


def corner(x, y, start):
    for angle in range(start + 30, start + 91, 30):
        b = radians(angle)
        go(x + 0.675 * cos(b), y + 0.675 * sin(b))


def wait_until(check):
    deadline = monotonic() + 25
    while not check():
        tb.vel_pub.publish()  # Пустое сообщение /cmd_vel останавливает колёса.
        if monotonic() > deadline:
            raise TimeoutError("Не дождались сигнала или свободного пути")
        tb.wait(0.1)


def image():
    frames = Queue()
    Thread(target=lambda: frames.put(tb.photo), daemon=True).start()
    try:
        return frames.get(timeout=3)
    except Empty:
        raise TimeoutError("Камера не прислала кадр за 3 секунды")


def green():
    hsv = cv2.cvtColor(image()[:340], cv2.COLOR_BGR2HSV)
    return cv2.countNonZero(cv2.inRange(hsv, (40, 140, 150), (90, 255, 255))) > 20


try:
    tb.color("blue")
    go(0, -1.025)  # Выезд с парковки.
    go(0.75, -1.025)
    corner(0.75, -0.35, -90)
    face(60)
    wait_until(green)  # Стоим перед светофором до зелёного.
    for step in range(1, 7):
        face(90)
        wait_until(lambda: tb.lidar_distance() > 0.40)
        go(1.425, -0.35 + step * 0.15)  # Шаг 15 см; проверка лидара перед каждым.
    corner(0.75, 0.55, 0)
    found = False
    for x in (0.65, 0, -0.65):
        go(x, 1.225)
        if not found:
            face(90)
            tb.wait(0.2)
            _, ids, _ = cv2.aruco.detectMarkers(image(), dictionary)
            if ids is not None and TARGET in ids.flatten():
                tb.say(f"Перед нами картина номер {TARGET}. Спасибо за внимание!")
                found = True
    if not found:
        raise RuntimeError("Нужный маркер не найден")
    go(-0.75, 1.225)
    corner(-0.75, 0.55, 90)
    go(-1.425, -0.35)
    corner(-0.75, -0.35, 180)
    go(0, -1.025)
    go(0, 0)  # Возвращаемся в исходную парковку.
    face(-90)
    tb.color("green")
    tb.say("Экскурсия завершена")
finally:
    tb.vel_pub.publish()
