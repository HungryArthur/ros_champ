"""Контроллер модели Webots. Все обращения к устройствам идут из его главного потока."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading

from controller import Supervisor

ROOT = Path(__file__).resolve().parent.parent


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class RobotController:
    RADIUS = 0.03
    TRACK = 0.23

    def __init__(self):
        self.robot = Supervisor()
        self.node = self.robot.getSelf()
        self.dt = int(self.robot.getBasicTimeStep())
        self.left = self.robot.getDevice("left wheel motor")
        self.right = self.robot.getDevice("right wheel motor")
        for motor in (self.left, self.right):
            motor.setPosition(float("inf"))
            motor.setVelocity(0)
        self.lidar = self.robot.getDevice("lidar")
        self.camera = self.robot.getDevice("camera")
        self.led = self.robot.getDevice("leds")
        self.speaker = self.robot.getDevice("speaker")
        self.lidar.enable(self.dt * 4)
        self.camera.enable(self.dt * 4)
        self.keyboard = self.robot.getKeyboard()
        self.keyboard.enable(self.dt)
        self.buttons = []
        self.cancel = threading.Event()
        self.commands = Queue()
        self.linear_speed = 0.09
        self.quit_after = None
        self.initial = []
        for node in [self.node] + [self.robot.getFromDef("BOX%d" % i) for i in range(1, 6)]:
            if node:
                self.initial.append((node, node.getField("translation").getSFVec3f(),
                                     node.getField("rotation").getSFRotation()))
        self.origin = self.initial[0][1][:]
        for _ in range(12):
            self.step()

    def step(self):
        if self.robot.step(self.dt) == -1:
            raise RuntimeError("Мир Webots закрыт")
        key = self.keyboard.getKey()
        while key != -1:
            if ord("1") <= key <= ord("4"):
                self.buttons.append(key - ord("1") + 22)
            key = self.keyboard.getKey()

    def motion_step(self):
        self.step()
        if self.cancel.is_set():
            raise RuntimeError("Движение остановлено")

    def raw_pose(self):
        position = self.node.getPosition()
        rotation = self.node.getOrientation()
        return position[0], position[1], math.atan2(rotation[3], rotation[0])

    def pose(self):
        x, y, yaw = self.raw_pose()
        return [x - self.origin[0], y - self.origin[1], math.degrees(yaw)]

    def velocity(self, linear, angular=0):
        self.left.setVelocity((linear - angular * self.TRACK / 2) / self.RADIUS)
        self.right.setVelocity((linear + angular * self.TRACK / 2) / self.RADIUS)

    def stop(self):
        self.velocity(0)

    def move(self, meters):
        if not math.isfinite(meters):
            raise ValueError("Расстояние должно быть конечным")
        x0, y0, heading = self.raw_pose()
        start = self.robot.getTime()
        best = 0
        progress_time = start
        try:
            while True:
                x, y, yaw = self.raw_pose()
                distance = math.hypot(x - x0, y - y0)
                remaining = abs(meters) - distance
                if remaining <= 0.002:
                    break
                if distance > best + 0.001:
                    best, progress_time = distance, self.robot.getTime()
                if self.robot.getTime() - progress_time > 3:
                    raise RuntimeError("Робот упёрся в препятствие или колёса не двигаются")
                if self.robot.getTime() - start > abs(meters) / self.linear_speed * 3 + 10:
                    raise RuntimeError("Не удалось закончить движение")
                speed = min(self.linear_speed, max(0.012, remaining * 1.6))
                angular = max(-0.4, min(0.4, wrap(heading - yaw) * 3))
                self.velocity(math.copysign(speed, meters), angular)
                self.motion_step()
        finally:
            self.stop()
            for _ in range(3):
                self.step()

    def turn(self, degrees):
        if not math.isfinite(degrees):
            raise ValueError("Угол должен быть конечным")
        goal = math.radians(degrees)
        previous = self.raw_pose()[2]
        travelled = 0
        start = self.robot.getTime()
        maximum = self.linear_speed * 10
        try:
            while abs(goal - travelled) > math.radians(0.3):
                yaw = self.raw_pose()[2]
                travelled += wrap(yaw - previous)
                previous = yaw
                error = goal - travelled
                if abs(error) <= math.radians(0.3):
                    break
                if self.robot.getTime() - start > abs(goal) / maximum * 3 + 12:
                    raise RuntimeError("Робот не смог закончить поворот")
                angular = math.copysign(min(maximum, max(0.08, abs(error) * 2.5)), error)
                self.velocity(0, angular)
                self.motion_step()
        finally:
            self.stop()
            for _ in range(3):
                self.step()

    def goto(self, x, y):
        px, py, yaw = self.raw_pose()
        dx, dy = x + self.origin[0] - px, y + self.origin[1] - py
        distance = math.hypot(dx, dy)
        if distance > 0.002:
            self.turn(math.degrees(wrap(math.atan2(dy, dx) - yaw)))
            self.move(distance)

    def ranges(self):
        values = self.lidar.getRangeImage()
        # Webots: слева направо, +pi ... -pi. API TurtleBro: 0 впереди, 90 слева.
        return [values[round(((math.pi - math.radians(angle)) % (2 * math.pi))
                             / (2 * math.pi) * (len(values) - 1))] for angle in range(360)]

    def say(self, text):
        print("TurtleBro: " + text, flush=True)
        self.robot.setLabel(0, text, 0.02, 0.92, 0.07, 0xFFFFFF, 0, "Arial")
        if os.name != "nt":
            self.speaker.speak(text, 1.0)
            while self.speaker.isSpeaking():
                self.motion_step()
            return
        encoded_text = base64.b64encode(text.encode("utf-8")).decode()
        script = (
            "$ProgressPreference='SilentlyContinue'; $ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName System.Speech; "
            "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded_text + "')); "
            "$v.Speak($t); $v.Dispose()"
        )
        command = base64.b64encode(script.encode("utf-16-le")).decode()
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            while process.poll() is None:
                self.motion_step()
            if process.returncode:
                raise RuntimeError("Синтезатор речи Windows не смог произнести фразу")
        finally:
            if process.poll() is None:
                process.terminate()

    def handle(self, method, arguments):
        if method == "stop":
            self.stop()
        elif method == "move":
            self.move(*arguments)
        elif method == "turn":
            self.turn(*arguments)
        elif method == "goto":
            self.goto(*arguments)
        elif method == "pose":
            return self.pose()
        elif method == "speed":
            self.linear_speed = float(arguments[0])
        elif method == "lidar":
            angle = arguments[0]
            if not math.isfinite(angle) or not 0 <= angle <= 360:
                raise ValueError("Угол лидара: от 0 до 360")
            values = self.ranges()
            return values if angle == 360 else values[round(angle) % 360]
        elif method == "photo":
            return {"width": self.camera.getWidth(), "height": self.camera.getHeight(),
                    "data": base64.b64encode(self.camera.getImage()).decode()}
        elif method == "save_photo":
            if self.camera.saveImage(arguments[0], 95) != 0:
                raise RuntimeError("Не удалось сохранить фотографию")
        elif method == "color":
            self.led.set(arguments[0])
        elif method == "say":
            self.say(*arguments)
        elif method == "play":
            self.speaker.playSound(self.speaker, self.speaker, arguments[0], 1, 1, 0, False)
            while self.speaker.isSoundPlaying(arguments[0]):
                self.motion_step()
        elif method == "time":
            return self.robot.getTime()
        elif method == "buttons":
            buttons, self.buttons = self.buttons, []
            return buttons
        elif method == "reset":
            self.stop()
            for node, position, rotation in self.initial:
                node.getField("translation").setSFVec3f(position)
                node.getField("rotation").setSFRotation(rotation)
                node.resetPhysics()
            for _ in range(12):
                self.step()
        elif method == "snapshot":
            viewpoint = self.robot.getFromDef("VIEWPOINT")
            position = viewpoint.getField("position")
            rotation = viewpoint.getField("orientation")
            old_position, old_rotation = position.getSFVec3f(), rotation.getSFRotation()
            try:
                if len(arguments) > 1 and arguments[1] == "robot":
                    x, y, z = self.node.getPosition()
                    position.setSFVec3f([x + 0.46, y - 0.6, z + 0.4])
                    yaw, pitch = math.atan2(0.6, -0.46), math.atan2(0.32, math.hypot(0.46, 0.6))
                    axis = [-math.sin(yaw/2)*math.sin(pitch/2), math.cos(yaw/2)*math.sin(pitch/2),
                            math.sin(yaw/2)*math.cos(pitch/2)]
                    norm = math.sqrt(sum(value*value for value in axis))
                    rotation.setSFRotation([value/norm for value in axis] +
                                          [2*math.acos(math.cos(yaw/2)*math.cos(pitch/2))])
                    for _ in range(3):
                        self.step()
                self.robot.exportImage(arguments[0], 95)
            finally:
                position.setSFVec3f(old_position)
                rotation.setSFRotation(old_rotation)
        elif method == "status":
            return {"pose": self.pose(), "led": self.led.get(), "devices":
                    [self.robot.getDeviceByIndex(i).getName() for i in range(self.robot.getNumberOfDevices())]}
        elif method == "quit":
            self.quit_after = self.robot.getTime() + 0.25
        else:
            raise ValueError("Неизвестная команда: " + method)


def run():
    controller = RobotController()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.send({"robot": "TurtleBro", "project": str(ROOT), "backend": "Webots"})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 100000:
                    raise ValueError("Неверный запрос")
                message = json.loads(self.rfile.read(length))
                if message["method"] in ("stop", "reset", "quit"):
                    controller.cancel.set()
                event, result = threading.Event(), {}
                controller.commands.put((message, event, result))
                if not event.wait(180):
                    raise RuntimeError("Включите ▶ в Webots: симуляция стоит на паузе")
                self.send(result)
            except Exception as error:
                self.send({"ok": False, "error": str(error)})

    server = ThreadingHTTPServer(("127.0.0.1", 18761), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("TurtleBro готов: запускайте python main.py", flush=True)
    try:
        while True:
            controller.step()
            if controller.quit_after is not None and controller.robot.getTime() >= controller.quit_after:
                controller.robot.simulationQuit(0)
            try:
                message, event, result = controller.commands.get_nowait()
            except Empty:
                continue
            try:
                if controller.cancel.is_set() and message["method"] not in ("stop", "reset", "quit"):
                    raise RuntimeError("Команда отменена остановкой")
                value = controller.handle(message["method"], message.get("arguments", []))
                result.update(ok=True, result=value)
            except Exception as error:
                controller.stop()
                result.update(ok=False, error=str(error))
            finally:
                if message["method"] in ("stop", "reset", "quit"):
                    controller.cancel.clear()
                event.set()
    except RuntimeError:
        pass
    finally:
        server.shutdown()
        server.server_close()
