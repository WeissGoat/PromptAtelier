# Windows Task Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 refactor 增加可持久化的 Windows SendTo 任务工具，默认支持从真实任务归档打开 Action 和 Artist 目录，并允许通过配置决定操作显示在高频快捷项、统一工具窗口或两者中。

**Architecture:** 新增独立的 `tags_machine_core.tools.task_tools` 应用层模块。`TaskArchiveResolver` 只负责把 Explorer 输入解析为 `TaskContextSet`，`OperationRegistry` 只负责注册操作，Runner 和 Tkinter Launcher 复用同一套操作定义；Windows 安装器只管理 LocalAppData 启动器和自己创建的 SendTo 项。现有 Composer、Policy、Renderer、Client 和 Batch 链路不做行为修改。

**Tech Stack:** Python 3.11、Pydantic 2、PyYAML、标准库 `argparse/json/pathlib/subprocess/tkinter/ctypes`、Windows PowerShell、VBScript SendTo 薄入口、pytest/unittest、Ruff。

## Global Constraints

- 只在 `refactor` 子模块开发；不修改旧 `tags_machine` 的 SendTo 脚本和 `F:\ThreeState`。
- 注释和面向用户的错误提示使用中文；代码标识符保持英文。
- 第一阶段只实现 `open_action_directory` 和 `open_artist_directory` 两个有用操作。
- 配置不能指定任意 Python、PowerShell 或可执行文件；Handler 必须由代码注册。
- 不从任务目录名猜节点，不递归扫描 `design`，不按同名节点自动纠错。
- 正常快捷操作不弹控制台；失败必须有明确 Windows 消息框或统一窗口错误。
- 安装器只删除安装清单记录的文件，不按通配符清理用户 SendTo 内容。
- 默认日志级别为 `error`，日志写入 `%LOCALAPPDATA%\PromptAtelier\TaskTools\logs`。
- 业务验收使用 `G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f`，并实际打开 Action、Artist 目录。
- 不为本功能修改 AgentComposer、PromptPolicyPipeline、生图参数或 NovelAI 请求。

---

## File Structure

创建以下模块：

```text
src/tags_machine_core/tools/task_tools/
  __init__.py              # 导出公共运行时接口
  cli.py                   # task-tools 子命令及根 CLI 接线
  config.py                # 配置模型、默认配置、配置覆盖
  logging.py               # LocalAppData 文件日志
  models.py                # RelatedResource、TaskContext、TaskContextSet
  resolver.py              # 任务目录定位和归档解析
  registry.py              # OperationSpec、OperationRegistry、默认操作注册
  runner.py                # 快捷操作和 Launcher 共用的执行编排
  operations/
    __init__.py
    open_directory.py      # 打开关联节点目录
  windows/
    __init__.py
    launcher.py            # Tkinter 统一工具窗口
    notifications.py       # Windows 消息框
    paths.py               # SendTo、LocalAppData、日志目录定位
    sendto_installer.py    # install/sync/uninstall
    bootstrap.ps1          # LocalAppData 稳定启动器模板
    sendto_entry.vbs       # SendTo 无终端入口模板

configs/task_tools.example.yaml
docs/task_tools_readme.md
scripts/install_task_tools.ps1

tests/
  test_task_tools_config.py
  test_task_tools_resolver.py
  test_task_tools_runner.py
  test_task_tools_launcher.py
  test_task_tools_sendto.py
  test_task_tools_cli.py
```

修改：

```text
src/tags_machine_core/cli.py
```

---

### Task 1: Runtime Models, Configuration, and Operation Registry

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/__init__.py`
- Create: `src/tags_machine_core/tools/task_tools/models.py`
- Create: `src/tags_machine_core/tools/task_tools/config.py`
- Create: `src/tags_machine_core/tools/task_tools/registry.py`
- Create: `tests/test_task_tools_config.py`

**Interfaces:**
- Produces: `RelatedResource`, `TaskContext`, `TaskContextSet`.
- Produces: `OperationPlacement`, `OperationOverride`, `TaskToolsConfig`, `load_task_tools_config()`.
- Produces: `OperationSpec`, `OperationRegistry`, `build_default_registry()`.
- Later tasks consume these exact names; do not add archive parsing or Windows calls in this task.

- [ ] **Step 1: Write configuration and runtime model tests**

```python
from pathlib import Path

import pytest

from tags_machine_core.tools.task_tools.config import (
    OperationPlacement,
    load_task_tools_config,
)
from tags_machine_core.tools.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.tools.task_tools.registry import build_default_registry


def test_default_registry_contains_only_first_phase_operations():
    registry = build_default_registry()

    assert registry.ids() == ["open_action_directory", "open_artist_directory"]
    assert registry.get("open_action_directory").target_role == "action"
    assert registry.get("open_artist_directory").target_role == "artist"


