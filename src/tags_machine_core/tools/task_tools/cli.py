from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import sys
from typing import Any

from .config import load_task_tools_config
from .registry import build_default_registry
from .resolver import TaskArchiveResolver
from .runner import TaskToolRunner
from .windows.launcher import launch_task_tools_window
from .windows.notifications import show_error
from .windows.sendto_installer import SendToInstaller, SendToInstallResult


Notifier = Callable[[str, str], None]


def add_task_tools_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    output_parent: argparse.ArgumentParser,
) -> None:
    parser = subparsers.add_parser(
        "task-tools",
        parents=[output_parent],
        help="Windows task archive convenience tools",
    )
    commands = parser.add_subparsers(dest="task_tool_command", required=True)

    run = commands.add_parser("run", help="Run one registered task operation")
    run.add_argument("operation_id")
    run.add_argument("--config", type=Path)
    run.add_argument("inputs", nargs="+")
    run.set_defaults(func=cmd_task_tools_run)

    launcher = commands.add_parser("launcher", help="Open the task tools window")
    launcher.add_argument("--config", type=Path)
    launcher.add_argument("inputs", nargs="+")
    launcher.set_defaults(func=cmd_task_tools_launcher)

    install = commands.add_parser("install-sendto", help="Install SendTo entries")
    install.add_argument("--config", type=Path)
    install.set_defaults(func=cmd_task_tools_install)

    sync = commands.add_parser("sync-sendto", help="Sync SendTo entries from config")
    sync.add_argument("--config", type=Path)
    sync.set_defaults(func=cmd_task_tools_sync)

    uninstall = commands.add_parser("uninstall-sendto", help="Remove managed SendTo entries")
    uninstall.set_defaults(func=cmd_task_tools_uninstall)


def run_task_tool_operation(
    *,
    operation_id: str,
    inputs: list[str],
    config_path: Path | None,
    notifier: Notifier = show_error,
) -> int:
    try:
        registry = build_default_registry()
        config = load_task_tools_config(config_path, registry=registry)
        contexts = TaskArchiveResolver().resolve(inputs)
        TaskToolRunner(
            registry=registry,
            config=config,
            log_level=config.log_level,
        ).run(operation_id, contexts)
        return 0
    except Exception as exc:
        notifier("Refactor 任务工具", str(exc))
        return 1


def cmd_task_tools_run(args: argparse.Namespace) -> int:
    return run_task_tool_operation(
        operation_id=args.operation_id,
        inputs=args.inputs,
        config_path=args.config,
    )


def cmd_task_tools_launcher(args: argparse.Namespace) -> int:
    try:
        registry = build_default_registry()
        config = load_task_tools_config(args.config, registry=registry)
        contexts = TaskArchiveResolver().resolve(args.inputs)
        runner = TaskToolRunner(
            registry=registry,
            config=config,
            log_level=config.log_level,
        )
        return launch_task_tools_window(
            contexts=contexts,
            registry=registry,
            config=config,
            runner=runner,
        )
    except Exception as exc:
        show_error("Refactor 任务工具", str(exc))
        return 1


def cmd_task_tools_install(args: argparse.Namespace) -> int:
    try:
        registry = build_default_registry()
        config = load_task_tools_config(args.config, registry=registry)
        project_root = _project_root()
        pythonw_path = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw_path.is_file():
            raise RuntimeError(f"Refactor Python 图形入口不存在：{pythonw_path}")
        result = SendToInstaller().install(
            project_root=project_root,
            pythonw_path=pythonw_path,
            config_path=args.config,
            registry=registry,
            config=config,
        )
        _print_json(_install_result_payload("installed", result))
        return 0
    except Exception as exc:
        show_error("Refactor 任务工具", str(exc))
        return 1


def cmd_task_tools_sync(args: argparse.Namespace) -> int:
    try:
        registry = build_default_registry()
        config = load_task_tools_config(args.config, registry=registry)
        result = SendToInstaller().sync(
            registry=registry,
            config=config,
            config_path=args.config,
        )
        _print_json(_install_result_payload("synced", result))
        return 0
    except Exception as exc:
        show_error("Refactor 任务工具", str(exc))
        return 1


def cmd_task_tools_uninstall(args: argparse.Namespace) -> int:
    try:
        removed = SendToInstaller().uninstall()
        _print_json(
            {
                "status": "uninstalled",
                "removed": [str(path) for path in removed],
            }
        )
        return 0
    except Exception as exc:
        show_error("Refactor 任务工具", str(exc))
        return 1


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _install_result_payload(status: str, result: SendToInstallResult) -> dict[str, Any]:
    return {
        "status": status,
        "app_dir": str(result.app_dir),
        "manifest": str(result.manifest_path),
        "sendto_entries": [str(path) for path in result.sendto_entries],
    }


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
