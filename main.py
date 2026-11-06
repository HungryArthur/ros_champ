"""Учебный заезд: дорога → светофор → шлагбаум → картина → парковка."""

import argparse

from turtlebro_py import TurtleBro
from tour import MuseumGuide


def main():
    parser = argparse.ArgumentParser(description="Робот-экскурсовод в Webots")
    parser.add_argument("--target", type=int, choices=(1, 2, 3), default=3,
                        help="Номер картины по ArUco-маркеру (по умолчанию 3)")
    args = parser.parse_args()

    tb = TurtleBro()
    guide = None
    try:
        guide = MuseumGuide(tb, target=args.target)
        tb.reset()  # Начинаем каждый учебный заезд с одинаковой позиции.
        guide.leave_parking()
        guide.follow_road()
        guide.park()
    except KeyboardInterrupt:
        if guide:
            guide.record_failure("Заезд прерван пользователем", "interrupted")
        print("Заезд прерван.")
        return 130
    except RuntimeError as error:
        if guide:
            guide.record_failure(str(error))
        try:
            tb.color("red")
        except RuntimeError:
            pass
        print("Заезд остановлен:", error, flush=True)
        return 1
    finally:
        try:
            tb.stop()
        except RuntimeError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