def test_config_can_place_operations_independently(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text(
        """
schema: prompt-atelier.task-tools/v1
operations:
  open_action_directory:
    enabled: true
    placement: quick
    order: 25
  open_artist_directory:
    enabled: true
    placement: launcher
""".strip(),
        encoding="utf-8",
    )

    config = load_task_tools_config(path, registry=build_default_registry())

    assert config.operations["open_action_directory"].placement is OperationPlacement.QUICK
    assert config.operations["open_action_directory"].order == 25
    assert config.operations["open_artist_directory"].placement is OperationPlacement.LAUNCHER


def test_unknown_operation_id_is_rejected(tmp_path: Path):
    path = tmp_path / "task_tools.yaml"
    path.write_text(
        "schema: prompt-atelier.task-tools/v1\noperations:\n  misspelled_action:\n    enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未知的任务工具操作：misspelled_action"):
        load_task_tools_config(path, registry=build_default_registry())


def test_context_set_deduplicates_paths_without_losing_order(tmp_path: Path):
    shared = tmp_path / "artist"
    first = TaskContext(
        input_path=tmp_path / "a.png",
        task_dir=tmp_path / "task-a",
        resources=[RelatedResource(role="artist", id="a", ref=str(shared), path=shared)],
    )
    second = TaskContext(
        input_path=tmp_path / "b.png",
        task_dir=tmp_path / "task-b",
        resources=[RelatedResource(role="artist", id="a", ref=str(shared), path=shared)],
    )

    contexts = TaskContextSet(tasks=[first, second])

    assert contexts.existing_paths("artist") == [shared]
```

- [ ] **Step 2: Run the focused tests and confirm the module is missing**

Run:

```powershell
uv run pytest tests/test_task_tools_config.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'tags_machine_core.tools.task_tools'`.

- [ ] **Step 3: Implement runtime models**

Implement `models.py` with these public signatures:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class RelatedResource:
    role: str
    id: str | None = None
    ref: str | None = None
    path: Path | None = None
    index: int = 0
    exists: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if self.path is not None:
            object.__setattr__(self, "path", self.path.resolve())
            object.__setattr__(self, "exists", self.path.is_dir())


@dataclass(slots=True)
class TaskContext:
    input_path: Path
    task_dir: Path
    archive_files: dict[str, Path] = field(default_factory=dict)
    resources: list[RelatedResource] = field(default_factory=list)
    render_request: dict[str, Any] | None = None
    prompt_bundle: dict[str, Any] | None = None
    generation_result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def resources_for(self, role: str) -> list[RelatedResource]:
        return [resource for resource in self.resources if resource.role == role]


@dataclass(slots=True)
class TaskContextSet:
    tasks: list[TaskContext]

    def resources_for(self, role: str) -> list[RelatedResource]:
        return [
            resource
            for task in self.tasks
            for resource in task.resources_for(role)
        ]

    def existing_paths(self, role: str) -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for resource in self.resources_for(role):
            if resource.path is None or not resource.exists:
                continue
            key = str(resource.path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(resource.path.resolve())
        return result
```

Deduplication uses normalized absolute path strings with `casefold()` on Windows while preserving first-seen order.

- [ ] **Step 4: Implement configuration and registry**

Implement `config.py` with Pydantic models:

```python
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperationPlacement(StrEnum):
    QUICK = "quick"
    LAUNCHER = "launcher"
    BOTH = "both"


class OperationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    placement: OperationPlacement | None = None
    label: str | None = None
    order: int | None = None


class TaskToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["prompt-atelier.task-tools/v1"] = Field(
        default="prompt-atelier.task-tools/v1",
        validation_alias="schema",
        serialization_alias="schema",
    )
    log_level: Literal["trace", "info", "warning", "error"] = "error"
    operations: dict[str, OperationOverride] = Field(default_factory=dict)


def load_task_tools_config(
    path: Path | None,
    *,
    registry: "OperationRegistry",
) -> TaskToolsConfig:
    data: dict[str, object] = {}
    if path is not None:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Task tool config must be a mapping: {path}")
        data = loaded
    config = TaskToolsConfig.model_validate(data)
    unknown = sorted(set(config.operations) - set(registry.ids()))
    if unknown:
        raise ValueError(f"Unknown task tool operation: {unknown[0]}")
    for spec in registry.all():
        override = config.operations.setdefault(spec.id, OperationOverride())
        if override.placement is None:
            override.placement = spec.default_placement
        if override.order is None:
            override.order = spec.default_order
        if override.label is None:
            override.label = spec.default_label
    return config
```

Implement `registry.py`:

```python
from dataclasses import dataclass
from typing import Protocol


class OperationHandler(Protocol):
    def __call__(self, contexts: TaskContextSet) -> "OperationResult":
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class OperationSpec:
    id: str
    default_label: str
    target_role: str
    default_placement: OperationPlacement
    default_order: int
    supports_multiple_tasks: bool = True
    supports_multiple_resources: bool = True
    handler: OperationHandler | None = None


class OperationRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"Duplicate task tool operation: {spec.id}")
        self._specs[spec.id] = spec

    def get(self, operation_id: str) -> OperationSpec:
        try:
            return self._specs[operation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown task tool operation: {operation_id}") from exc

    def all(self) -> list[OperationSpec]:
        return list(self._specs.values())

    def ids(self) -> list[str]:
        return list(self._specs)


def build_default_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(
        OperationSpec(
            id="open_action_directory",
            default_label="打开 Action 目录",
            target_role="action",
            default_placement=OperationPlacement.BOTH,
            default_order=10,
        )
    )
    registry.register(
        OperationSpec(
            id="open_artist_directory",
            default_label="打开 Artist 目录",
            target_role="artist",
            default_placement=OperationPlacement.BOTH,
            default_order=20,
        )
    )
    return registry
```

Task 1 registers metadata only; Task 3 injects actual handlers.

- [ ] **Step 5: Run tests and lint**

Run:

```powershell
uv run pytest tests/test_task_tools_config.py -q
uv run ruff check src/tags_machine_core/tools/task_tools tests/test_task_tools_config.py
```

Expected: all tests pass and Ruff exits `0`.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src/tags_machine_core/tools/task_tools tests/test_task_tools_config.py
git commit -m "feat: add task tool runtime models"
```

---

### Task 2: Task Archive Resolver

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/resolver.py`
- Create: `tests/test_task_tools_resolver.py`

**Interfaces:**
- Consumes: `RelatedResource`, `TaskContext`, `TaskContextSet` from Task 1.
- Produces: `TaskArchiveResolver.resolve(inputs) -> TaskContextSet`.
- Produces: `TaskArchiveNotFoundError`, `TaskArchiveReadError`.
- The resolver returns dictionaries parsed with `json.loads`; it does not require current Pydantic contract versions to accept older archives.

- [ ] **Step 1: Write resolver tests using realistic archive shapes**

```python
import json
from pathlib import Path

import pytest

from tags_machine_core.tools.task_tools.resolver import (
    TaskArchiveNotFoundError,
    TaskArchiveResolver,
)


def _write_task(task_dir: Path, *, action: Path, artist: Path) -> Path:
    task_dir.mkdir(parents=True)
    image = task_dir / "generated.png"
    image.write_bytes(b"png")
    (task_dir / "render_request.json").write_text(
        json.dumps(
            {
                "schema": "tags-machine-core.render-request/v1",
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "00_start_侧脸回眸",
                            "ref": str(action),
                            "index": 0,
                        }
                    ]
                },
                "artist_payload": {
                    "artist_ref": "114425243_Soft_Akipeco_Official",
                    "path": str(artist),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return image


def test_resolver_reads_action_and_artist_from_render_request(tmp_path: Path):
    action = tmp_path / "design" / "动作改2" / "00_start_侧脸回眸"
    artist = tmp_path / "design" / "画风" / "114425243_Soft_Akipeco_Official"
    action.mkdir(parents=True)
    artist.mkdir(parents=True)
    image = _write_task(tmp_path / "output" / "task", action=action, artist=artist)

    contexts = TaskArchiveResolver().resolve([image])

    assert contexts.tasks[0].task_dir == image.parent.resolve()
    assert contexts.existing_paths("action") == [action.resolve()]
    assert contexts.existing_paths("artist") == [artist.resolve()]


def test_resolver_uses_nearest_parent_archive(tmp_path: Path):
    task = tmp_path / "day" / "task"
    action = tmp_path / "action"
    artist = tmp_path / "artist"
    action.mkdir()
    artist.mkdir()
    _write_task(task, action=action, artist=artist)
    nested = task / "nested"
    nested.mkdir()
    selected = nested / "note.json"
    selected.write_text("{}", encoding="utf-8")

    contexts = TaskArchiveResolver().resolve([selected])

    assert contexts.tasks[0].task_dir == task.resolve()


def test_resolver_preserves_missing_resource_with_exists_false(tmp_path: Path):
    missing_action = tmp_path / "missing-action"
    missing_artist = tmp_path / "missing-artist"
    image = _write_task(tmp_path / "task", action=missing_action, artist=missing_artist)

    contexts = TaskArchiveResolver().resolve([image])

    action = contexts.tasks[0].resources_for("action")[0]
    assert action.path == missing_action.resolve()
    assert action.exists is False


def test_resolver_does_not_scan_child_directories(tmp_path: Path):
    selected = tmp_path / "day"
    selected.mkdir()
    nested = selected / "task"
    nested.mkdir()
    (nested / "render_request.json").write_text("{}", encoding="utf-8")

    with pytest.raises(TaskArchiveNotFoundError):
        TaskArchiveResolver().resolve([selected])
```

- [ ] **Step 2: Run resolver tests and confirm failure**

```powershell
uv run pytest tests/test_task_tools_resolver.py -q
```

Expected: import fails because `resolver.py` does not exist.

- [ ] **Step 3: Implement archive location and JSON loading**

Implement these signatures:

```python
class TaskArchiveError(RuntimeError):
    """任务归档定位或读取失败。"""


class TaskArchiveNotFoundError(TaskArchiveError):
    """输入路径向上找不到受支持的任务归档。"""


class TaskArchiveReadError(TaskArchiveError):
    """任务归档存在但无法按 UTF-8 JSON 对象读取。"""


class TaskArchiveResolver:
    archive_names = (
        "render_request.json",
        "prompt_bundle.json",
        "generation_result.json",
    )

    def resolve(self, inputs: Sequence[str | Path]) -> TaskContextSet:
        tasks: list[TaskContext] = []
        seen: set[str] = set()
        for value in inputs:
            context = self.resolve_one(value)
            key = str(context.task_dir).casefold()
            if key in seen:
                continue
            seen.add(key)
            tasks.append(context)
        if not tasks:
            raise TaskArchiveNotFoundError("没有收到可解析的任务路径")
        return TaskContextSet(tasks=tasks)

    def resolve_one(self, input_path: str | Path) -> TaskContext:
        selected = Path(input_path).resolve(strict=True)
        task_dir = self.find_task_dir(selected)
        archive_files = {
            name: task_dir / name
            for name in self.archive_names
            if (task_dir / name).is_file()
        }
        loaded = {name: _read_json(path) for name, path in archive_files.items()}
        render_request = loaded.get("render_request.json")
        prompt_bundle = loaded.get("prompt_bundle.json")
        resources = _merge_resources(
            _resources_from_render_request(render_request or {}),
            _resources_from_prompt_bundle(prompt_bundle or {}),
        )
        return TaskContext(
            input_path=selected,
            task_dir=task_dir,
            archive_files=archive_files,
            resources=resources,
            render_request=render_request,
            prompt_bundle=prompt_bundle,
            generation_result=loaded.get("generation_result.json"),
        )

    def find_task_dir(self, input_path: str | Path) -> Path:
        selected = Path(input_path).resolve(strict=True)
        start = selected if selected.is_dir() else selected.parent
        for candidate in (start, *start.parents):
            if any((candidate / name).is_file() for name in self.archive_names):
                return candidate
        raise TaskArchiveNotFoundError(f"找不到任务归档目录：{selected}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskArchiveReadError(f"无法读取任务归档：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TaskArchiveReadError(f"任务归档顶层必须是对象：{path}")
    return value
```

Use `Path.resolve(strict=True)` for the selected input. Search only the input directory and its parents. Read JSON with `Path.read_text(encoding="utf-8")` and `json.loads`; reject non-object top-level JSON with `TaskArchiveReadError`.

- [ ] **Step 4: Implement resource extraction and fallback**

Extraction rules:

```python
def _resources_from_render_request(data: dict[str, Any]) -> list[RelatedResource]:
    resources: list[RelatedResource] = []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    node_refs = meta.get("node_refs") if isinstance(meta.get("node_refs"), list) else []
    for fallback_index, item in enumerate(node_refs):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        ref = str(item.get("ref") or "").strip() or None
        path = Path(ref) if ref and Path(ref).is_absolute() else None
        resources.append(
            RelatedResource(
                role=role,
                id=str(item.get("id") or "").strip() or None,
                ref=ref,
                path=path,
                index=int(item.get("index", fallback_index)),
                source="render_request.meta.node_refs",
            )
        )
    artist = data.get("artist_payload") if isinstance(data.get("artist_payload"), dict) else {}
    artist_path = str(artist.get("path") or "").strip()
    if artist_path:
        resources.append(
            RelatedResource(
                role="artist",
                id=str(artist.get("artist_ref") or "").strip() or None,
                ref=str(artist.get("artist_ref") or "").strip() or None,
                path=Path(artist_path),
                source="render_request.artist_payload.path",
            )
        )
    return resources


def _resources_from_prompt_bundle(data: dict[str, Any]) -> list[RelatedResource]:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    nodes = meta.get("nodes") if isinstance(meta.get("nodes"), list) else []
    resources: list[RelatedResource] = []
    for fallback_index, item in enumerate(nodes):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        ref = str(item.get("ref") or "").strip() or None
        path = Path(ref) if ref and Path(ref).is_absolute() else None
        resources.append(
            RelatedResource(
                role=role,
                id=str(item.get("id") or "").strip() or None,
                ref=ref,
                path=path,
                index=int(item.get("index", fallback_index)),
                source="prompt_bundle.meta.nodes",
            )
        )
    return resources


def _merge_resources(*groups: list[RelatedResource]) -> list[RelatedResource]:
    merged: dict[tuple[str, int, str], RelatedResource] = {}
    order: list[tuple[str, int, str]] = []
    for group in groups:
        for resource in group:
            identity = str(resource.id or resource.ref or resource.path or "").casefold()
            key = (resource.role, resource.index, identity)
            previous = merged.get(key)
            if previous is None:
                order.append(key)
                merged[key] = resource
            elif previous.path is None and resource.path is not None:
                merged[key] = resource
    return [merged[key] for key in order]
```

Merge resources by `(role, index, normalized ref/path)` while preferring records with an absolute path. Do not turn a plain Artist id such as `20260412` into a guessed design path.

- [ ] **Step 5: Run resolver regression tests**

```powershell
uv run pytest tests/test_task_tools_resolver.py tests/test_task_tools_config.py -q
uv run ruff check src/tags_machine_core/tools/task_tools tests/test_task_tools_resolver.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add src/tags_machine_core/tools/task_tools/resolver.py tests/test_task_tools_resolver.py
git commit -m "feat: resolve task archive resources"
```

---

### Task 3: Operation Runner and Open Directory Handlers

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/operations/__init__.py`
- Create: `src/tags_machine_core/tools/task_tools/operations/open_directory.py`
- Create: `src/tags_machine_core/tools/task_tools/logging.py`
- Create: `src/tags_machine_core/tools/task_tools/runner.py`
- Create: `src/tags_machine_core/tools/task_tools/windows/__init__.py`
- Create: `src/tags_machine_core/tools/task_tools/windows/notifications.py`
- Create: `tests/test_task_tools_runner.py`
- Modify: `src/tags_machine_core/tools/task_tools/registry.py`

**Interfaces:**
- Consumes: `TaskArchiveResolver`, `TaskContextSet`, `TaskToolsConfig`, `OperationRegistry`.
- Produces: `OperationResult`, `OperationAvailability`, `TaskToolRunner`.
- Produces: `open_related_directories(contexts, role, opener)`.
- Produces: `configure_task_tool_file_logging(log_dir, level)`.
- Default registry now binds handlers for Action and Artist.

- [ ] **Step 1: Write operation and runner tests**

```python
from pathlib import Path
from unittest.mock import Mock

import pytest

from tags_machine_core.tools.task_tools.config import load_task_tools_config
from tags_machine_core.tools.task_tools.logging import configure_task_tool_file_logging
from tags_machine_core.tools.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.tools.task_tools.registry import build_default_registry
from tags_machine_core.tools.task_tools.runner import OperationUnavailableError, TaskToolRunner


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


def test_runner_explains_missing_artist_path(tmp_path: Path):
    missing = tmp_path / "missing"
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)
    contexts = _contexts(tmp_path, "artist", missing)

    availability = TaskToolRunner(registry=registry, config=config).availability(
        "open_artist_directory",
        contexts,
    )

    assert availability.enabled is False
    assert "目录不存在" in availability.reason


