from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import dev_web


class DevWebProcessManagementTest(TestCase):
    def test_cleanup_stops_recorded_process_trees_and_removes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dev_web.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema": "promptatelier.dev-web/v1",
                        "root": str(dev_web.ROOT),
                        "instance_id": "old-instance",
                        "backend_pid": 101,
                        "frontend_pid": 202,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(dev_web, "_terminate_pid_tree") as terminate,
                patch.object(dev_web, "_port_owner_pid", return_value=None),
            ):
                dev_web._cleanup_previous_instance(8765, 53173, state_path=state_path)

        self.assertEqual([call.args[0] for call in terminate.call_args_list], [101, 202])
        self.assertFalse(state_path.exists())

    def test_cleanup_stops_owned_port_process_when_state_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "missing.json"
            with (
                patch.object(dev_web, "_port_owner_pid", side_effect=[303, None]),
                patch.object(dev_web, "_is_owned_port_process", return_value=True),
                patch.object(dev_web, "_terminate_pid_tree") as terminate,
            ):
                dev_web._cleanup_previous_instance(8765, 53173, state_path=state_path)

        terminate.assert_called_once_with(303)

    def test_owned_process_root_selects_uvicorn_reload_supervisor(self):
        chain = [
            {
                "ProcessId": 303,
                "ParentProcessId": 202,
                "Name": "python.exe",
                "CommandLine": "python -c multiprocessing.spawn_main",
            },
            {
                "ProcessId": 202,
                "ParentProcessId": 101,
                "Name": "python.exe",
                "CommandLine": (
                    f"{dev_web.ROOT}\\.venv\\Scripts\\python.exe "
                    "-m tags_machine_core.web --reload"
                ),
            },
            {
                "ProcessId": 101,
                "ParentProcessId": 1,
                "Name": "python.exe",
                "CommandLine": "python scripts/dev_web.py",
            },
        ]
        with patch.object(dev_web, "_process_chain", return_value=chain):
            target = dev_web._owned_process_root(303, "backend")

        self.assertEqual(target, 202)

    def test_cleanup_refuses_to_stop_unknown_port_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "missing.json"
            with (
                patch.object(dev_web, "_port_owner_pid", return_value=404),
                patch.object(dev_web, "_is_owned_port_process", return_value=False),
                patch.object(dev_web, "_describe_process", return_value="other-service.exe --serve"),
            ):
                with self.assertRaisesRegex(RuntimeError, "404.*other-service"):
                    dev_web._cleanup_previous_instance(8765, 53173, state_path=state_path)

    def test_cleanup_ignores_process_that_exits_during_ownership_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "missing.json"
            with (
                patch.object(dev_web, "_port_owner_pid", side_effect=[606, None, None]),
                patch.object(dev_web, "_is_owned_port_process", return_value=False),
                patch.object(dev_web, "_terminate_pid_tree") as terminate,
            ):
                dev_web._cleanup_previous_instance(8765, 53173, state_path=state_path)

        terminate.assert_not_called()

    def test_stop_only_cleans_previous_instance(self):
        popen = MagicMock()
        with (
            patch.object(dev_web, "_cleanup_previous_instance") as cleanup,
            patch.object(dev_web, "_ensure_frontend_deps") as ensure_deps,
            patch.object(dev_web.subprocess, "Popen", popen),
        ):
            result = dev_web.main(["--stop"])

        self.assertEqual(result, 0)
        cleanup.assert_called_once_with(
            dev_web.DEFAULT_BACKEND_PORT,
            dev_web.DEFAULT_FRONTEND_PORT,
        )
        ensure_deps.assert_not_called()
        popen.assert_not_called()

    def test_clear_state_does_not_remove_newer_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dev_web.json"
            state_path.write_text(
                json.dumps({"instance_id": "new-instance"}),
                encoding="utf-8",
            )

            dev_web._clear_state("old-instance", state_path=state_path)

            self.assertTrue(state_path.exists())

    def test_windows_termination_uses_taskkill_tree(self):
        with (
            patch.object(dev_web.os, "name", "nt"),
            patch.object(dev_web.subprocess, "run") as run,
        ):
            dev_web._terminate_pid_tree(505)

        run.assert_called_once_with(
            ["taskkill", "/PID", "505", "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
