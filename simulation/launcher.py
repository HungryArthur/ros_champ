"""Открывает мир Webots и ждёт готовности контроллера."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "webots/worlds/turtlebro.wbt"
STATE = ROOT / ".webots_state"
URL = "http://127.0.0.1:18761"
HTTP = build_opener(ProxyHandler({}))


def health():
    try:
        with HTTP.open(URL + "/health", timeout=1) as response:
            info = json.load(response)
        if info.get("robot") != "TurtleBro" or os.path.normcase(info.get("project", "")) != os.path.normcase(str(ROOT)):
            raise RuntimeError("Уже открыт TurtleBro из другой папки. Закройте его окно Webots.")
        return info
    except (URLError, TimeoutError, ConnectionError):
        return None


def find_webots():
    candidates = [os.environ.get("WEBOTS_HOME", "")]
    if os.name == "nt":
        candidates += [
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Webots"),
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Webots"),
        ]
    else:
        candidates += ["/usr/local/webots", "/usr/share/webots", "/Applications/Webots.app/Contents"]
    for candidate in candidates:
        home = Path(candidate)
        binary = home / ("msys64/mingw64/bin/webots.exe" if os.name == "nt" else "webots")
        if candidate and binary.is_file():
            return home, binary
    binary = shutil.which("webots")
    if binary:
        binary = Path(binary).resolve()
        return binary.parent, binary
    raise RuntimeError("Установите Webots R2025a или новее и укажите его папку в WEBOTS_HOME.")


def ensure_running():
    if health():
        return
    home, binary = find_webots()
    STATE.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment["WEBOTS_HOME"] = str(home)
    runtime = ROOT / "webots/controllers/turtlebro_bridge/runtime.ini"
    runtime.write_text("[python]\nCOMMAND = " + sys.executable + "\n", encoding="utf-8")
    with (STATE / "webots.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(binary), "--mode=realtime", "--stdout", "--stderr", str(WORLD)],
            cwd=str(ROOT), env=environment, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    (STATE / "webots.pid").write_text(str(process.pid))
    print("Открываю TurtleBro в Webots…", flush=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if health():
            return
        if process.poll() is not None and process.returncode:
            break
        time.sleep(0.25)
    raise RuntimeError("Контроллер Webots не запустился. Смотрите .webots_state/webots.log; в Webots включите ▶.")


def request(method, arguments=None, timeout=120):
    data = json.dumps({"method": method, "arguments": arguments or []}, ensure_ascii=False).encode("utf-8")
    message = Request(URL + "/command", data=data, headers={"Content-Type": "application/json"})
    try:
        with HTTP.open(message, timeout=timeout) as response:
            result = json.load(response)
    except (URLError, TimeoutError, ConnectionError) as error:
        raise RuntimeError("Webots не ответил. Проверьте, что мир открыт и не стоит на паузе.") from error
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Ошибка контроллера Webots"))
    return result.get("result")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Полигон TurtleBro в Webots")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--reset", action="store_true", help="Вернуть робота и ящики на старт")
    actions.add_argument("--stop", action="store_true", help="Закрыть учебный мир Webots")
    args = parser.parse_args(argv)
    try:
        if args.stop:
            if health():
                request("quit")
                deadline = time.monotonic() + 10
                while health() and time.monotonic() < deadline:
                    time.sleep(0.1)
            print("Учебный мир Webots закрыт.")
        else:
            ensure_running()
            if args.reset:
                request("reset")
                print("Робот и ящики возвращены на старт.")
            else:
                print("Полигон готов. Запустите python main.py")
        return 0
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
