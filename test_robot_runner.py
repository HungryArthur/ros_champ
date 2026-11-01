import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zlib

import robot_runner


PROGRAM = Path(__file__).resolve().with_name("main.py")


class RobotRunnerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.program = Path(folder.name) / "exercise.py"
        self.program.write_text(
            'from turtlebro_py import TurtleBro\nTurtleBro().say("Привет мир")\n',
            encoding="utf-8",
        )

    def test_bundle_contains_only_user_program_without_vendored_library(self):
        bundle = robot_runner.make_bundle(PROGRAM, debug=True)
        data = json.loads(zlib.decompress(base64.b64decode(bundle)))
        self.assertEqual(
            data["files"], {"main.py": PROGRAM.read_text(encoding="utf-8")},
        )
        self.assertEqual(data["args"], ["--debug"])

    def execute_bundle(self, fail=False):
        encoded = robot_runner.make_bundle(self.program, debug=True)
        installed_library = types.ModuleType("turtlebro_py")
        exec("""
class TurtleBro:
    def say(self, text):
        print("say:" + text)
        if FAIL:
            raise RuntimeError("speech unavailable")
""".replace("FAIL", repr(fail)), installed_library.__dict__)
        output = io.StringIO()
        old_path = sys.path[:]
        try:
            with patch.dict(sys.modules, {"turtlebro_py": installed_library}), \
                    patch.object(sys, "argv", ["-c", encoded]), \
                    patch.object(signal, "SIGHUP", 1, create=True), \
                    patch.object(signal, "signal"), redirect_stdout(output):
                try:
                    exec(compile(robot_runner.BOOTSTRAP, "<bootstrap>", "exec"), {})
                finally:
                    self.assertFalse(Path(sys.argv[0]).parent.exists())
                    self.assertEqual(sys.argv[1:], ["--debug"])
        finally:
            sys.path[:] = old_path
            self.output = output.getvalue()

    def test_bootstrap_runs_user_speech_and_removes_temporary_files(self):
        self.execute_bundle()
        self.assertIn("say:Привет мир", self.output)

    def test_local_runner_uses_installed_library_from_environment(self):
        library_folder = self.program.parent / "installed"
        library_folder.mkdir()
        (library_folder / "turtlebro_py.py").write_text(
            'class TurtleBro:\n    def say(self, text):\n        print("installed:" + text)\n',
            encoding="utf-8",
        )
        # Эмуляция установленного пакета, доступного через окружение ROS.
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(library_folder)
        environment["PYTHONIOENCODING"] = "utf-8"
        # Используем отдельную программу, чтобы тест не зависел от упражнений в main.py.
        command = (
            "import robot_runner; from pathlib import Path; "
            "raise SystemExit(robot_runner.run(Path(%r), ['--local']))" % str(self.program)
        )
        result = subprocess.run(
            [sys.executable, "-c", command], cwd=PROGRAM.parent,
            env=environment, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn("installed:Привет мир", result.stdout.decode("utf-8"))

    def test_bootstrap_preserves_program_errors_and_cleans_up(self):
        with self.assertRaisesRegex(RuntimeError, "speech unavailable"):
            self.execute_bundle(fail=True)
        self.assertIn("say:Привет мир", self.output)

    def test_shell_quoting_preserves_setup_path(self):
        setup = "/home/pi/robot's $(echo injected); folder/setup.bash"
        outer = shlex.split(robot_runner.remote_command("BUNDLE", setup))
        self.assertEqual(outer[:2], ["bash", "-lc"])
        inner = shlex.split(outer[2])
        self.assertEqual(inner[:3], ["source", setup, "&&"])
        self.assertEqual(inner[3:], ["exec", "python3", "-u", "-c", robot_runner.BOOTSTRAP, "BUNDLE"])

    def test_ssh_uses_terminal_and_propagates_remote_exit_status(self):
        with patch("robot_runner.shutil.which", return_value="ssh"), \
                patch("robot_runner.subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as execute, \
                redirect_stdout(io.StringIO()):
            code = robot_runner.run(PROGRAM, ["--host", "pi@robot", "--port", "2222", "--debug"])
        self.assertEqual(code, 7)
        command = execute.call_args.args[0]
        self.assertEqual(command[0:2], ["ssh", "-tt"])
        self.assertEqual(command[-4:-1], ["-p", "2222", "pi@robot"])
        self.assertEqual(execute.call_args.kwargs, {"check": False})
        self.assertLess(len(subprocess.list2cmdline(command)), 30000)

    def test_missing_address_explains_how_to_find_it_without_connecting(self):
        error = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), \
                patch("robot_runner.subprocess.run") as execute, redirect_stderr(error):
            with self.assertRaises(SystemExit) as failure:
                robot_runner.run(PROGRAM, [])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("hostname -I", error.getvalue())
        execute.assert_not_called()

    def test_missing_ssh_reports_required_windows_component(self):
        error = io.StringIO()
        with patch("robot_runner.shutil.which", return_value=None), redirect_stderr(error):
            self.assertEqual(robot_runner.run(PROGRAM, ["--host", "pi@robot"]), 1)
        self.assertIn("OpenSSH", error.getvalue())

    def test_bad_port_is_rejected_before_connecting(self):
        with patch("robot_runner.subprocess.run") as execute, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                robot_runner.run(PROGRAM, ["--host", "pi@robot", "--port", "70000"])
        self.assertEqual(failure.exception.code, 2)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
