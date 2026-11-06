"""Учебный API. Управляющий скрипт остаётся обычным Python-скриптом."""

import atexit
import base64
import math
from pathlib import Path
import time

from .launcher import ROOT, ensure_running, health, request


def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name + " должно быть положительным числом")
    return value


class TurtleBro:
    def __init__(self, debug=False):
        ensure_running()
        self.debug = bool(debug)
        self.callbacks = {}
        request("stop")
        atexit.register(self._stop_at_exit)

    def _command(self, method, *arguments):
        if self.debug:
            print(method, *arguments)
        try:
            return request(method, list(arguments))
        except KeyboardInterrupt:
            self.stop()
            raise
        except RuntimeError:
            try:
                request("stop", timeout=2)
            except Exception:
                pass
            raise

    def _stop_at_exit(self):
        try:
            if health():
                request("stop", timeout=2)
        except Exception:
            pass

    def forward(self, meters):
        self._command("move", positive(meters, "Расстояние"))

    def backward(self, meters):
        self._command("move", -positive(meters, "Расстояние"))

    def left(self, degrees):
        self._command("turn", positive(degrees, "Угол"))

    def right(self, degrees):
        self._command("turn", -positive(degrees, "Угол"))

    def turn(self, degrees):
        self._command("turn", float(degrees))

    def goto(self, x, y):
        self._command("goto", float(x), float(y))

    def speed(self, value):
        speeds = {"fastest": 0.17, "fast": 0.12, "normal": 0.09, "slow": 0.04, "slowest": 0.01}
        if value not in speeds:
            raise ValueError("Скорость: fastest, fast, normal, slow или slowest")
        self._command("speed", speeds[value])

    @property
    def pose(self):
        return tuple(self._command("pose"))

    def lidar_distance(self, angle=0):
        return self._command("lidar", float(angle))

    def color(self, color):
        colors = {"red": 0xFF2020, "green": 0x20FF40, "blue": 0x2060FF,
                  "yellow": 0xFFFF20, "white": 0xFFFFFF, "off": 0}
        if color not in colors:
            raise ValueError("Цвет: red, green, blue, yellow, white или off")
        self._command("color", colors[color])

    def say(self, text="Привет"):
        self._command("say", str(text))

    @property
    def photo(self):
        try:
            import numpy as np
        except ImportError as error:
            raise RuntimeError("Для tb.photo установите NumPy: python -m pip install numpy. tb.save_photo() работает без NumPy.") from error
        frame = self._command("photo")
        return np.frombuffer(base64.b64decode(frame["data"]), dtype=np.uint8).reshape(
            frame["height"], frame["width"], 4
        )[:, :, :3].copy()

    def save_photo(self, name="robophoto"):
        path = Path(name)
        if not path.suffix:
            path = ROOT / "output/photos" / (str(name) + ".jpg")
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._command("save_photo", str(path))
        print("Фото сохранено:", path)

    def play(self, filename):
        self._command("play", str(Path(filename).resolve()))

    def record(self, timeval=3, filename="turtlebro_sound"):
        raise NotImplementedError("Виртуальный микрофон пока не подключён. Запись звука проверяется на настоящем роботе.")

    def call(self, function, button=24):
        if not callable(function) or button not in (22, 23, 24, 25):
            raise ValueError("Нужны функция и номер кнопки от 22 до 25")
        self.callbacks[button] = function

    def wait(self, seconds=0):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Время должно быть неотрицательным")
        start = self._command("time")
        while seconds == 0 or self._command("time") - start < seconds:
            for button in self._command("buttons"):
                if button in self.callbacks:
                    self.callbacks[button]()
            time.sleep(0.03)

    def stop(self):
        return self._command("stop")

    def drive(self, linear, angular=0):
        """Плавное движение Webots: м/с и рад/с. Команду нужно обновлять чаще раза в секунду."""
        linear, angular = float(linear), float(angular)
        if not math.isfinite(linear) or not math.isfinite(angular) or abs(linear) > 0.2 or abs(angular) > 1.2:
            raise ValueError("drive: скорость до 0.2 м/с, поворот до 1.2 рад/с")
        self._command("drive", linear, angular)

    @property
    def simulation_time(self):
        return self._command("time")

    def reset(self):
        """Вернуть учебный мир Webots в начальное состояние."""
        self._command("reset")


class TurtleNav(TurtleBro):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("TurtleNav требует отдельного планировщика. Для упражнений используйте TurtleBro.")