def test_task_tool_file_logging_defaults_to_error(tmp_path: Path):
    logger = configure_task_tool_file_logging(tmp_path / "logs", "error")

    logger.info("not-written")
    logger.error("written")
    for handler in logger.handlers:
        handler.flush()

    text = (tmp_path / "logs" / "task-tools.log").read_text(encoding="utf-8")
    assert "written" in text
    assert "not-written" not in text
```

- [ ] **Step 2: Run tests and confirm missing implementation**

```powershell
uv run pytest tests/test_task_tools_runner.py -q
```

Expected: import failure for `runner`.

- [ ] **Step 3: Implement open directory operation**

```python
from pathlib import Path
from typing import Callable

from tags_machine_core.tools.task_tools.models import TaskContextSet


DirectoryOpener = Callable[[Path], None]


def open_directory_with_explorer(path: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("打开关联目录当前只支持 Windows")
    subprocess.Popen(["explorer.exe", str(path)], close_fds=True)


def open_related_directories(
    contexts: TaskContextSet,
    *,
    role: str,
    opener: DirectoryOpener = open_directory_with_explorer,
) -> OperationResult:
    paths = contexts.existing_paths(role)
    if not paths:
        raise OperationUnavailableError(f"没有可用的 {role} 目录")
    for path in paths:
        opener(path)
    return OperationResult(operation_id=f"open_{role}_directory", affected_paths=paths)
```

- [ ] **Step 4: Implement runner and availability checks**

Public signatures:

```python
@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    affected_paths: list[Path] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True, slots=True)
class OperationAvailability:
    enabled: bool
    reason: str = ""


