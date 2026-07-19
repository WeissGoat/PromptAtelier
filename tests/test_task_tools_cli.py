from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tags_machine_core.cli import build_parser
from tags_machine_core.task_tools.cli import (
    cmd_task_tools_install,
    run_task_tool_operation,
)


def test_task_tools_run_parser_preserves_multiple_input_paths() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "task-tools",
            "run",
            "open_action_directory",
            "--",
            r"G:\ai_auto\task-a",
            r"G:\ai_auto\task b\image.png",
        ]
    )

    assert args.task_tool_command == "run"
    assert args.operation_id == "open_action_directory"
    assert args.inputs == [r"G:\ai_auto\task-a", r"G:\ai_auto\task b\image.png"]


def test_task_tools_launcher_parser_accepts_config_before_inputs(tmp_path: Path) -> None:
    config = tmp_path / "task-tools.yaml"
    args = build_parser().parse_args(
        ["task-tools", "launcher", "--config", str(config), "--", "task-a"]
    )

    assert args.task_tool_command == "launcher"
    assert args.config == config
    assert args.inputs == ["task-a"]


@patch("tags_machine_core.task_tools.cli.TaskArchiveResolver")
def test_quick_run_reports_errors_through_notifier(resolver_type, tmp_path: Path) -> None:
    resolver_type.return_value.resolve.side_effect = RuntimeError("归档损坏")
    notifier = Mock()

    exit_code = run_task_tool_operation(
        operation_id="open_action_directory",
        inputs=[str(tmp_path)],
        config_path=None,
        notifier=notifier,
    )

    assert exit_code == 1
    notifier.assert_called_once_with("Refactor 任务工具", "归档损坏")


@patch("tags_machine_core.task_tools.cli.TaskToolRunner")
@patch("tags_machine_core.task_tools.cli.TaskArchiveResolver")
def test_quick_run_passes_config_log_level_to_runner(
    resolver_type,
    runner_type,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "task-tools.yaml"
    config_path.write_text("log_level: warning\n", encoding="utf-8")

    exit_code = run_task_tool_operation(
        operation_id="open_action_directory",
        inputs=[str(tmp_path)],
        config_path=config_path,
    )

    assert exit_code == 0
    assert runner_type.call_args.kwargs["log_level"] == "warning"
    runner_type.return_value.run.assert_called_once_with(
        "open_action_directory",
        resolver_type.return_value.resolve.return_value,
    )


@patch("tags_machine_core.task_tools.cli.show_error")
@patch("tags_machine_core.task_tools.cli.SendToInstaller")
@patch("tags_machine_core.task_tools.cli.Path")
def test_install_rejects_missing_pythonw(path_type, installer_type, show_error) -> None:
    executable = Mock()
    executable.with_name.return_value.is_file.return_value = False
    path_type.return_value = executable
    args = SimpleNamespace(config=None)

    exit_code = cmd_task_tools_install(args)

    assert exit_code == 1
    installer_type.assert_not_called()
    show_error.assert_called_once()
