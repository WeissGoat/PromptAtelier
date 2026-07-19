from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from tags_machine_core.tools.task_tools.config import (
    OperationOverride,
    OperationPlacement,
    TaskToolsConfig,
)
from tags_machine_core.tools.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.tools.task_tools.registry import OperationRegistry, OperationSpec
from tags_machine_core.tools.task_tools.runner import OperationAvailability
from tags_machine_core.tools.task_tools.windows import launcher


@dataclass
class FakeRunner:
    availability_by_id: dict[str, OperationAvailability]

    def __post_init__(self) -> None:
        self.run_calls: list[tuple[str, TaskContextSet]] = []

    def availability(self, operation_id: str, contexts: TaskContextSet) -> OperationAvailability:
        return self.availability_by_id[operation_id]

    def run(self, operation_id: str, contexts: TaskContextSet) -> None:
        self.run_calls.append((operation_id, contexts))


def _contexts(tmp_path: Path, *, artist_exists: bool = True) -> TaskContextSet:
    action_path = tmp_path / "action"
    artist_path = tmp_path / "artist"
    action_path.mkdir()
    if artist_exists:
        artist_path.mkdir()
    return TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path / "input.json",
                task_dir=tmp_path,
                resources=[
                    RelatedResource(role="action", id="Action A", path=action_path),
                    RelatedResource(role="artist", id="Artist A", path=artist_path),
                ],
            )
        ]
    )


def _registry() -> OperationRegistry:
    registry = OperationRegistry()
    for operation_id, placement, order in (
        ("quick-op", OperationPlacement.QUICK, 1),
        ("launcher-op", OperationPlacement.LAUNCHER, 30),
        ("both-op", OperationPlacement.BOTH, 20),
        ("disabled-op", OperationPlacement.BOTH, 40),
    ):
        registry.register(
            OperationSpec(
                id=operation_id,
                default_label=operation_id,
                target_role="action",
                default_placement=placement,
                default_order=order,
                handler=lambda contexts: None,
            )
        )
    return registry


def _config() -> TaskToolsConfig:
    return TaskToolsConfig(
        operations={
            "quick-op": OperationOverride(),
            "launcher-op": OperationOverride(label="自定义操作", order=10),
            "both-op": OperationOverride(),
            "disabled-op": OperationOverride(enabled=False),
        }
    )


def test_build_launcher_items_filters_and_sorts_operations(tmp_path: Path) -> None:
    registry = _registry()
    runner = FakeRunner(
        {
            operation_id: OperationAvailability(True)
            for operation_id in ("launcher-op", "both-op")
        }
    )

    items = launcher.build_launcher_items(
        contexts=_contexts(tmp_path),
        registry=registry,
        config=_config(),
        runner=runner,
    )

    assert [(item.operation_id, item.label, item.order) for item in items] == [
        ("launcher-op", "自定义操作", 10),
        ("both-op", "both-op", 20),
    ]


def test_build_launcher_items_keeps_missing_resource_disabled_with_reason(tmp_path: Path) -> None:
    registry = _registry()
    runner = FakeRunner(
        {
            "launcher-op": OperationAvailability(False, "Action 目录不存在"),
            "both-op": OperationAvailability(True),
        }
    )

    items = launcher.build_launcher_items(
        contexts=_contexts(tmp_path, artist_exists=False),
        registry=registry,
        config=_config(),
        runner=runner,
    )

    missing = next(item for item in items if item.operation_id == "launcher-op")
    assert not missing.enabled
    assert missing.disabled_reason == "Action 目录不存在"


def test_launcher_view_model_contains_task_and_resource_summary(tmp_path: Path) -> None:
    contexts = _contexts(tmp_path, artist_exists=False)
    registry = _registry()
    runner = FakeRunner(
        {
            "launcher-op": OperationAvailability(True),
            "both-op": OperationAvailability(True),
        }
    )

    model = launcher.build_launcher_view_model(
        contexts=contexts,
        registry=registry,
        config=_config(),
        runner=runner,
    )

    assert model.task_count == 1
    assert model.input_paths == (str(tmp_path / "input.json"),)
    assert model.action_resources[0].name == "Action A"
    assert model.action_resources[0].path == str(tmp_path / "action")
    assert model.artist_resources[0].exists is False


