"""Автоматика полигона. Управляет только светофором и шлагбаумом."""

import math


class Course:
    def __init__(self, supervisor, robot_node):
        self.robot = supervisor
        self.node = robot_node
        self.red = supervisor.getFromDef("SIGNAL_RED")
        self.green = supervisor.getFromDef("SIGNAL_GREEN")
        self.arm = supervisor.getFromDef("GATE_ARM")
        self.reset()

    def reset(self):
        self.green_on = False
        self.gate_angle = 0.0
        self.light_wait_start = None
        self.gate_wait_start = None
        self.red_wait = 0.0
        self.barrier_wait = 0.0
        self.red_crossings = 0
        self.closed_gate_crossings = 0
        self.previous_y = self.node.getPosition()[1]
        self.paint_lights()
        if self.arm:
            self.arm.getField("rotation").setSFRotation([0, 1, 0, 0])

    def paint_lights(self):
        for node, lit, color in ((self.red, not self.green_on, [1, 0.015, 0.01]),
                                  (self.green, self.green_on, [0.01, 1, 0.03])):
            if node:
                node.getField("baseColor").setSFColor(color if lit else [0.025] * 3)
                node.getField("emissiveColor").setSFColor(color if lit else [0, 0, 0])

    def update(self):
        if not self.arm:
            return
        x, y, _ = self.node.getPosition()
        velocity = self.node.getVelocity()
        stopped = math.hypot(velocity[0], velocity[1]) < 0.015
        now = self.robot.getTime()
        if not self.green_on and math.hypot(x - 1.7, y) < 0.95 and stopped:
            if self.light_wait_start is None:
                self.light_wait_start = now
            self.red_wait = now - self.light_wait_start
            if self.red_wait >= 5:
                self.green_on = True
                self.paint_lights()
        if self.green_on and x > 1.0 and -0.32 < y < 0.35 and stopped:
            if self.gate_wait_start is None:
                self.gate_wait_start = now
            self.barrier_wait = now - self.gate_wait_start
        if self.gate_wait_start is not None and self.barrier_wait >= 3:
            self.gate_angle = min(1.5, self.gate_angle + self.robot.getBasicTimeStep() / 1000 * 1.1)
            self.arm.getField("rotation").setSFRotation([0, 1, 0, self.gate_angle])
        if x > 1.05:
            if self.previous_y < -0.32 <= y and not self.green_on:
                self.red_crossings += 1
            if self.previous_y < 0.35 <= y and self.gate_angle < 1.2:
                self.closed_gate_crossings += 1
        self.previous_y = y

    def status(self):
        return {"light": "green" if self.green_on else "red",
                "gate_angle": self.gate_angle, "red_wait_seconds": self.red_wait,
                "gate_wait_seconds": self.barrier_wait,
                "red_crossings": self.red_crossings,
                "closed_gate_crossings": self.closed_gate_crossings}