class OperationUnavailableError(RuntimeError):
    """操作存在但不适用于当前任务上下文。"""


class TaskToolRunner:
    def __init__(self, *, registry: OperationRegistry, config: TaskToolsConfig):
        self.registry = registry
        self.config = config

    def availability(
        self,
        operation_id: str,
        contexts: TaskContextSet,
    ) -> OperationAvailability:
        try:
            spec = self.registry.get(operation_id)
        except KeyError:
            return OperationAvailability(False, f"未知操作：{operation_id}")
        override = self.config.operations[operation_id]
        if not override.enabled:
            return OperationAvailability(False, "操作已禁用")
        if spec.handler is None:
            return OperationAvailability(False, "操作尚未绑定 Handler")
        resources = contexts.resources_for(spec.target_role)
        if not resources:
            return OperationAvailability(False, f"未找到 {spec.target_role} 关联资源")
        if not any(resource.exists for resource in resources):
            return OperationAvailability(False, f"{spec.target_role} 目录不存在")
        if not spec.supports_multiple_tasks and len(contexts.tasks) > 1:
            return OperationAvailability(False, "该操作不支持多个任务")
        if not spec.supports_multiple_resources and len(contexts.existing_paths(spec.target_role)) > 1:
            return OperationAvailability(False, "该操作不支持多个关联资源")
        return OperationAvailability(True)

    def run(self, operation_id: str, contexts: TaskContextSet) -> OperationResult:
        availability = self.availability(operation_id, contexts)
        if not availability.enabled:
            raise OperationUnavailableError(availability.reason)
        handler = self.registry.get(operation_id).handler
        if handler is None:
            raise OperationUnavailableError("操作尚未绑定 Handler")
        return handler(contexts)
