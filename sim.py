"""Управление учебным полигоном: python sim.py [--reset | --stop]."""

import sys

from simulation.launcher import main

raise SystemExit(main(sys.argv[1:]))