def test_launcher_resource_summary_prefers_existing_path_for_same_artist(
    tmp_path: Path,
) -> None:
    artist_path = tmp_path / "artist"
    artist_path.mkdir()
    contexts = TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path,
                task_dir=tmp_path,
                resources=[
                    RelatedResource(
                        role="artist",
                        id="artist-a",
                        ref="artist-a",
                    ),
                    RelatedResource(
                        role="artist",
                        id="artist-a",
                        ref="artist-a",
                        path=artist_path,
                    ),
                ],
            )
        ]
    )

    resources = launcher._build_resource_items(contexts, "artist")

    assert [(item.name, item.path, item.exists) for item in resources] == [
        ("artist-a", str(artist_path), True)
    ]


class FakeWidget:
    def __init__(self, parent=None, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.grid_calls: list[dict[str, object]] = []

    def grid(self, **kwargs):
        self.grid_calls.append(kwargs)


class FakeButton(FakeWidget):
    instances: list["FakeButton"] = []

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.command = kwargs["command"]
        self.states: list[tuple[str, ...]] = []
        self.__class__.instances.append(self)

    def state(self, value: tuple[str, ...]) -> None:
        self.states.append(value)


class FakeWindow:
    def __init__(self):
        self.title_value = ""
        self.mainloop_calls = 0

    def title(self, value: str) -> None:
        self.title_value = value

    def resizable(self, width: bool, height: bool) -> None:
        assert (width, height) == (False, False)

    def mainloop(self) -> None:
        self.mainloop_calls += 1


def test_window_buttons_delegate_to_runner_and_stay_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    contexts = _contexts(tmp_path)
    runner = FakeRunner(
        {
            "launcher-op": OperationAvailability(True),
            "both-op": OperationAvailability(False, "资源缺失"),
        }
    )
    window = FakeWindow()
    FakeButton.instances.clear()
    monkeypatch.setattr(launcher.tk, "Tk", lambda: window)
    monkeypatch.setattr(
        launcher.ttk,
        "Frame",
        lambda parent, **kwargs: FakeWidget(parent, **kwargs),
    )
    monkeypatch.setattr(
        launcher.ttk,
        "LabelFrame",
        lambda parent, **kwargs: FakeWidget(parent, **kwargs),
    )
    monkeypatch.setattr(
        launcher.ttk,
        "Label",
        lambda parent, **kwargs: FakeWidget(parent, **kwargs),
    )
    monkeypatch.setattr(launcher.ttk, "Button", FakeButton)

    result = launcher.launch_task_tools_window(
        contexts=contexts,
        registry=_registry(),
        config=_config(),
        runner=runner,
    )

    assert result == 0
    assert window.title_value == "Refactor 任务工具"
    assert window.mainloop_calls == 1
    assert [button.kwargs["text"] for button in FakeButton.instances] == [
        "自定义操作",
        "both-op",
    ]
    assert FakeButton.instances[1].states == [("disabled",)]
    FakeButton.instances[0].command()
    assert runner.run_calls == [("launcher-op", contexts)]


def test_launcher_shows_runner_error_without_closing_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    contexts = _contexts(tmp_path)

    class ErrorRunner(FakeRunner):
        def run(self, operation_id: str, contexts: TaskContextSet) -> None:
            raise RuntimeError("执行失败")

    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda title, message, parent: errors.append((title, message)),
    )
    launcher._run_launcher_item(
        item=launcher.LauncherItem("launcher-op", "打开目录", 1, True),
        contexts=contexts,
        runner=ErrorRunner({}),
        parent=SimpleNamespace(),
    )

    assert errors == [("任务工具错误", "执行“打开目录”失败：执行失败")]