```

Availability checks order: operation exists, enabled, handler exists, target resources exist, cardinality supported.

Modify `build_default_registry()` to accept `directory_opener: DirectoryOpener = open_directory_with_explorer`. Bind `open_action_directory` with `functools.partial(open_related_directories, role="action", opener=directory_opener)` and bind `open_artist_directory` with the same call using `role="artist"`.

- [ ] **Step 5: Implement Windows error notification**

Use standard-library `ctypes` without requiring Tk root:

```python
def show_error(title: str, message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        return
    print(f"{title}: {message}", file=sys.stderr)
```

- [ ] **Step 6: Implement LocalAppData file logging**

```python
from logging.handlers import RotatingFileHandler

from tags_machine_core.logging_config import normalize_log_level


def configure_task_tool_file_logging(log_dir: Path, level: str = "error") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tags_machine_core.tools.task_tools")
    level_number = normalize_log_level(level)
    logger.setLevel(level_number)
    logger.propagate = False
    target = (log_dir / "task-tools.log").resolve()
    for handler in logger.handlers:
        if getattr(handler, "task_tools_target", None) == target:
            handler.setLevel(level_number)
            return logger
    handler = RotatingFileHandler(
        target,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.task_tools_target = target
    handler.setLevel(level_number)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger
```

CLI、Launcher 和 Installer 在执行前调用该函数。快捷入口捕获异常时使用 `logger.exception()`，成功打开目录使用 `logger.info()`。

- [ ] **Step 7: Run tests and lint**

```powershell
uv run pytest tests/test_task_tools_runner.py tests/test_task_tools_resolver.py -q
uv run ruff check src/tags_machine_core/tools/task_tools tests/test_task_tools_runner.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```powershell
git add src/tags_machine_core/tools/task_tools tests/test_task_tools_runner.py
git commit -m "feat: execute task tool operations"
```

---

### Task 4: Config-Driven Tkinter Launcher

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/windows/launcher.py`
- Create: `tests/test_task_tools_launcher.py`

**Interfaces:**
- Consumes: `TaskContextSet`, `OperationRegistry`, `TaskToolsConfig`, `TaskToolRunner`.
- Produces: `LauncherItem`, `build_launcher_items()`, `launch_task_tools_window()`.
- UI code consumes a testable view model; tests do not require a display server.

- [ ] **Step 1: Write launcher view-model tests**

```python
from pathlib import Path
from unittest.mock import Mock

from tags_machine_core.tools.task_tools.config import OperationPlacement, load_task_tools_config
from tags_machine_core.tools.task_tools.models import RelatedResource, TaskContext, TaskContextSet
from tags_machine_core.tools.task_tools.registry import build_default_registry
from tags_machine_core.tools.task_tools.runner import TaskToolRunner
from tags_machine_core.tools.task_tools.windows.launcher import build_launcher_items


def test_launcher_only_lists_launcher_and_both_operations(tmp_path: Path):
    action = tmp_path / "action"
    artist = tmp_path / "artist"
    action.mkdir()
    artist.mkdir()
    contexts = TaskContextSet(
        tasks=[
            TaskContext(
                input_path=tmp_path,
                task_dir=tmp_path,
                resources=[
                    RelatedResource(role="action", path=action),
                    RelatedResource(role="artist", path=artist),
                ],
            )
        ]
    )
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)
    config.operations["open_action_directory"].placement = OperationPlacement.QUICK
    config.operations["open_artist_directory"].placement = OperationPlacement.LAUNCHER

    items = build_launcher_items(
        contexts=contexts,
        registry=registry,
        config=config,
        runner=TaskToolRunner(registry=registry, config=config),
    )

    assert [item.operation_id for item in items] == ["open_artist_directory"]


def test_launcher_disables_operation_with_visible_reason(tmp_path: Path):
    registry = build_default_registry(directory_opener=Mock())
    config = load_task_tools_config(None, registry=registry)
    contexts = TaskContextSet(
        tasks=[TaskContext(input_path=tmp_path, task_dir=tmp_path)]
    )

    items = build_launcher_items(
        contexts=contexts,
        registry=registry,
        config=config,
        runner=TaskToolRunner(registry=registry, config=config),
    )

    assert items[0].enabled is False
    assert "未找到" in items[0].disabled_reason
```

- [ ] **Step 2: Run tests and confirm launcher module is missing**

```powershell
uv run pytest tests/test_task_tools_launcher.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement the launcher view model**

```python
@dataclass(frozen=True, slots=True)
class LauncherItem:
    operation_id: str
    label: str
    order: int
    enabled: bool
    disabled_reason: str = ""


def build_launcher_items(
    *,
    contexts: TaskContextSet,
    registry: OperationRegistry,
    config: TaskToolsConfig,
    runner: TaskToolRunner,
) -> list[LauncherItem]:
    items: list[LauncherItem] = []
    for spec in registry.all():
        override = config.operations[spec.id]
        if not override.enabled:
            continue
        if override.placement not in {OperationPlacement.LAUNCHER, OperationPlacement.BOTH}:
            continue
        availability = runner.availability(spec.id, contexts)
        items.append(
            LauncherItem(
                operation_id=spec.id,
                label=override.label or spec.default_label,
                order=override.order if override.order is not None else spec.default_order,
                enabled=availability.enabled,
                disabled_reason=availability.reason,
            )
        )
    return sorted(items, key=lambda item: (item.order, item.operation_id))
```

Only include effective placement `launcher` or `both`; sort by `order`, then operation id.

- [ ] **Step 4: Implement the Tkinter window**

```python
def launch_task_tools_window(
    *,
    contexts: TaskContextSet,
    registry: OperationRegistry,
    config: TaskToolsConfig,
    runner: TaskToolRunner,
) -> int:
    root = tkinter.Tk()
    root.title("Refactor 任务工具")
    root.minsize(560, 320)
    frame = ttk.Frame(root, padding=16)
    frame.grid(sticky="nsew")
    ttk.Label(frame, text=f"已选择 {len(contexts.tasks)} 个任务").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
    )

    row = 1
    for role in ("action", "artist"):
        resources = contexts.resources_for(role)
        summary = "未找到"
        if resources:
            summary = "；".join(
                f"{resource.id or resource.ref or role}：{resource.path or '无路径'}"
                + ("" if resource.exists else "（目录不存在）")
                for resource in resources
            )
        ttk.Label(frame, text=role.capitalize()).grid(row=row, column=0, sticky="nw")
        ttk.Label(frame, text=summary, wraplength=430).grid(row=row, column=1, sticky="w")
        row += 1

    def execute(operation_id: str) -> None:
        try:
            runner.run(operation_id, contexts)
        except Exception as exc:
            messagebox.showerror("Refactor 任务工具", str(exc), parent=root)

    for item in build_launcher_items(
        contexts=contexts,
        registry=registry,
        config=config,
        runner=runner,
    ):
        button = ttk.Button(
            frame,
            text=item.label,
            command=lambda operation_id=item.operation_id: execute(operation_id),
        )
        button.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        if not item.enabled:
            button.state(["disabled"])
        ttk.Label(frame, text=item.disabled_reason).grid(row=row, column=1, sticky="w")
        row += 1

    root.mainloop()
    return 0
```

Window requirements:

- Title: `Refactor 任务工具`.
- Show task count and selected input summary.
- Show Action and Artist names, path, and missing status.
- Render one button per LauncherItem.
- Disabled operations use disabled buttons and an adjacent reason label.
- Clicking a successful open-directory operation keeps the window open.
- Handler exceptions show `tkinter.messagebox.showerror()` and write an error log.
- No nested cards or decorative UI; use a compact native Windows utility layout.

- [ ] **Step 5: Run view-model tests and import the GUI module**

```powershell
uv run pytest tests/test_task_tools_launcher.py -q
uv run python -c "from tags_machine_core.tools.task_tools.windows.launcher import launch_task_tools_window; print(launch_task_tools_window.__name__)"
uv run ruff check src/tags_machine_core/tools/task_tools/windows/launcher.py tests/test_task_tools_launcher.py
```

Expected: tests pass; import command prints `launch_task_tools_window` without opening a window.

- [ ] **Step 6: Commit Task 4**

```powershell
git add src/tags_machine_core/tools/task_tools/windows/launcher.py tests/test_task_tools_launcher.py
git commit -m "feat: add task tool launcher window"
```

---

### Task 5: Persistent Windows Bootstrap and SendTo Installer

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/windows/paths.py`
- Create: `src/tags_machine_core/tools/task_tools/windows/sendto_installer.py`
- Create: `src/tags_machine_core/tools/task_tools/windows/bootstrap.ps1`
- Create: `src/tags_machine_core/tools/task_tools/windows/sendto_entry.vbs`
- Create: `tests/test_task_tools_sendto.py`

**Interfaces:**
- Consumes: effective operation configuration and Registry.
- Produces: `WindowsTaskToolPaths`, `SendToInstallResult`, `SendToInstaller`.
- Manages only files listed in `%LOCALAPPDATA%\PromptAtelier\TaskTools\install.json`.

- [ ] **Step 1: Write installer tests against temporary Windows directories**

```python
import json
from pathlib import Path

from tags_machine_core.tools.task_tools.config import load_task_tools_config
from tags_machine_core.tools.task_tools.registry import build_default_registry
from tags_machine_core.tools.task_tools.windows.paths import WindowsTaskToolPaths
from tags_machine_core.tools.task_tools.windows.sendto_installer import SendToInstaller


def test_install_creates_quick_entries_launcher_and_manifest(tmp_path: Path):
    paths = WindowsTaskToolPaths(
        app_dir=tmp_path / "local" / "PromptAtelier" / "TaskTools",
        sendto_dir=tmp_path / "sendto",
    )
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    installer = SendToInstaller(paths=paths)

    result = installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "refactor" / ".venv" / "Scripts" / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )

    names = sorted(path.name for path in result.sendto_entries)
    assert names == [
        "Refactor - 打开 Action 目录.vbs",
        "Refactor - 打开 Artist 目录.vbs",
        "Refactor 工具.vbs",
    ]
    manifest = json.loads(paths.install_manifest.read_text(encoding="utf-8"))
    assert manifest["managed_sendto_entries"] == names


def test_sync_removes_only_previous_managed_entries(tmp_path: Path):
    paths = WindowsTaskToolPaths(
        app_dir=tmp_path / "app",
        sendto_dir=tmp_path / "sendto",
    )
    paths.sendto_dir.mkdir(parents=True)
    user_file = paths.sendto_dir / "ct.blackboard.run_actions.bat"
    user_file.write_text("keep", encoding="utf-8")
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    installer = SendToInstaller(paths=paths)
    installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )
    config.operations["open_artist_directory"].placement = "launcher"

    installer.sync(registry=registry, config=config)

    assert user_file.read_text(encoding="utf-8") == "keep"
    assert not (paths.sendto_dir / "Refactor - 打开 Artist 目录.vbs").exists()


