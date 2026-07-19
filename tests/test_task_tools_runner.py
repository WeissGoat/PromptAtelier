from pathlib import Path
from unittest.mock import Mock

import pytest

from tags_machine_core.task_tools.config import load_task_tools_config
from tags_machine_core.task_tools.logging import configure_task_tool_file_logging
from tags_machine_core.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.task_tools.operations.open_directory import open_directory_with_explorer
from tags_machine_core.task_tools.registry import (
    OperationRegistry,
    OperationSpec,
    build_default_registry,
)
from tags_machine_core.task_tools.runner import OperationUnavailableError, TaskToolRunner
from tags_machine_core.task_tools.windows.notifications import show_error


def _contexts(tmp_path: Path, role: str, path: Path) -> TaskContextSet:
    return TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path,
                task_dir=tmp_path,
                resources=[RelatedResource(role=role, id=path.name, ref=str(path), path=path)],
            )
        ]
    )


def _contexts_with_paths(tmp_path: Path, role: str, paths: list[Path]) -> TaskContextSet:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path,
                task_dir=tmp_path,
                resources=[
                    RelatedResource(role=role, id=path.name, ref=str(path), path=path)
                    for path in paths
                ],
            )
        ]
    )


def _multiple_task_contexts(tmp_path: Path) -> TaskContextSet:
    first_action = tmp_path / "action-a"
    second_action = tmp_path / "action-b"
    first_action.mkdir()
    second_action.mkdir()
    return TaskContextSet(
        tasks=[
            _contexts(tmp_path / "task-a", "action", first_action).tasks[0],
            _contexts(tmp_path / "task-b", "action", second_action).tasks[0],
        ]
    )


def test_runner_opens_each_unique_action_directory_once(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    opener = Mock()
    registry = build_default_registry(directory_opener=opener)
    config = load_task_tools_config(None, registry=registry)

    result = TaskToolRunner(registry=registry, config=config).run(
        "open_action_directory",
        _contexts(tmp_path, "action", action),
    )

    opener.assert_called_once_with(action.resolve())
    assert result.affected_paths == [action.resolve()]


def test_runner_opens_duplicate_action_path_across_tasks_once(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    opener = Mock()
    registry = build_default_registry(directory_opener=opener)
    config = load_task_tools_config(None, registry=registry)
    contexts = TaskContextSet(
        tasks=[
            _contexts(tmp_path / "task-a", "action", action).tasks[0],
            _contexts(tmp_path / "task-b", "action", action).tasks[0],
        ]
    )

    result = TaskToolRunner(registry=registry, config=config).run(
        "open_action_directory",
        contexts,
    )

    opener.assert_called_once_with(action.resolve())
    assert result.affected_paths == [action.resolve()]


def test_runner_uses_artist_target_role(tmp_path: Path):
    artist = tmp_path / "artist"
    artist.mkdir()
    opener = Mock()
    registry = build_default_registry(directory_opener=opener)
    config = load_task_tools_config(None, registry=registry)

    result = TaskToolRunner(registry=registry, config=config).run(
        "open_artist_directory",
        _contexts(tmp_path, "artist", artist),
    )

    opener.assert_called_once_with(artist.resolve())
    assert result.operation_id == "open_artist_directory"
    assert result.affected_paths == [artist.resolve()]


def test_runner_rejects_disabled_operation(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)
    config.operations["open_action_directory"].enabled = False

    with pytest.raises(OperationUnavailableError, match="操作已禁用"):
        TaskToolRunner(registry=registry, config=config).run(
            "open_action_directory",
            _contexts(tmp_path, "action", action),
        )


@pytest.mark.parametrize(
    ("contexts_factory", "expected_reason"),
    [
        (
            lambda tmp_path: TaskContextSet(
                tasks=[TaskContext(input_path=tmp_path, task_dir=tmp_path)]
            ),
            "未找到 artist 关联资源",
        ),
        (
            lambda tmp_path: _contexts(tmp_path, "artist", tmp_path / "missing"),
            "artist 目录不存在",
        ),
    ],
)
def test_runner_distinguishes_missing_artist_resource_states(
    tmp_path: Path,
    contexts_factory,
    expected_reason: str,
):
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)

    availability = TaskToolRunner(registry=registry, config=config).availability(
        "open_artist_directory",
        contexts_factory(tmp_path),
    )

    assert availability.enabled is False
    assert availability.reason == expected_reason


def test_runner_checks_resource_availability_before_cardinality(tmp_path: Path):
    missing_action_a = tmp_path / "missing-action-a"
    missing_action_b = tmp_path / "missing-action-b"
    contexts = TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path,
                task_dir=tmp_path,
                resources=[
                    RelatedResource(
                        role="action",
                        id="missing-a",
                        ref=str(missing_action_a),
                        path=missing_action_a,
                    ),
                    RelatedResource(
                        role="action",
                        id="missing-b",
                        ref=str(missing_action_b),
                        path=missing_action_b,
                    ),
                ],
            )
        ]
    )
    registry = OperationRegistry()
    registry.register(
        OperationSpec(
            id="limited",
            default_label="有限操作",
            target_role="action",
            default_placement=build_default_registry()
            .get("open_action_directory")
            .default_placement,
            default_order=1,
            supports_multiple_resources=False,
            handler=Mock(),
        )
    )
    config = load_task_tools_config(None, registry=registry)

    availability = TaskToolRunner(registry=registry, config=config).availability(
        "limited",
        contexts,
    )

    assert availability.enabled is False
    assert availability.reason == "action 目录不存在"


