"""Пересобрать локальные текстуры и мир: python tools/build_course.py."""

from pathlib import Path
import math

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "webots/worlds"
TEXTURES = WORLD / "textures"
TEXTURES.mkdir(parents=True, exist_ok=True)
SCALE, WIDTH, HEIGHT = 600, 4.4, 3.8


def pixel(x, y):
    return round((x + WIDTH / 2) * SCALE), round((HEIGHT / 2 - y) * SCALE)


def line(image, a, b, color, width):
    cv2.line(image, pixel(*a), pixel(*b), color, round(width * SCALE), cv2.LINE_AA)


def centerline():
    points = []
    corners = [(0.75, -0.45, -90), (0.75, 0.45, 0),
               (-0.75, 0.45, 90), (-0.75, -0.45, 180)]
    for x, y, start in corners:
        for angle in np.linspace(start, start + 90, 100):
            a = math.radians(angle)
            points.append((x + 0.5 * math.cos(a), y + 0.5 * math.sin(a)))
    points.append(points[0])
    return points


def floor_texture():
    image = np.full((round(HEIGHT * SCALE), round(WIDTH * SCALE), 3), (187, 190, 193), np.uint8)
    points = centerline()
    path = np.array([pixel(*p) for p in points], np.int32)
    cv2.polylines(image, [path], True, (245, 245, 240), round(0.78 * SCALE), cv2.LINE_AA)
    cv2.polylines(image, [path], True, (49, 48, 46), round(0.73 * SCALE), cv2.LINE_AA)
    distance = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        count = max(1, math.ceil(length / 0.008))
        for index in range(count):
            t, end = index / count, (index + 1) / count
            if (distance + length * t) % 0.27 < 0.15:
                line(image, tuple(a[i] + (b[i] - a[i]) * t for i in range(2)),
                     tuple(a[i] + (b[i] - a[i]) * end for i in range(2)), (245, 245, 240), 0.018)
        distance += length
    # Соединение парковки с внутренней стороной дороги.
    cv2.rectangle(image, pixel(-0.23, -0.39), pixel(0.23, -0.99), (49, 48, 46), -1)
    cv2.rectangle(image, pixel(-0.36, 0.28), pixel(0.36, -0.48), (58, 160, 83), round(0.025 * SCALE))
    cv2.circle(image, pixel(0, -0.1), round(0.14 * SCALE), (190, 112, 37), -1, cv2.LINE_AA)
    cv2.putText(image, "P", pixel(-0.065, -0.18), cv2.FONT_HERSHEY_SIMPLEX, 2.7, (250, 250, 250), 8, cv2.LINE_AA)
    # Стоп-линия перед светофором.
    line(image, (1.29, -0.32), (1.60, -0.32), (235, 235, 245), 0.035)
    for x, y, direction in [(0.4, -1.12, 1), (-0.35, 1.12, -1)]:
        cv2.arrowedLine(image, pixel(x - direction * 0.12, y), pixel(x + direction * 0.12, y),
                       (245, 245, 240), 6, cv2.LINE_AA, tipLength=0.35)
    cv2.putText(image, "TURTLEBRO  /  MUSEUM", pixel(-0.70, 0.62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 105, 110), 2, cv2.LINE_AA)
    cv2.imwrite(str(TEXTURES / "museum-floor.png"), image)


