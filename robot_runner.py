"""Запуск main.py настоящей библиотекой TurtleBro в ROS-окружении робота."""

import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import zlib

# Передаём только программу. Библиотека производителя установлена на самом роботе.
BOOTSTRAP = """\
import base64, json, runpy, signal, sys, tempfile, zlib
from pathlib import Path

def disconnected(signum, frame):
    raise SystemExit(129)

if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, disconnected)
bundle = json.loads(zlib.decompress(base64.b64decode(sys.argv[1])))
with tempfile.TemporaryDirectory(prefix="turtlebro-") as folder:
    root = Path(folder)
    for name, source in bundle["files"].items():
        (root / name).write_text(source, encoding="utf-8")
    sys.path.insert(0, folder)
    # Исходный модуль из стандартного catkin_ws, если он не установлен в site-packages.
    library = Path.home() / "catkin_ws/src/turtlebro_extra/turtlebro_py/src"
    if (library / "turtlebro_py.py").is_file():
        sys.path.insert(1, str(library))
    sys.argv = [str(root / "main.py")] + bundle["args"]
    runpy.run_path(sys.argv[0], run_name="__main__")
"""


def make_bundle(program, debug=False):
    bundle = {
        "files": {
            "main.py": program.read_text(encoding="utf-8-sig"),
        },
        "args": ["--debug"] if debug else [],
    }
    raw = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(zlib.compress(raw)).decode("ascii")


def remote_command(bundle, setup):
    command = ""
    if setup:
        if setup.startswith("~/"):
            setup = '"$HOME"/' + shlex.quote(setup[2:])
        else:
            setup = shlex.quote(setup)
        command = "source " + setup + " && "
    command += "exec python3 -u -c " + shlex.quote(BOOTSTRAP)
    command += " " + shlex.quote(bundle)
    return "bash -lc " + shlex.quote(command)


def run(program, argv=None):
    parser = argparse.ArgumentParser(
        description="Запустить main.py на TurtleBro через SSH с Windows или Linux."
    )
    parser.add_argument(
        "--host", default=os.environ.get("TURTLEBRO_HOST"),
        help="SSH-адрес робота, например pi@192.168.1.100 (или TURTLEBRO_HOST)",
    )
    parser.add_argument("--port", type=int, default=22, help="Порт SSH (22)")
    parser.add_argument(
        "--ros-setup", default="~/catkin_ws/devel/setup.bash",
        help="Путь к setup.bash на роботе; пустая строка использует окружение SSH",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Отладка TurtleBro")
    parser.add_argument(
        "--local", action="store_true", help="Выполнить на этом устройстве с ROS"
    )
    args = parser.parse_args(argv)
    program = Path(program).resolve()

    if args.local:
        try:
            # Папка проекта не попадает в sys.path: импортируется библиотека робота.
            with tempfile.TemporaryDirectory(prefix="turtlebro-local-") as folder:
                result = subprocess.run(
                    [sys.executable, "-u", "-c", BOOTSTRAP, make_bundle(program, args.debug)],
                    cwd=folder, check=False,
                )
            return result.returncode
        except OSError as exc:
            print("Ошибка запуска: %s" % exc, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130

    if not args.host:
        parser.error(
            "укажите адрес робота: python robot_runner.py --host pi@IP_РОБОТА. "
            "IP можно посмотреть на роботе командой hostname -I."
        )
    if args.host.startswith("-") or any(c.isspace() for c in args.host):
        parser.error("--host должен иметь вид пользователь@адрес без пробелов")
    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть от 1 до 65535")
    ssh = shutil.which("ssh")
    if ssh is None:
        print("Не найден ssh. Установите Клиент OpenSSH (Windows) или openssh-client (Linux).", file=sys.stderr)
        return 1

    try:
        bundle = make_bundle(program, args.debug)
        command = [
            ssh, "-tt", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "-p", str(args.port), args.host,
            remote_command(bundle, args.ros_setup),
        ]
        if os.name == "nt" and len(subprocess.list2cmdline(command)) > 30000:
            print("Программа слишком велика для командной строки Windows.", file=sys.stderr)
            return 1
        print("Подключение к %s…" % args.host, flush=True)
        # Терминал нужен для пароля SSH и передачи Ctrl+C на робот.
        result = subprocess.run(command, check=False)
    except OSError as exc:
        print("Ошибка запуска: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    if result.returncode == 255:
        print("SSH не подключился. Проверьте адрес, сеть и доступ к роботу.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(run(Path(__file__).with_name("main.py")))
