"""Соединяет устройства модели с обычными Python-скриптами."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.bridge import run

run()