def paintings():
    # Собственная процедурная графика: портрет, ночной пейзаж и парусник.
    portrait = np.full((480, 400, 3), (61, 85, 87), np.uint8)
    cv2.ellipse(portrait, (200, 470), (145, 205), 0, 0, 360, (33, 44, 39), -1)
    cv2.ellipse(portrait, (205, 190), (95, 140), 0, 0, 360, (30, 41, 38), -1)
    cv2.ellipse(portrait, (200, 203), (64, 91), 0, 0, 360, (107, 161, 188), -1)
    cv2.ellipse(portrait, (203, 126), (77, 45), -8, 0, 180, (35, 43, 42), -1)
    for x in (176, 225):
        cv2.ellipse(portrait, (x, 194), (10, 4), 0, 0, 360, (49, 63, 64), -1)
    cv2.ellipse(portrait, (201, 240), (18, 5), 0, 0, 180, (68, 92, 127), 2)
    cv2.ellipse(portrait, (200, 384), (66, 20), -10, 0, 360, (107, 161, 188), -1)
    night = np.full((480, 400, 3), (101, 49, 25), np.uint8)
    rng = np.random.default_rng(7)
    for x, y, radius in rng.integers([10, 10, 2], [390, 320, 7], (65, 3)):
        cv2.circle(night, (int(x), int(y)), int(radius), (149, 221, 249), -1, cv2.LINE_AA)
    cv2.circle(night, (295, 95), 40, (169, 227, 249), -1, cv2.LINE_AA)
    cv2.fillPoly(night, [np.array([[0, 390], [90, 210], [200, 370], [295, 270], [400, 400], [400, 480], [0, 480]])], (62, 73, 37))
    sea = np.full((480, 400, 3), (222, 191, 133), np.uint8)
    cv2.rectangle(sea, (0, 260), (400, 480), (139, 95, 36), -1)
    cv2.circle(sea, (80, 85), 35, (151, 219, 252), -1, cv2.LINE_AA)
    cv2.fillPoly(sea, [np.array([[205, 100], [205, 300], [105, 285]])], (234, 242, 244))
    cv2.fillPoly(sea, [np.array([[218, 170], [218, 300], [290, 290]])], (205, 221, 227))
    cv2.fillPoly(sea, [np.array([[102, 310], [292, 310], [255, 345], [145, 345]])], (38, 47, 68))
    for index, image in enumerate((portrait, night, sea), 1):
        cv2.imwrite(str(TEXTURES / f"painting-{index}.png"), image)
        marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), index, 256)
        cv2.imwrite(str(TEXTURES / f"marker-{index}.png"), cv2.copyMakeBorder(marker, 64, 64, 64, 64, cv2.BORDER_CONSTANT, value=255))
    sign = np.full((256, 256, 3), 245, np.uint8)
    cv2.circle(sign, (128, 128), 112, (30, 35, 210), 20, cv2.LINE_AA)
    cv2.putText(sign, "20", (58, 158), cv2.FONT_HERSHEY_SIMPLEX, 2.1, (30, 30, 30), 6, cv2.LINE_AA)
    cv2.imwrite(str(TEXTURES / "speed-20.png"), sign)


def shape(geometry, color="0.8 0.8 0.8", material=None):
    material = material or f"PBRAppearance {{ baseColor {color} metalness 0 roughness 0.8 }}"
    return f"Shape {{ appearance {material} geometry {geometry} }}"


def box(position, size, color, name="", collision=False):
    geometry = f"Box {{ size {size} }}"
    return (f'Solid {{ translation {position} name "{name}" children [ {shape(geometry, color)} ] '
            + (f"boundingObject {geometry} " if collision else "") + "}")


def panel(position, width, height, image, name):
    w, h = width / 2, height / 2
    geometry = (f"IndexedFaceSet {{ coord Coordinate {{ point [ {-w} 0 {-h}, {w} 0 {-h}, {w} 0 {h}, {-w} 0 {h} ] }} "
                "texCoord TextureCoordinate { point [ 0 0, 1 0, 1 1, 0 1 ] } coordIndex [ 0 1 2 3 -1 ] solid FALSE }")
    material = f'PBRAppearance {{ baseColorMap ImageTexture {{ url [ "textures/{image}" ] filtering 0 }} metalness 0 roughness 1 }}'
    return f'Solid {{ translation {position} name "{name}" children [ {shape(geometry, material=material)} ] }}'