def test_uninstall_preserves_unmanaged_sendto_items(tmp_path: Path):
    paths = WindowsTaskToolPaths(
        app_dir=tmp_path / "app",
        sendto_dir=tmp_path / "sendto",
    )
    paths.sendto_dir.mkdir(parents=True)
    user_file = paths.sendto_dir / "ct.keep.bat"
    user_file.write_text("keep", encoding="utf-8")
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    installer = SendToInstaller(paths=paths)
    result = installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )

    removed = installer.uninstall()

    assert user_file.read_text(encoding="utf-8") == "keep"
    assert all(not path.exists() for path in result.sendto_entries)
    assert paths.bootstrap_script in removed
    assert not paths.install_manifest.exists()
```

- [ ] **Step 2: Run tests and confirm missing modules**

```powershell
uv run pytest tests/test_task_tools_sendto.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement Windows path discovery**

```python
@dataclass(frozen=True, slots=True)
class WindowsTaskToolPaths:
    app_dir: Path
    sendto_dir: Path

    @property
    def install_manifest(self) -> Path:
        return self.app_dir / "install.json"

    @property
    def bootstrap_script(self) -> Path:
        return self.app_dir / "bootstrap.ps1"

    @property
    def log_dir(self) -> Path:
        return self.app_dir / "logs"

    @classmethod
    def discover(cls) -> "WindowsTaskToolPaths":
        local_app_data = os.environ.get("LOCALAPPDATA")
        app_data = os.environ.get("APPDATA")
        if not local_app_data or not app_data:
            raise RuntimeError("缺少 LOCALAPPDATA 或 APPDATA，无法安装 Windows 任务工具")
        return cls(
            app_dir=Path(local_app_data) / "PromptAtelier" / "TaskTools",
            sendto_dir=Path(app_data) / "Microsoft" / "Windows" / "SendTo",
        )
```

`discover()` requires `LOCALAPPDATA` and `APPDATA`; raise a Chinese `RuntimeError` when missing.

- [ ] **Step 4: Implement bootstrap and SendTo templates**

`bootstrap.ps1` contract:

```powershell
param(
    [Parameter(Mandatory = $true)][ValidateSet("run", "launcher")][string]$Mode,
    [string]$OperationId = "",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$InputPaths
)

$ErrorActionPreference = "Stop"
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $appDir "install.json"

try {
    $install = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $install.pythonw_path)) {
        throw "Refactor Python 环境不存在：$($install.pythonw_path)"
    }
    $arguments = @("-m", "tags_machine_core", "task-tools", $Mode)
    if ($Mode -eq "run") { $arguments += $OperationId }
    if ($install.config_path) { $arguments += @("--config", $install.config_path) }
    $arguments += "--"
    $arguments += $InputPaths
    Push-Location $install.project_root
    try {
        & $install.pythonw_path @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Refactor 任务工具执行失败，退出码：$LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, "Refactor 任务工具", "OK", "Error") | Out-Null
}
```

`sendto_entry.vbs` is this format template; Python replaces `{bootstrap_path}`, `{mode}`, and `{operation_id}` during installation:

```vbscript
Option Explicit

Dim shell, command, argument
Set shell = CreateObject("WScript.Shell")

Function QuoteArgument(value)
    QuoteArgument = """" & Replace(CStr(value), """", """""") & """"
End Function

command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass" & _
          " -File ""{bootstrap_path}""" & _
          " -Mode ""{mode}""" & _
          " -OperationId ""{operation_id}"""

For Each argument In WScript.Arguments
    command = command & " " & QuoteArgument(argument)
Next

shell.Run command, 0, False
```

- [ ] **Step 5: Implement manifest-based install, sync, and uninstall**

```python
@dataclass(frozen=True, slots=True)
class SendToInstallResult:
    app_dir: Path
    sendto_entries: list[Path]
    manifest_path: Path


class SendToInstaller:
    def __init__(self, *, paths: WindowsTaskToolPaths | None = None):
        self.paths = paths or WindowsTaskToolPaths.discover()

    def install(
        self,
        *,
        project_root: Path,
        pythonw_path: Path,
        config_path: Path | None,
        registry: OperationRegistry,
        config: TaskToolsConfig,
    ) -> SendToInstallResult:
        install = {
            "schema": "prompt-atelier.task-tools-install/v1",
            "project_root": str(project_root.resolve()),
            "pythonw_path": str(pythonw_path.resolve()),
            "config_path": str(config_path.resolve()) if config_path else None,
            "managed_sendto_entries": [],
        }
        return self._write_install(install=install, registry=registry, config=config)

    def sync(
        self,
        *,
        registry: OperationRegistry,
        config: TaskToolsConfig,
        config_path: Path | None = None,
    ) -> SendToInstallResult:
        install = self._read_manifest(required=True)
        if config_path is not None:
            install["config_path"] = str(config_path.resolve())
        return self._write_install(install=install, registry=registry, config=config)

    def uninstall(self) -> list[Path]:
        install = self._read_manifest(required=False)
        removed: list[Path] = []
        for name in install.get("managed_sendto_entries", []):
            target = self.paths.sendto_dir / Path(str(name)).name
            if target.is_file():
                target.unlink()
                removed.append(target)
        for target in (self.paths.bootstrap_script, self.paths.install_manifest):
            if target.is_file():
                target.unlink()
                removed.append(target)
        return removed

    def _write_install(
        self,
        *,
        install: dict[str, object],
        registry: OperationRegistry,
        config: TaskToolsConfig,
    ) -> SendToInstallResult:
        old = self._read_manifest(required=False)
        for name in old.get("managed_sendto_entries", []):
            target = self.paths.sendto_dir / Path(str(name)).name
            if target.is_file():
                target.unlink()
        self.paths.app_dir.mkdir(parents=True, exist_ok=True)
        self.paths.sendto_dir.mkdir(parents=True, exist_ok=True)
        self.paths.log_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.paths.bootstrap_script, _read_packaged_text("bootstrap.ps1"))

        entries: list[Path] = []
        for spec in registry.all():
            override = config.operations[spec.id]
            if not override.enabled or override.placement not in {
                OperationPlacement.QUICK,
                OperationPlacement.BOTH,
            }:
                continue
            label = _safe_filename(override.label or spec.default_label)
            entry = self.paths.sendto_dir / f"Refactor - {label}.vbs"
            _write_atomic(
                entry,
                _render_sendto_entry(
                    bootstrap_path=self.paths.bootstrap_script,
                    mode="run",
                    operation_id=spec.id,
                ),
            )
            entries.append(entry)

        launcher = self.paths.sendto_dir / "Refactor 工具.vbs"
        _write_atomic(
            launcher,
            _render_sendto_entry(
                bootstrap_path=self.paths.bootstrap_script,
                mode="launcher",
                operation_id="",
            ),
        )
        entries.append(launcher)
        install["managed_sendto_entries"] = [entry.name for entry in entries]
        _write_atomic(
            self.paths.install_manifest,
            json.dumps(install, ensure_ascii=False, indent=2) + "\n",
        )
        return SendToInstallResult(
            app_dir=self.paths.app_dir,
            sendto_entries=entries,
            manifest_path=self.paths.install_manifest,
        )

    def _read_manifest(self, *, required: bool) -> dict[str, object]:
        if not self.paths.install_manifest.is_file():
            if required:
                raise RuntimeError("任务工具尚未安装，请先执行 install-sendto")
            return {}
        value = json.loads(self.paths.install_manifest.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("任务工具安装清单格式错误")
        return value


def _write_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_filename(value: str) -> str:
    result = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    if not result:
        raise ValueError("SendTo 显示名称不能为空")
    return result


def _read_packaged_text(name: str) -> str:
    package = resources.files("tags_machine_core.tools.task_tools.windows")
    return package.joinpath(name).read_text(encoding="utf-8")


def _render_sendto_entry(
    *,
    bootstrap_path: Path,
    mode: str,
    operation_id: str,
) -> str:
    template = _read_packaged_text("sendto_entry.vbs")
    return (
        template.replace("{bootstrap_path}", str(bootstrap_path).replace('"', '""'))
        .replace("{mode}", mode)
        .replace("{operation_id}", operation_id)
    )
```

