"""Полные заезды в Webots: python tools/verify_course.py. Занимает несколько минут."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
from simulation.launcher import ensure_running, request
from tour import Vision


def main():
    ensure_running()
    reports = []
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    for target in (1, 2, 3):
        print("VERIFY TARGET", target, flush=True)
        completed = subprocess.run([sys.executable, "main.py", "--target", str(target)],
                                   cwd=ROOT, env=environment, check=False)
        assert completed.returncode == 0, completed.returncode
        result = json.loads((ROOT / "output/tour-result.json").read_text(encoding="utf-8"))
        course = request("course_status")
        assert result["target"] == target and result["completed"], result
        assert target in result["marker_ids_seen"], result
        assert result["light_colors_seen"] == ["red", "green"], result
        assert result["obstacle_stops"] >= 1, result
        assert course["red_crossings"] == 0 and course["closed_gate_crossings"] == 0, course
        assert course["red_wait_seconds"] >= 4.9 and course["gate_wait_seconds"] >= 2.9, course
        assert math.hypot(*result["finish_pose"][:2]) < 0.02, result
        assert result["duration_sim_seconds"] <= 180, result
        image = cv2.imread(str(ROOT / "output/photos/selected-painting.jpg"))
        assert target in Vision().markers(image)
        trace = json.loads((ROOT / "output/tour-trace.json").read_text(encoding="utf-8"))
        offsets = []
        for x, y, _ in trace:
            qx, qy = abs(x) - 0.75, abs(y - 0.1) - 0.45
            offsets.append(math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 0.5)
        result["right_lane_offset_min_max_m"] = [min(offsets), max(offsets)]
        assert min(offsets) > 0.10 and max(offsets) < 0.26, result
        result["course"] = course
        reports.append(result)
        (ROOT / "output/verification.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)

    request("drive", [0.05, 0])
    time.sleep(1.3)
    first = request("pose")
    time.sleep(0.7)
    second = request("pose")
    assert math.dist(first[:2], second[:2]) < 0.002, (first, second)
    request("reset")
    print("ALL MUSEUM RUNS AND DRIVE WATCHDOG PASSED", flush=True)


if __name__ == "__main__":
    main()