def world_file():
    yaw = math.atan2(5.2, -4.2)
    pitch = math.atan2(5.45, math.hypot(4.2, 5.2))
    axis = [-math.sin(yaw / 2) * math.sin(pitch / 2),
            math.cos(yaw / 2) * math.sin(pitch / 2),
            math.sin(yaw / 2) * math.cos(pitch / 2)]
    norm = math.sqrt(sum(value * value for value in axis))
    view_rotation = " ".join(str(value / norm) for value in axis) + " " + str(2 * math.acos(math.cos(yaw / 2) * math.cos(pitch / 2)))
    parts = ['#VRML_SIM R2025a utf8', '# Museum road course inspired by the supplied competition photograph.',
             'EXTERNPROTO "../protos/TurtleBro.proto"',
             '''WorldInfo {
  title "TurtleBro | Museum tour"
  basicTimeStep 16
  coordinateSystem "ENU"
  randomSeed 7
  contactProperties [
    ContactProperties { material1 "rubber" material2 "floor" coulombFriction [ 1.1 ] bounce 0 }
    ContactProperties { material1 "caster" material2 "floor" coulombFriction [ 0.001 ] bounce 0 }
  ]
}
DEF VIEWPOINT Viewpoint {
  orientation VIEW_ROTATION
  position 4.2 -5.2 5.5
}
Background { skyColor [ 0.21 0.24 0.29 ] }
DirectionalLight { direction -0.3 0.4 -1 intensity 1 ambientIntensity 0.65 castShadows FALSE }
DirectionalLight { direction 0.4 -0.5 -1 intensity 0.35 ambientIntensity 0.1 castShadows FALSE }
Solid {
  translation 0 0 -0.02
  name "printed competition floor"
  contactMaterial "floor"
  children [ Shape {
    appearance PBRAppearance { baseColorMap ImageTexture { url [ "textures/museum-floor.png" ] } metalness 0 roughness 1 }
    geometry IndexedFaceSet {
      coord Coordinate { point [ -2.2 -1.9 0.02, 2.2 -1.9 0.02, 2.2 1.9 0.02, -2.2 1.9 0.02 ] }
      texCoord TextureCoordinate { point [ 0 0, 1 0, 1 1, 0 1 ] }
      coordIndex [ 0 1 2 3 -1 ]
    }
  } ]
  boundingObject Box { size 4.4 3.8 0.04 }
}''']
    for y in (-1.88, 1.88):
        parts.append(box(f"0 {y} 0.19", "4.4 0.035 0.38", "0.82 0.83 0.81", f"wall y {y}", True))
        parts.append(box(f"0 {y} 0.39", "4.4 0.05 0.025", "0.42 0.46 0.49", f"rail y {y}"))
    for x in (-2.18, 2.18):
        parts.append(box(f"{x} 0 0.19", "0.035 3.8 0.38", "0.82 0.83 0.81", f"wall x {x}", True))
        parts.append(box(f"{x} 0 0.39", "0.05 3.8 0.025", "0.42 0.46 0.49", f"rail x {x}"))
    for index, x in enumerate((0.65, 0, -0.65), 1):
        parts.append(box(f"{x} 1.76 0.33", "0.46 0.035 0.62", "0.10 0.08 0.06", f"gallery frame {index}", True))
        parts.append(panel(f"{x} 1.739 0.43", 0.39, 0.33, f"painting-{index}.png", f"painting {index}"))
        parts.append(panel(f"{x} 1.738 0.13", 0.22, 0.22, f"marker-{index}.png", f"ArUco {index}"))
    # Знак ограничения скорости, как на фотографии.
    parts.append(box("1.82 -0.8 0.11", "0.018 0.018 0.22", "0.12 0.13 0.14", "sign pole"))
    parts.append(panel("1.82 -0.81 0.25", 0.14, 0.14, "speed-20.png", "speed limit 20"))
    parts.append(box("1.70 0 0.20", "0.15 0.07 0.30", "0.025 0.03 0.04", "traffic light", True))
    for name, z, color in (("RED", 0.29, "1 0.015 0.01"), ("AMBER", 0.21, "0.025 0.025 0.025"), ("GREEN", 0.13, "0.025 0.025 0.025")):
        material = f"DEF SIGNAL_{name} PBRAppearance {{ baseColor {color} emissiveColor {color if name == 'RED' else '0 0 0'} metalness 0 roughness 0.5 }}"
        parts.append(f"Pose {{ translation 1.70 -0.041 {z} rotation 1 0 0 1.57079632679 children [ {shape('Cylinder { radius 0.027 height 0.012 }', material=material)} ] }}")
    parts.append(box("1.85 0.35 0.125", "0.13 0.13 0.25", "0.08 0.11 0.15", "barrier pedestal", True))
    stripes = []
    for index in range(7):
        stripes.append(box(f"{-0.07 - index * 0.125} 0 0", "0.055 0.040 0.044", "0.82 0.03 0.025", f"barrier stripe {index}"))
    parts.append('DEF GATE_ARM Pose { translation 1.85 0.35 0.135 rotation 0 1 0 0 children [ '
                 + box("-0.45 0 0", "0.9 0.035 0.04", "0.95 0.95 0.93", "barrier arm", True)
                 + "\n" + "\n".join(stripes) + " ] }")
    parts.append('DEF TURTLEBRO TurtleBro {}')
    (WORLD / "turtlebro.wbt").write_text("\n".join(parts).replace("VIEW_ROTATION", view_rotation) + "\n", encoding="utf-8")


if __name__ == "__main__":
    floor_texture()
    paintings()
    world_file()
    print("Created webots/worlds/turtlebro.wbt and local textures")