def test_runner_availability_uses_documented_precedence(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    contexts = _contexts(tmp_path, "action", action)

    default_registry = build_default_registry(directory_opener=Mock())
    default_config = load_task_tools_config(None, registry=default_registry)
    default_config.operations["open_action_directory"].enabled = False
    default_runner = TaskToolRunner(registry=default_registry, config=default_config)

    assert default_runner.availability("unknown", contexts).reason == "未知操作：unknown"
    assert (
        default_runner.availability("open_action_directory", TaskContextSet([])).reason
        == "操作已禁用"
    )

    no_handler_registry = OperationRegistry()
    no_handler_registry.register(
        OperationSpec(
            id="no_handler",
            default_label="无处理器",
            target_role="action",
            default_placement=default_registry.get("open_action_directory").default_placement,
            default_order=1,
        )
    )
    no_handler_config = load_task_tools_config(None, registry=no_handler_registry)
    no_handler_runner = TaskToolRunner(
        registry=no_handler_registry,
        config=no_handler_config,
    )

    assert (
        no_handler_runner.availability("no_handler", TaskContextSet([])).reason
        == "操作尚未绑定处理器"
    )


@pytest.mark.parametrize(
    ("supports_multiple_tasks", "supports_multiple_resources", "contexts_factory", "reason"),
    [
        (
            False,
            True,
            _multiple_task_contexts,
            "该操作不支持多个任务",
        ),
        (
            True,
            False,
            lambda tmp_path: _contexts_with_paths(
                tmp_path,
                "action",
                [tmp_path / "action-a", tmp_path / "action-b"],
            ),
            "该操作不支持多个关联资源",
        ),
    ],
)
def test_runner_rejects_unsupported_cardinality(
    tmp_path: Path,
    supports_multiple_tasks: bool,
    supports_multiple_resources: bool,
    contexts_factory,
    reason: str,
):
    registry = OperationRegistry()
    registry.register(
        OperationSpec(
            id="limited",
            default_label="有限操作",
            target_role="action",
            default_placement=build_default_registry()
            .get("open_action_directory")
            .default_placement,
            default_order=1,
            supports_multiple_tasks=supports_multiple_tasks,
            supports_multiple_resources=supports_multiple_resources,
            handler=Mock(),
        )
    )
    config = load_task_tools_config(None, registry=registry)

    availability = TaskToolRunner(registry=registry, config=config).availability(
        "limited",
        contexts_factory(tmp_path),
    )

    assert availability.enabled is False
    assert availability.reason == reason


def test_explorer_opener_rejects_non_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("tags_machine_core.task_tools.operations.open_directory.sys.platform", "linux")

    with pytest.raises(RuntimeError, match="当前只支持 Windows"):
        open_directory_with_explorer(tmp_path)


def test_explorer_opener_invokes_windows_explorer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    path = tmp_path / "artist"
    path.mkdir()
    popen = Mock()
    monkeypatch.setattr("tags_machine_core.task_tools.operations.open_directory.sys.platform", "win32")
    monkeypatch.setattr(
        "tags_machine_core.task_tools.operations.open_directory.subprocess.Popen",
        popen,
    )

    open_directory_with_explorer(path)

    popen.assert_called_once_with(["explorer.exe", str(path)], close_fds=True)


def test_notification_fallback_writes_chinese_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr("tags_machine_core.task_tools.windows.notifications.sys.platform", "linux")

    show_error("任务工具错误", "无法打开目录")

    assert capsys.readouterr().err == "任务工具错误：无法打开目录\n"


def test_task_tool_file_logging_defaults_to_error(tmp_path: Path):
    logger = configure_task_tool_file_logging(tmp_path / "logs")

    logger.info("not-written")
    logger.error("written")
    for handler in logger.handlers:
        handler.flush()

    text = (tmp_path / "logs" / "task-tools.log").read_text(encoding="utf-8")
    assert "written" in text
    assert "not-written" not in text


def test_runner_logs_operation_start_and_success(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)

    TaskToolRunner(
        registry=registry,
        config=config,
        log_dir=tmp_path / "logs",
        log_level="info",
    ).run("open_action_directory", _contexts(tmp_path, "action", action))

    log_path = tmp_path / "logs" / "task-tools.log"
    text = log_path.read_text(encoding="utf-8")
    assert "开始执行任务工具操作：open_action_directory" in text
    assert "任务工具操作执行成功：open_action_directory" in text


def test_runner_logs_operation_failure(tmp_path: Path):
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)
    runner = TaskToolRunner(
        registry=registry,
        config=config,
        log_dir=tmp_path / "logs",
    )

    with pytest.raises(OperationUnavailableError, match="目录不存在"):
        runner.run("open_artist_directory", _contexts(tmp_path, "artist", tmp_path / "missing"))

    for handler in runner.logger.handlers:
        handler.flush()
    text = (tmp_path / "logs" / "task-tools.log").read_text(encoding="utf-8")
    assert "任务工具操作执行失败：open_artist_directory" in text


def test_task_tool_file_logging_uses_local_app_data_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))

    logger = configure_task_tool_file_logging()
    for handler in logger.handlers:
        handler.flush()

    assert (
        tmp_path / "local-app-data" / "PromptAtelier" / "TaskTools" / "logs" / "task-tools.log"
    ).is_file()