Manifest schema:

```json
{
  "schema": "prompt-atelier.task-tools-install/v1",
  "project_root": "F:\\my_project\\new\\tags_machine\\refactor",
  "pythonw_path": "F:\\my_project\\new\\tags_machine\\refactor\\.venv\\Scripts\\pythonw.exe",
  "config_path": null,
  "managed_sendto_entries": [
    "Refactor - 打开 Action 目录.vbs",
    "Refactor - 打开 Artist 目录.vbs",
    "Refactor 工具.vbs"
  ]
}
```

Before replacing entries, read the old manifest and delete only its listed entries. Write files atomically through a temporary sibling and `Path.replace()`.

- [ ] **Step 6: Run installer tests and inspect generated scripts**

```powershell
uv run pytest tests/test_task_tools_sendto.py -q
uv run ruff check src/tags_machine_core/tools/task_tools/windows tests/test_task_tools_sendto.py
```

Expected: tests pass; no unmanaged file is removed.

- [ ] **Step 7: Commit Task 5**

```powershell
git add src/tags_machine_core/tools/task_tools/windows tests/test_task_tools_sendto.py
git commit -m "feat: install persistent SendTo task tools"
```

---

### Task 6: CLI Integration, Example Configuration, and User Documentation

**Files:**
- Create: `src/tags_machine_core/tools/task_tools/cli.py`
- Create: `configs/task_tools.example.yaml`
- Create: `docs/task_tools_readme.md`
- Create: `scripts/install_task_tools.ps1`
- Create: `tests/test_task_tools_cli.py`
- Modify: `src/tags_machine_core/cli.py`
- Modify: `src/tags_machine_core/tools/task_tools/__init__.py`

**Interfaces:**
- Produces the top-level `uv run python -m tags_machine_core task-tools` command group.
- `task-tools run` and `task-tools launcher` accept Explorer inputs after `--`.
- Installation commands print concise JSON to stdout for terminal use; `pythonw` execution reports failures through Windows notifications.

- [ ] **Step 1: Write CLI parser and command tests**

```python
from pathlib import Path
from unittest.mock import Mock, patch

from tags_machine_core.cli import build_parser


def test_task_tools_run_parser_preserves_multiple_input_paths():
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


@patch("tags_machine_core.tools.task_tools.cli.TaskArchiveResolver")
@patch("tags_machine_core.tools.task_tools.cli.TaskToolRunner")
def test_quick_run_reports_errors_through_notifier(runner_type, resolver_type, tmp_path: Path):
    resolver_type.return_value.resolve.side_effect = RuntimeError("归档损坏")
    notifier = Mock()

    exit_code = run_task_tool_operation(
        operation_id="open_action_directory",
        inputs=[str(tmp_path)],
        config_path=None,
        notifier=notifier,
    )

    assert exit_code == 1
    notifier.assert_called_once()
```

- [ ] **Step 2: Run CLI tests and confirm parser command is absent**

```powershell
uv run pytest tests/test_task_tools_cli.py -q
```

Expected: parser rejects `task-tools` or import fails.

- [ ] **Step 3: Add the isolated task-tools subparser**

In `task_tools/cli.py`, expose:

```python
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
    commands = parser.add_subparsers(dest="task_tool_command")

    run = commands.add_parser("run", help="Run one registered task operation")
    run.add_argument("operation_id")
    run.add_argument("--config", type=Path)
    run.add_argument("inputs", nargs="+")
    run.set_defaults(func=cmd_task_tools_run)

    launcher = commands.add_parser("launcher", help="Open the task tools window")
    launcher.add_argument("--config", type=Path)
    launcher.add_argument("inputs", nargs="+")
    launcher.set_defaults(func=cmd_task_tools_launcher)

    for name, handler in (
        ("install-sendto", cmd_task_tools_install),
        ("sync-sendto", cmd_task_tools_sync),
    ):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path)
        command.set_defaults(func=handler)

    uninstall = commands.add_parser("uninstall-sendto")
    uninstall.set_defaults(func=cmd_task_tools_uninstall)


def run_task_tool_operation(
    *,
    operation_id: str,
    inputs: list[str],
    config_path: Path | None,
    notifier: Callable[[str, str], None] = show_error,
) -> int:
    try:
        registry = build_default_registry()
        config = load_task_tools_config(config_path, registry=registry)
        contexts = TaskArchiveResolver().resolve(inputs)
        TaskToolRunner(registry=registry, config=config).run(operation_id, contexts)
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
    registry = build_default_registry()
    config = load_task_tools_config(args.config, registry=registry)
    contexts = TaskArchiveResolver().resolve(args.inputs)
    runner = TaskToolRunner(registry=registry, config=config)
    return launch_task_tools_window(
        contexts=contexts,
        registry=registry,
        config=config,
        runner=runner,
    )
```

`cmd_task_tools_install` derives `pythonw.exe` from `Path(sys.executable).with_name("pythonw.exe")`, validates it exists, and calls `SendToInstaller.install()`. `cmd_task_tools_sync` loads the effective config and calls `sync(config_path=args.config)` so a newly selected config becomes the persisted launcher config. `cmd_task_tools_uninstall` calls `uninstall()`. Each command prints a small JSON object containing changed paths and returns `0`; exceptions return `1` after `show_error()`.

Subcommands:

```text
task-tools run <operation_id> [--config PATH] -- <input-paths>
task-tools launcher [--config PATH] -- <input-paths>
task-tools install-sendto [--config PATH]
task-tools sync-sendto [--config PATH]
task-tools uninstall-sendto
```

In root `cli.py`, add only:

```python
from tags_machine_core.tools.task_tools.cli import add_task_tools_subparser

# inside build_parser(), after output_parent is defined
add_task_tools_subparser(subparsers, output_parent=output_parent)
```

Do not add task tool implementation functions to the already large root CLI.

- [ ] **Step 4: Add example configuration**

`configs/task_tools.example.yaml`:

```yaml
schema: prompt-atelier.task-tools/v1
log_level: error

operations:
  open_action_directory:
    enabled: true
    placement: both
    order: 10

  open_artist_directory:
    enabled: true
    placement: both
    order: 20
```

- [ ] **Step 5: Add the installation convenience script**

`scripts/install_task_tools.ps1`:

```powershell
param(
    [ValidateSet("install", "sync", "uninstall")]
    [string]$Mode = "install",
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$command = switch ($Mode) {
    "install" { "install-sendto" }
    "sync" { "sync-sendto" }
    "uninstall" { "uninstall-sendto" }
}
$arguments = @("run", "python", "-m", "tags_machine_core", "task-tools", $command)
if ($Config) { $arguments += @("--config", (Resolve-Path $Config).Path) }

Push-Location $projectRoot
try {
    & uv @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
```

