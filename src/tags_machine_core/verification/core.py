from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


CORE_VERIFICATION_SCHEMA = "tags-machine-core.core-verification/v1"

RunnerResult = Any
CommandRunner = Callable[[Sequence[str], Path], RunnerResult]


def run_core_verification(
    *,
    cwd: str | Path = ".",
    dry_run: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """运行当前 v1 无联网门禁；旧项目 oracle 的严格验收由独立 acceptance suite 完成。"""

    cwd_path = Path(cwd)
    commands = _core_verification_commands()
    items: list[dict[str, Any]] = []
    if dry_run:
        for command in commands:
            items.append(
                {
                    "label": command["label"],
                    "command": command["command"],
                    "command_text": _command_text(command["command"]),
                    "status": "pending",
                }
            )
        return _verification_result(cwd_path, dry_run=True, items=items)

    command_runner = runner or _subprocess_runner
    for command in commands:
        completed = command_runner(command["command"], cwd_path)
        returncode = int(getattr(completed, "returncode", 1))
        items.append(
            {
                "label": command["label"],
                "command": command["command"],
                "command_text": _command_text(command["command"]),
                "status": "pass" if returncode == 0 else "fail",
                "returncode": returncode,
                "stdout_tail": _tail_text(getattr(completed, "stdout", "")),
                "stderr_tail": _tail_text(getattr(completed, "stderr", "")),
            }
        )
    return _verification_result(cwd_path, dry_run=False, items=items)


def _core_verification_commands() -> list[dict[str, Any]]:
    python = sys.executable
    return [
        {
            "label": "compileall",
            "command": [python, "-m", "compileall", "-q", "src", "tests"],
        },
        {
            "label": "unittest_discover",
            "command": [python, "-m", "unittest", "discover", "-s", "tests"],
        },
        {
            "label": "validate_example_nodes",
            "command": [python, "-m", "tags_machine_core", "validate-node-tree", "examples/nodes"],
        },
        {
            "label": "fixture_acceptance_suite",
            "command": [
                python,
                "-m",
                "tags_machine_core",
                "verify-acceptance-suite",
                "examples/acceptance/suite.yaml",
                "--require-minimum-set",
            ],
        },
        {
            "label": "git_diff_check",
            "command": ["git", "diff", "--check"],
        },
    ]


def _verification_result(
    cwd: Path,
    *,
    dry_run: bool,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    fail_count = sum(1 for item in items if item.get("status") == "fail")
    pass_count = sum(1 for item in items if item.get("status") == "pass")
    match = fail_count == 0
    return {
        "schema": CORE_VERIFICATION_SCHEMA,
        "cwd": str(cwd),
        "dry_run": dry_run,
        "match": match,
        "result": "dry_run" if dry_run else ("pass" if match else "fail"),
        "summary": {
            "total": len(items),
            "pass_count": pass_count,
            "fail_count": fail_count,
        },
        "commands": items,
    }


def _subprocess_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _tail_text(value: Any, *, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-limit:]


def _command_text(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])
