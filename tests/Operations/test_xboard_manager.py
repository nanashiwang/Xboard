"""Exercise the real CLI with a fake Docker daemon; never touch live containers."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / ".docker/production/xboard.sh"
DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
if a[:2] == ["compose", "--project-directory"]:
    assert a[2] == os.environ["XBOARD_DIR"]
    a = ["compose"] + a[3:]
with open(os.environ["MOCK_LOG"], "a") as f:
    f.write(json.dumps({"args": a, "cwd": os.getcwd(), "compose_file": os.getenv("COMPOSE_FILE")}) + "\n")
if a == ["compose", "version"]:
    print("Docker Compose version v2.39.0")
elif a == ["compose", "config", "--services"]:
    print(os.getenv("MOCK_SERVICES", "xboard\nredis"))
elif a == ["compose", "config", "--format", "json"]:
    volumes = [{"type": "bind", "source": "./data", "target": "/www/storage"}]
    if os.getenv("MOCK_SOURCE_MOUNT"):
        volumes.append({"type": "bind", "source": ".", "target": "/www/"})
    if os.getenv("MOCK_ANON_VOLUME"):
        volumes.append({"type": "volume", "target": "/data"})
    print(json.dumps({"services": {"xboard": {"image": "example/xboard:latest", "volumes": volumes}}}))
elif a[:2] == ["compose", "pull"]:
    sys.exit(int(os.getenv("MOCK_PULL_EXIT", "0")))
elif a[:2] == ["compose", "run"]:
    # A real command may read stdin. The manager must isolate it from the menu.
    assert sys.stdin.read() == ""
    sys.exit(int(os.getenv("MOCK_RUN_EXIT", "0")))
elif a == ["compose", "up", "--help"]:
    print("" if os.getenv("MOCK_OLD_COMPOSE") else "--wait --wait-timeout")
elif a[:2] == ["compose", "up"]:
    sys.exit(int(os.getenv("MOCK_UP_EXIT", "0")))
elif a[:2] == ["compose", "ps"]:
    if "-q" in a:
        print("" if os.getenv("MOCK_NO_CONTAINER") else "container-1")
    else:
        print("xboard running")
elif a[:2] in (["compose", "restart"], ["compose", "stop"], ["compose", "rm"], ["compose", "logs"]):
    pass
elif a[:2] == ["image", "inspect"]:
    print("sha256:new" if a[3] == "{{.Id}}" else "a" * 40)
elif a[0] == "inspect":
    if a[2] == "{{.Image}}":
        print(os.getenv("MOCK_RUNNING_IMAGE", "sha256:new"))
    elif a[2] == "{{.State.Running}}":
        print(os.getenv("MOCK_RUNNING", "true"))
    elif a[2] == "{{json .Mounts}}":
        print(json.dumps([{"Type": "volume", "Name": "anonymous-volume"}] if os.getenv("MOCK_IMAGE_VOLUME") else []))
    else:
        sys.exit("Unexpected inspect: " + repr(a))
else:
    sys.exit("Unexpected Docker operation: " + repr(a))
'''


class XboardManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xboard manager ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "compose.yaml").write_text("services: {}\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker.log"
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "XBOARD_DIR": str(self.project),
            "XBOARD_BIN_DIR": str(self.root / "installed"),
            "MOCK_LOG": str(self.log),
        }
        for name, source in {
            "docker": DOCKER,
            "flock": '#!/bin/sh\nexit "${MOCK_LOCK_EXIT:-0}"\n',
        }.items():
            path = self.bin / name
            path.write_text(source)
            path.chmod(0o755)

    def run_cli(self, *args, input="", **env):
        return subprocess.run(
            ["bash", str(SCRIPT), *args], input=input, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**self.env, **env}, cwd=self.root, timeout=15,
        )

    def calls(self):
        return [json.loads(line)["args"] for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def mutations(self):
        return [a for a in self.calls() if "--help" not in a and a[:2] in (
            ["compose", "pull"], ["compose", "run"], ["compose", "up"],
            ["compose", "stop"], ["compose", "restart"], ["compose", "rm"],
        )]

    def test_menu_exit_and_help_do_not_mutate(self):
        result = self.run_cli(input="0\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("卸载服务（保留数据）", result.stdout)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.run_cli("help", XBOARD_DIR="/does/not/exist").returncode, 0)

    def test_install_from_any_directory_and_reinstall(self):
        for _ in range(2):
            result = self.run_cli("install")
            self.assertEqual(result.returncode, 0, result.stdout)
        installed = Path(self.env["XBOARD_BIN_DIR"]) / "xboard"
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        result = subprocess.run([str(installed), "version"], capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1.0.0", result.stdout)
        self.assertEqual(self.mutations(), [])

    def test_install_refuses_unrelated_program(self):
        target = Path(self.env["XBOARD_BIN_DIR"]) / "xboard"
        target.parent.mkdir()
        target.write_text("unrelated program")
        self.assertNotEqual(self.run_cli("install").returncode, 0)
        self.assertEqual(target.read_text(), "unrelated program")

    def test_update_orders_migration_before_start_and_verifies_image(self):
        result = self.run_cli("update", "--yes", XBOARD_EXPECTED_REVISION="a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([a[1] for a in self.mutations()], ["pull", "run", "up"])
        self.assertIn("--wait", self.mutations()[2])
        self.assertIn("更新完成", result.stdout)

    def test_update_failures_never_report_success(self):
        for variable, commands in (
            ("MOCK_PULL_EXIT", ["pull"]),
            ("MOCK_RUN_EXIT", ["pull", "run"]),
            ("MOCK_UP_EXIT", ["pull", "run", "up"]),
        ):
            with self.subTest(variable=variable):
                self.log.unlink(missing_ok=True)
                result = self.run_cli("update", "--yes", **{variable: "21"})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("更新完成", result.stdout)
                self.assertEqual([a[1] for a in self.mutations()], commands)

    def test_revision_mismatch_stops_before_migration(self):
        result = self.run_cli("update", "--yes", XBOARD_EXPECTED_REVISION="b" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([a[1] for a in self.mutations()], ["pull"])

    def test_wrong_running_image_is_failure(self):
        result = self.run_cli("update", "--yes", MOCK_RUNNING_IMAGE="sha256:old")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("更新完成", result.stdout)

    def test_source_mount_is_rejected_before_pull(self):
        result = self.run_cli("update", "--yes", MOCK_SOURCE_MOUNT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_busy_lock_prevents_mutations(self):
        result = self.run_cli("update", "--yes", MOCK_LOCK_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_menu_survives_update_failure_and_accepts_next_choice(self):
        result = self.run_cli(input="1\ny\n\n5\n\n0\n", MOCK_RUN_EXIT="21")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("本次操作未完成", result.stdout)
        self.assertIn("运行镜像", result.stdout)
        self.assertNotIn("更新完成", result.stdout)
        self.assertEqual([a[1] for a in self.mutations()], ["pull", "run"])

    def test_update_confirmation_defaults_to_cancel(self):
        for answer in ("", "\n", "n\n"):
            self.assertEqual(self.run_cli("update", input=answer).returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_restart_does_not_pull_or_migrate(self):
        result = self.run_cli("restart", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([a[1] for a in self.mutations()], ["restart", "up"])
        self.assertIn("--no-recreate", self.mutations()[1])
        self.assertNotEqual(self.run_cli("restart", "--yes", MOCK_NO_CONTAINER="1").returncode, 0)

    def test_uninstall_requires_explicit_confirmation(self):
        for answer in ("", "y\n", "uninstall\n"):
            self.assertEqual(self.run_cli("uninstall", input=answer).returncode, 0)
        self.assertNotEqual(self.run_cli("uninstall", "--yes", input="UNINSTALL\n").returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_uninstall_only_removes_xboard_and_keeps_data(self):
        sentinel = self.project / "database.sqlite"
        sentinel.write_text("preserve me")
        result = self.run_cli("uninstall", input="UNINSTALL\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.mutations(), [["compose", "stop", "xboard"], ["compose", "rm", "--force", "xboard"]])
        self.assertEqual(sentinel.read_text(), "preserve me")

    def test_uninstall_rejects_anonymous_volumes(self):
        for variable in ("MOCK_ANON_VOLUME", "MOCK_IMAGE_VOLUME"):
            result = self.run_cli("uninstall", input="UNINSTALL\n", **{variable: "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.mutations(), [])

    def test_old_compose_is_rejected_before_migrations(self):
        result = self.run_cli("update", "--yes", MOCK_OLD_COMPOSE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_wrong_project_and_stale_shell_overrides(self):
        result = self.run_cli("stop", "--yes", MOCK_SERVICES="web\nredis")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])
        result = self.run_cli("status", COMPOSE_FILE="/unrelated/compose.yml")
        self.assertEqual(result.returncode, 0, result.stdout)
        for line in self.log.read_text().splitlines():
            self.assertIsNone(json.loads(line)["compose_file"])
            self.assertEqual(json.loads(line)["cwd"], str(self.project))

    def test_start_stop_and_logs_are_scoped(self):
        for action in ("start", "stop"):
            result = self.run_cli(action, "--yes")
            self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.run_cli("logs").returncode, 0)
        self.assertTrue(all(a[-1] == "xboard" for a in self.mutations()))
        self.assertIn(["compose", "logs", "--tail", "100", "xboard"], self.calls())


if __name__ == "__main__":
    unittest.main()