Run it from project root through `uv` and ensure the implementation uses `sys.executable` to derive the sibling `pythonw.exe` path.

- [ ] **Step 6: Write the Chinese user guide**

`docs/task_tools_readme.md` must include:

- Supported inputs: task directory, task PNG, task JSON, multiple selection.
- Install, sync, uninstall commands.
- `placement: quick|launcher|both` semantics.
- Actual SendTo item names.
- Archive field sources for Action and Artist.
- Behavior when project path, `.venv`, archive, or node path is missing.
- Log location.
- How to add a new code-registered operation.
- The real example directory used for acceptance.

- [ ] **Step 7: Run CLI and documentation checks**

```powershell
uv run pytest tests/test_task_tools_cli.py tests/test_task_tools_config.py -q
uv run python -m tags_machine_core task-tools --help
uv run python -m tags_machine_core task-tools install-sendto --help
uv run ruff check src/tags_machine_core/tools/task_tools src/tags_machine_core/cli.py tests/test_task_tools_cli.py
```

Expected: tests pass; help output lists all five commands.

- [ ] **Step 8: Commit Task 6**

```powershell
git add src/tags_machine_core/cli.py src/tags_machine_core/tools/task_tools configs/task_tools.example.yaml docs/task_tools_readme.md scripts/install_task_tools.ps1 tests/test_task_tools_cli.py
git commit -m "feat: expose configurable Windows task tools"
```

---

### Task 7: Real Archive Business Acceptance and Installation Verification

**Files:**
- Create: `docs/task_tools_business_acceptance_20260718.md`
- Modify only if acceptance reveals a defect: files created in Tasks 1-6 and their focused tests.

**Interfaces:**
- Consumes the complete task-tools CLI and Windows installation.
- Produces an acceptance record containing actual resolved paths, installed entries, operation results, and known manual reboot limitation.

- [ ] **Step 1: Run the complete focused regression suite**

```powershell
uv run pytest tests/test_task_tools_config.py tests/test_task_tools_resolver.py tests/test_task_tools_runner.py tests/test_task_tools_launcher.py tests/test_task_tools_sendto.py tests/test_task_tools_cli.py -q
uv run ruff check src/tags_machine_core/tools/task_tools src/tags_machine_core/cli.py tests/test_task_tools_*.py
```

Expected: all tests pass and Ruff exits `0`.

- [ ] **Step 2: Resolve the real task archive and record exact resources**

Run:

```powershell
uv run python -c "from tags_machine_core.tools.task_tools.resolver import TaskArchiveResolver; c=TaskArchiveResolver().resolve([r'G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f']); print('ACTION=' + str(c.existing_paths('action')[0])); print('ARTIST=' + str(c.existing_paths('artist')[0]))"
```

Expected Action path ends with the archived action node `00_start_侧脸回眸`; Artist path equals:

```text
F:\my_project\new\tags_machine\design\画风\114425243_Soft_Akipeco_Official
```

Do not infer expected paths from the task directory name; compare them against `render_request.json` fields.

- [ ] **Step 3: Verify PNG input resolves to the same task**

Select one actual generated PNG from the task directory and run the same resolver command with that PNG path. Record that `task_dir`, Action path, and Artist path match Step 2.

- [ ] **Step 4: Snapshot existing SendTo files before installation**

```powershell
$sendTo = Join-Path $env:APPDATA 'Microsoft\Windows\SendTo'
Get-ChildItem -LiteralPath $sendTo -File | ForEach-Object {
    [pscustomobject]@{
        Name = $_.Name
        Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
    }
} | ConvertTo-Json | Set-Content -Encoding UTF8 "$env:TEMP\prompt-atelier-sendto-before.json"
```

- [ ] **Step 5: Install the real SendTo entries**

```powershell
uv run python -m tags_machine_core task-tools install-sendto --config configs/task_tools.example.yaml
```

Expected:

- LocalAppData install manifest exists.
- Three SendTo entries exist.
- Existing `ct.*` files remain.
- Installation JSON reports the actual project root and `.venv\Scripts\pythonw.exe`.

- [ ] **Step 6: Execute both real quick operations**

```powershell
uv run python -m tags_machine_core task-tools run open_action_directory --config configs/task_tools.example.yaml -- 'G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f'
uv run python -m tags_machine_core task-tools run open_artist_directory --config configs/task_tools.example.yaml -- 'G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f'
```

Business acceptance:

- Explorer opens the actual Action directory.
- Explorer opens the actual Artist directory.
- No console-only success message is required.

- [ ] **Step 7: Launch the unified window with the real task**

```powershell
uv run python -m tags_machine_core task-tools launcher --config configs/task_tools.example.yaml -- 'G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f'
```

Visually verify:

- Action and Artist names are correct.
- Both operations are enabled.
- Clicking both buttons opens the same directories as Step 6.
- Window remains usable after opening a directory.

- [ ] **Step 8: Verify configurable placement and safe synchronization**

Create a temporary config in `%TEMP%` with Action `quick` and Artist `launcher`, then run `sync-sendto`. Verify:

- Action quick entry remains.
- Artist quick entry is removed.
- Artist remains visible in Launcher.
- Checksums for every pre-existing `ct.*` file match the Step 4 snapshot.

Restore `configs/task_tools.example.yaml` and run `sync-sendto` again.

- [ ] **Step 9: Verify fresh-process persistence**

Close the current terminal and invoke each installed SendTo entry from Explorer against the real task directory. This simulates a fresh process and proves no in-memory registration is required.

Do not automatically reboot the user's workstation. Record that the entries are ordinary files under `%APPDATA%\Microsoft\Windows\SendTo` and the bootstrap/manifest are ordinary files under `%LOCALAPPDATA%`, so Windows restart does not remove them. The user can perform a physical reboot check later without reinstalling.

- [ ] **Step 10: Write the business acceptance record**

`docs/task_tools_business_acceptance_20260718.md` must record:

- Date and branch commit.
- Real task path.
- Parsed Action and Artist paths.
- PNG input used.
- Installed SendTo entries.
- Placement synchronization result.
- Confirmation that `ct.*` hashes were unchanged.
- Actual Explorer and Launcher observations.
- Automated test and Ruff results.
- Reboot persistence rationale and the fact that an automatic reboot was intentionally not performed.

- [ ] **Step 11: Run final verification**

```powershell
uv run pytest tests/test_task_tools_config.py tests/test_task_tools_resolver.py tests/test_task_tools_runner.py tests/test_task_tools_launcher.py tests/test_task_tools_sendto.py tests/test_task_tools_cli.py -q
uv run ruff check src/tags_machine_core/tools/task_tools src/tags_machine_core/cli.py tests/test_task_tools_*.py
git diff --check
```

Expected: all tests pass, Ruff exits `0`, and `git diff --check` reports no whitespace errors.

- [ ] **Step 12: Commit business acceptance artifacts and any acceptance fixes**

```powershell
git add docs/task_tools_business_acceptance_20260718.md src/tags_machine_core/tools/task_tools src/tags_machine_core/cli.py configs/task_tools.example.yaml docs/task_tools_readme.md scripts/install_task_tools.ps1 tests/test_task_tools_*.py
git commit -m "test: verify Windows task tools workflow"
```
