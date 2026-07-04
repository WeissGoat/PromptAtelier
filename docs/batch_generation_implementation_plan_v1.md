# 自动化批量跑图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个由 `BatchSpec` 驱动的自动化批量跑图层，支持按动作文件夹/collection 展开任务，通过现有 `GenerationService` 真实调用 NovelAI，支持恢复执行，并归档业务验收证据。

**Architecture:** 新增 `tags_machine_core.batch` 包，只负责批量编排，不自己拼 prompt，不直接拼 NovelAI payload。它复用 `GenerationService`、`AgentComposer`、`NovelAIRenderer`、`execute_render_request` 和现有 PNG 参数工具；纯逻辑可用单测覆盖，但发布门禁以真实 NovelAI 出图为准。

**Tech Stack:** Python 3.11、Pydantic v2、PyYAML、pytest、现有 `tags_machine_core` CLI 与执行链路。

---

## Spec 与实现计划的区别

一句话区分：`spec` 是“我们要造什么”，`实现计划` 是“从哪几个文件、哪几个步骤把它造出来”。

`spec` 回答“要做什么、为什么这样做、边界在哪里”。它面向产品和架构 review，重点是需求、术语、数据契约、非目标、验收口径。它应该足够稳定，用来判断方向是否对、范围是否收敛、验收是否清楚。

`实现计划` 回答“怎么一步步落地”。它面向开发执行，重点是新增/修改哪些文件、每步实现什么、每步怎么验证、什么时候提交、最后如何真实业务验收。它允许随着开发细节微调，但每次调整都应该服务于同一个 spec。

在这个项目里，两者的分工是：

| 文档 | 主要回答 | 不负责 |
| --- | --- | --- |
| `batch_generation_spec_v1.md` | 自动化批量跑图的目标、边界、模块职责、BatchSpec 格式、验收口径 | 不列出逐文件改动步骤 |
| `batch_generation_implementation_plan_v1.md` | 按任务拆分的开发顺序、文件清单、测试命令、真实 NovelAI 验收步骤 | 不重新讨论架构方向 |

本计划基于 [batch_generation_spec_v1.md](F:/my_project/new/tags_machine/refactor/docs/batch_generation_spec_v1.md)。

## 用户偏好与执行约束

- 业务测试优先于接口单测。
- 涉及真实生图链路时，最终必须跑 NovelAI 真实出图。
- 单元测试只覆盖不联网的纯逻辑：spec 解析、selector、planner、manifest、archive/report。
- 第一版不做并发，默认串行跑图。
- 第一版只接 NovelAI 真实执行。
- 不修改父项目旧 `blackboard.py`、`formula.py`、`TagsMachine`。
- 不迁移旧提示词库，继续通过 `configs/local.example.yaml` 的 `legacy.design_root` 读取旧 `design`。

## 文件结构

新增包：

```text
src/tags_machine_core/batch/
  __init__.py              # 对外导出 BatchSpec、BatchPlanner、BatchRunner 等核心类型
  models.py                # Pydantic 数据模型：BatchSpec、BatchTask、ManifestEntry
  spec_reader.py           # 读取 YAML/JSON，解析相对路径
  selectors.py             # explicit/folder/collection/glob/prompt selector
  planner.py               # BatchSpec -> BatchTask 列表
  manifest.py              # manifest.jsonl、index.json、status 读写
  archive.py               # task 目录归档，保存 PromptBundle/RenderRequest/GenerationResult
  report.py                # report.md/report.json
  executor.py              # 单任务执行：调用 GenerationService 和 execute_render_request
  runner.py                # 批量主控：resume、retry、limit、stop_on_error
```

修改文件：

```text
src/tags_machine_core/cli.py
src/tags_machine_core/services/json_api_models.py
src/tags_machine_core/services/json_api.py
src/tags_machine_core/services/__init__.py
docs/README.md
```

新增测试：

```text
tests/test_batch_models.py
tests/test_batch_selectors.py
tests/test_batch_planner.py
tests/test_batch_manifest_archive_report.py
tests/test_batch_executor_runner.py
tests/test_batch_cli.py
```

新增示例：

```text
examples/batches/prompt_list_20260412.yaml
examples/batches/action_folder_20260412.yaml
examples/batches/agent_cache_miss.yaml
```

## Task 1: Batch 数据模型

**Files:**
- Create: `src/tags_machine_core/batch/__init__.py`
- Create: `src/tags_machine_core/batch/models.py`
- Test: `tests/test_batch_models.py`

- [ ] **Step 1: 写模型测试**

```python
# tests/test_batch_models.py
from tags_machine_core.batch.models import BatchSpec, BatchTask, ManifestEntry


def test_batch_spec_defaults_are_business_safe():
    spec = BatchSpec.model_validate(
        {
            "schema": "tags-machine-core.batch/v1",
            "name": "smoke",
            "select": {
                "prompts": [
                    {
                        "selector": "prompt_list",
                        "items": [{"id": "p1", "prompt": "1girl, standing"}],
                    }
                ]
            },
            "expand": {"mode": "prompt_list"},
        }
    )

    assert spec.defaults.backend == "novelai"
    assert spec.defaults.composer == "full"
    assert spec.defaults.nt == 1
    assert spec.run.resume is True
    assert spec.run.stop_on_error is False
    assert spec.archive.save_generation_result is True


def test_batch_task_id_rejects_empty_value():
    try:
        BatchTask.model_validate(
            {
                "id": "",
                "index": 0,
                "composer": "full",
                "nodes": [],
                "render": {"backend": "novelai", "artist": "20260412", "nt": 1},
                "output": {"task_dir": "outputs/batches/run/tasks/t1"},
            }
        )
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("empty task id should fail validation")


def test_manifest_entry_status_values():
    entry = ManifestEntry.model_validate(
        {
            "task_id": "t1",
            "status": "requires_agent",
            "attempt": 0,
            "task_path": "tasks/t1/task.json",
            "status_path": "tasks/t1/status.json",
            "updated_at": "2026-06-13T00:00:00+08:00",
        }
    )

    assert entry.status == "requires_agent"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_models.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tags_machine_core.batch'
```

- [ ] **Step 3: 实现 `models.py`**

```python
# src/tags_machine_core/batch/models.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ComposerMode = Literal["full", "agent", "script"]
BatchStatus = Literal[
    "pending",
    "requires_agent",
    "ready",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
]
ExpandMode = Literal["product", "zip", "prompt_list", "manual"]


class RetryConfig(BaseModel):
    max_attempts: int = 3
    timeout_seconds: float | None = None
    retry_on: list[str] = Field(
        default_factory=lambda: ["429", "500", "502", "503", "504", "timeout"]
    )
    backoff_seconds: list[float] = Field(default_factory=lambda: [1.0, 2.0, 5.0, 10.0])


class RunConfig(BaseModel):
    resume: bool = True
    stop_on_error: bool = False
    max_images: int | None = None
    execute_requires_agent: bool = False
    retry: RetryConfig = Field(default_factory=RetryConfig)


class ArchiveConfig(BaseModel):
    save_prompt_bundle: bool = True
    save_render_request: bool = True
    save_generation_result: bool = True
    save_png_params: bool = True
    copy_images: bool = False


class ReportConfig(BaseModel):
    markdown: bool = True
    json: bool = True
    include_prompt_preview: bool = True
    include_png_params_summary: bool = True
    visual_check_template: bool = True


class BatchDefaults(BaseModel):
    backend: str = "novelai"
    composer: ComposerMode = "full"
    artist: str | None = None
    nt: int = 1
    resolution: str = "square"
    width: int | None = None
    height: int | None = None
    image_format: str = "png"
    prompt_policy_profile: str | None = None
    model: str = "nai-diffusion-4-5-full"
    add_male_caption: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class SelectorSpec(BaseModel):
    selector: str
    refs: list[str] = Field(default_factory=list)
    root: str | None = None
    name: str | None = None
    pattern: str | None = None
    path: str | None = None
    format: str = "lines"
    items: list[dict[str, Any]] = Field(default_factory=list)
    recursive: bool = False
    node_files: list[str] = Field(default_factory=lambda: ["meta.yaml", "node.yaml", "tags.txt"])
    include: dict[str, Any] = Field(default_factory=dict)
    exclude: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = None
    shuffle: bool = False


class BatchSelect(BaseModel):
    artists: list[SelectorSpec] = Field(default_factory=list)
    characters: list[SelectorSpec] = Field(default_factory=list)
    actions: list[SelectorSpec] = Field(default_factory=list)
    backgrounds: list[SelectorSpec] = Field(default_factory=list)
    prompts: list[SelectorSpec] = Field(default_factory=list)


class ExpandConfig(BaseModel):
    mode: ExpandMode = "product"
    max_tasks: int | None = None
    shuffle: bool = False


class NodeRef(BaseModel):
    role: str
    ref: str
    index: int = 0


class PromptItem(BaseModel):
    id: str
    prompt: str
    negative: str | None = None


class RenderOptions(BaseModel):
    backend: str = "novelai"
    artist: str | None = None
    nt: int = 1
    resolution: str = "square"
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    model: str = "nai-diffusion-4-5-full"
    image_format: str = "png"
    params: dict[str, Any] = Field(default_factory=dict)


class TaskOutput(BaseModel):
    task_dir: str


class BatchTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.batch-task/v1", alias="schema")
    id: str
    index: int
    composer: ComposerMode
    nodes: list[NodeRef] = Field(default_factory=list)
    prompt: str | None = None
    negative: str | None = None
    extra_prompt: str = ""
    render: RenderOptions
    policy: dict[str, Any] = Field(default_factory=dict)
    output: TaskOutput
    source: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_must_not_be_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("BatchTask id must not be empty")
        return text


class ManifestEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="tags-machine-core.batch-manifest-entry/v1",
        alias="schema",
    )
    task_id: str
    status: BatchStatus
    attempt: int = 0
    task_path: str
    status_path: str
    generation_result_path: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    updated_at: str


class BatchSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.batch/v1", alias="schema")
    name: str
    description: str | None = None
    config: str = "configs/local.example.yaml"
    output_root: str = "outputs/batches"
    defaults: BatchDefaults = Field(default_factory=BatchDefaults)
    collections: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    select: BatchSelect = Field(default_factory=BatchSelect)
    expand: ExpandConfig = Field(default_factory=ExpandConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    tasks: list[dict[str, Any]] = Field(default_factory=list)

    def config_path(self, base_dir: Path) -> Path:
        path = Path(self.config)
        return path if path.is_absolute() else base_dir / path
```

- [ ] **Step 4: 实现 `__init__.py`**

```python
# src/tags_machine_core/batch/__init__.py
from .models import (
    ArchiveConfig,
    BatchDefaults,
    BatchSpec,
    BatchTask,
    ManifestEntry,
    NodeRef,
    PromptItem,
    RenderOptions,
    ReportConfig,
    RunConfig,
    SelectorSpec,
)

__all__ = [
    "ArchiveConfig",
    "BatchDefaults",
    "BatchSpec",
    "BatchTask",
    "ManifestEntry",
    "NodeRef",
    "PromptItem",
    "RenderOptions",
    "ReportConfig",
    "RunConfig",
    "SelectorSpec",
]
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
uv run pytest tests/test_batch_models.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: 提交**

```bash
git add src/tags_machine_core/batch/__init__.py src/tags_machine_core/batch/models.py tests/test_batch_models.py
git commit -m "Add batch generation models"
```

## Task 2: BatchSpecReader 与选择器

**Files:**
- Create: `src/tags_machine_core/batch/spec_reader.py`
- Create: `src/tags_machine_core/batch/selectors.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_selectors.py`

- [ ] **Step 1: 写 selector 测试**

```python
# tests/test_batch_selectors.py
from pathlib import Path

from tags_machine_core.batch.models import SelectorSpec
from tags_machine_core.batch.selectors import SelectorContext, expand_selector
from tags_machine_core.batch.spec_reader import load_batch_spec


def test_folder_selector_prefers_meta_yaml_and_skips_classify(tmp_path: Path):
    action_dir = tmp_path / "actions"
    node_dir = action_dir / "foot_closeup"
    node_dir.mkdir(parents=True)
    (node_dir / "meta.yaml").write_text(
        "schema: tags-machine.action/v1\nkind: action\nid: foot_closeup\nprompt: foot focus\n",
        encoding="utf-8",
    )
    (node_dir / "classify.yaml").write_text("tags: [foot]\n", encoding="utf-8")

    refs = expand_selector(
        role="action",
        spec=SelectorSpec(selector="folder", root=str(action_dir), recursive=True),
        context=SelectorContext(base_dir=tmp_path, collections={}),
    )

    assert refs == [str(node_dir)]


def test_collection_selector_expands_multiple_roots(tmp_path: Path):
    a = tmp_path / "a" / "x"
    b = tmp_path / "b" / "y"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "tags.txt").write_text("standing\n", encoding="utf-8")
    (b / "tags.txt").write_text("sitting\n", encoding="utf-8")

    refs = expand_selector(
        role="action",
        spec=SelectorSpec(selector="collection", name="foot", recursive=True),
        context=SelectorContext(
            base_dir=tmp_path,
            collections={"actions": {"foot": [str(tmp_path / "a"), str(tmp_path / "b")]}},
        ),
    )

    assert refs == [str(a), str(b)]


def test_prompt_list_selector_returns_prompt_items(tmp_path: Path):
    refs = expand_selector(
        role="prompt",
        spec=SelectorSpec(
            selector="prompt_list",
            items=[{"id": "p1", "prompt": "1girl, standing"}],
        ),
        context=SelectorContext(base_dir=tmp_path, collections={}),
    )

    assert refs == [{"id": "p1", "prompt": "1girl, standing"}]


def test_load_batch_spec_reads_yaml(tmp_path: Path):
    path = tmp_path / "batch.yaml"
    path.write_text(
        "schema: tags-machine-core.batch/v1\n"
        "name: smoke\n"
        "select:\n"
        "  prompts:\n"
        "    - selector: prompt_list\n"
        "      items:\n"
        "        - id: p1\n"
        "          prompt: 1girl\n",
        encoding="utf-8",
    )

    spec = load_batch_spec(path)

    assert spec.name == "smoke"
    assert spec.select.prompts[0].items[0]["id"] == "p1"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_selectors.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tags_machine_core.batch.selectors'
```

- [ ] **Step 3: 实现 spec reader**

```python
# src/tags_machine_core/batch/spec_reader.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import BatchSpec


def load_batch_spec(path: str | Path) -> BatchSpec:
    spec_path = Path(path)
    data = _read_mapping(spec_path)
    return BatchSpec.model_validate(data)


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Batch spec must be a mapping: {path}")
    return data


def resolve_path(value: str, *, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path
```

- [ ] **Step 4: 实现 selectors**

```python
# src/tags_machine_core/batch/selectors.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SelectorSpec
from .spec_reader import resolve_path


@dataclass(frozen=True)
class SelectorContext:
    base_dir: Path
    collections: dict[str, dict[str, list[str]]]


def expand_selector(
    *,
    role: str,
    spec: SelectorSpec,
    context: SelectorContext,
) -> list[Any]:
    selector = spec.selector.strip()
    if selector == "explicit":
        return [str(_resolve_ref(ref, context.base_dir)) for ref in spec.refs]
    if selector == "folder":
        if not spec.root:
            raise ValueError("folder selector requires root")
        return _discover_nodes(resolve_path(spec.root, base_dir=context.base_dir), spec)
    if selector == "collection":
        if not spec.name:
            raise ValueError("collection selector requires name")
        roots = context.collections.get(f"{role}s", {}).get(spec.name, [])
        if not roots:
            raise ValueError(f"Unknown {role} collection: {spec.name}")
        result: list[str] = []
        for root in roots:
            result.extend(_discover_nodes(_resolve_ref(root, context.base_dir), spec))
        return _dedupe(result)
    if selector == "glob":
        if not spec.pattern:
            raise ValueError("glob selector requires pattern")
        return _glob_nodes(spec.pattern, context.base_dir, spec)
    if selector == "prompt_list":
        return list(spec.items)
    raise ValueError(f"Unsupported selector: {selector}")


def _resolve_ref(value: str, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _discover_nodes(root: Path, spec: SelectorSpec) -> list[str]:
    if not root.exists():
        raise FileNotFoundError(f"Selector root not found: {root}")
    candidates = [root] + list(root.rglob("*")) if spec.recursive else [root] + list(root.iterdir())
    result: list[str] = []
    for candidate in sorted(candidates):
        if not candidate.is_dir():
            continue
        if _excluded(candidate, spec):
            continue
        if _has_node_file(candidate, spec.node_files):
            result.append(str(candidate))
    if spec.shuffle:
        import random

        random.shuffle(result)
    if spec.limit is not None:
        result = result[: spec.limit]
    return _dedupe(result)


def _glob_nodes(pattern: str, base_dir: Path, spec: SelectorSpec) -> list[str]:
    matches = sorted(base_dir.glob(pattern) if not Path(pattern).is_absolute() else Path().glob(pattern))
    result = [str(path.parent if path.is_file() else path) for path in matches]
    result = _dedupe(result)
    if spec.limit is not None:
        result = result[: spec.limit]
    return result


def _has_node_file(path: Path, node_files: list[str]) -> bool:
    return any((path / name).exists() for name in node_files)


def _excluded(path: Path, spec: SelectorSpec) -> bool:
    names = set(spec.exclude.get("names") or [])
    if path.name in names:
        return True
    patterns = [str(item) for item in spec.exclude.get("paths") or []]
    return any(path.match(pattern) for pattern in patterns)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
```

- [ ] **Step 5: 导出新对象**

```python
# src/tags_machine_core/batch/__init__.py
from .selectors import SelectorContext, expand_selector
from .spec_reader import load_batch_spec

__all__ = [
    # keep existing names from Task 1
    "SelectorContext",
    "expand_selector",
    "load_batch_spec",
]
```

When editing `__init__.py`, append these imports and names to the existing exports instead of replacing Task 1 exports.

- [ ] **Step 6: 运行 selector 测试**

Run:

```bash
uv run pytest tests/test_batch_selectors.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/batch/spec_reader.py src/tags_machine_core/batch/selectors.py src/tags_machine_core/batch/__init__.py tests/test_batch_selectors.py
git commit -m "Add batch selectors"
```

## Task 3: BatchPlanner 与 manifest 初始写出

**Files:**
- Create: `src/tags_machine_core/batch/planner.py`
- Create: `src/tags_machine_core/batch/manifest.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_planner.py`

- [ ] **Step 1: 写 planner 测试**

```python
# tests/test_batch_planner.py
from pathlib import Path

from tags_machine_core.batch.models import BatchSpec
from tags_machine_core.batch.planner import BatchPlanner


def test_prompt_list_planner_creates_full_prompt_tasks(tmp_path: Path):
    spec = BatchSpec.model_validate(
        {
            "schema": "tags-machine-core.batch/v1",
            "name": "prompt-smoke",
            "output_root": str(tmp_path / "outputs"),
            "defaults": {"artist": "20260412", "composer": "full", "nt": 1},
            "select": {
                "prompts": [
                    {
                        "selector": "prompt_list",
                        "items": [{"id": "p1", "prompt": "1girl, standing"}],
                    }
                ]
            },
            "expand": {"mode": "prompt_list"},
        }
    )

    tasks = BatchPlanner(base_dir=tmp_path).plan(spec)

    assert len(tasks) == 1
    assert tasks[0].id.startswith("0001_p1_20260412")
    assert tasks[0].composer == "full"
    assert tasks[0].prompt == "1girl, standing"
    assert tasks[0].render.artist == "20260412"


def test_product_planner_expands_character_action_artist(tmp_path: Path):
    character = tmp_path / "characters" / "homura"
    action = tmp_path / "actions" / "standing"
    character.mkdir(parents=True)
    action.mkdir(parents=True)
    (character / "tags.txt").write_text("akemi_homura\n", encoding="utf-8")
    (action / "tags.txt").write_text("standing\n", encoding="utf-8")
    spec = BatchSpec.model_validate(
        {
            "schema": "tags-machine-core.batch/v1",
            "name": "product",
            "output_root": str(tmp_path / "outputs"),
            "defaults": {"artist": "20260412", "composer": "agent"},
            "select": {
                "characters": [{"selector": "explicit", "refs": [str(character)]}],
                "actions": [{"selector": "explicit", "refs": [str(action)]}],
                "artists": [{"selector": "explicit", "refs": ["20260412"]}],
            },
            "expand": {"mode": "product"},
        }
    )

    tasks = BatchPlanner(base_dir=tmp_path).plan(spec)

    assert len(tasks) == 1
    assert [node.role for node in tasks[0].nodes] == ["character", "action", "artist"]
    assert tasks[0].composer == "agent"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_planner.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tags_machine_core.batch.planner'
```

- [ ] **Step 3: 实现 planner**

```python
# src/tags_machine_core/batch/planner.py
from __future__ import annotations

import hashlib
import itertools
import re
from pathlib import Path
from typing import Any

from .models import BatchSpec, BatchTask, NodeRef, RenderOptions
from .selectors import SelectorContext, expand_selector


class BatchPlanner:
    def __init__(self, *, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def plan(self, spec: BatchSpec) -> list[BatchTask]:
        if spec.expand.mode == "prompt_list":
            tasks = self._plan_prompt_list(spec)
        elif spec.expand.mode == "product":
            tasks = self._plan_product(spec)
        else:
            raise ValueError(f"Unsupported expand mode for MVP: {spec.expand.mode}")
        if spec.expand.max_tasks is not None:
            tasks = tasks[: spec.expand.max_tasks]
        return tasks

    def _plan_prompt_list(self, spec: BatchSpec) -> list[BatchTask]:
        prompts = self._select("prompt", spec.select.prompts, spec)
        tasks: list[BatchTask] = []
        for index, item in enumerate(prompts, start=1):
            prompt_id = str(item.get("id") or f"prompt_{index:04d}")
            artist = spec.defaults.artist
            task_id = _task_id(index, [prompt_id, artist or "no_artist"])
            tasks.append(
                BatchTask(
                    id=task_id,
                    index=index - 1,
                    composer="full",
                    prompt=str(item.get("prompt") or ""),
                    negative=item.get("negative"),
                    render=_render_options(spec),
                    output={"task_dir": _task_dir(spec, task_id)},
                    source={"selected_by": ["prompt_list"]},
                )
            )
        return tasks

    def _plan_product(self, spec: BatchSpec) -> list[BatchTask]:
        characters = self._select("character", spec.select.characters, spec)
        actions = self._select("action", spec.select.actions, spec)
        artists = self._select("artist", spec.select.artists, spec) or [spec.defaults.artist]
        tasks: list[BatchTask] = []
        for index, (character, action, artist) in enumerate(
            itertools.product(characters or [None], actions or [None], artists or [None]),
            start=1,
        ):
            nodes = []
            labels = []
            if character:
                nodes.append(NodeRef(role="character", ref=str(character), index=0))
                labels.append(Path(str(character)).name)
            if action:
                nodes.append(NodeRef(role="action", ref=str(action), index=0))
                labels.append(Path(str(action)).name)
            if artist:
                nodes.append(NodeRef(role="artist", ref=str(artist), index=0))
                labels.append(Path(str(artist)).name)
            task_id = _task_id(index, labels or ["task"])
            render = _render_options(spec)
            render.artist = str(artist) if artist else render.artist
            tasks.append(
                BatchTask(
                    id=task_id,
                    index=index - 1,
                    composer=spec.defaults.composer,
                    nodes=nodes,
                    render=render,
                    output={"task_dir": _task_dir(spec, task_id)},
                    source={"selected_by": ["product"]},
                )
            )
        return tasks

    def _select(self, role: str, selectors: list[Any], spec: BatchSpec) -> list[Any]:
        context = SelectorContext(base_dir=self.base_dir, collections=spec.collections)
        values: list[Any] = []
        for selector in selectors:
            values.extend(expand_selector(role=role, spec=selector, context=context))
        return values


def _render_options(spec: BatchSpec) -> RenderOptions:
    return RenderOptions(
        backend=spec.defaults.backend,
        artist=spec.defaults.artist,
        nt=spec.defaults.nt,
        resolution=spec.defaults.resolution,
        width=spec.defaults.width,
        height=spec.defaults.height,
        model=spec.defaults.model,
        image_format=spec.defaults.image_format,
        params=dict(spec.defaults.params),
    )


def _task_dir(spec: BatchSpec, task_id: str) -> str:
    return str(Path(spec.output_root) / spec.name / "tasks" / task_id)


def _task_id(index: int, parts: list[str]) -> str:
    slug = "_".join(_slug(part) for part in parts if part)
    if len(slug) > 80:
        digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:70]}_{digest}"
    return f"{index:04d}_{slug or 'task'}"


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value.strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "item"
```

- [ ] **Step 4: 实现 manifest 基础写入**

```python
# src/tags_machine_core/batch/manifest.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tags_machine_core.json_tools import sanitize_json_for_display

from .models import BatchTask, ManifestEntry


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_initial_manifest(run_dir: str | Path, tasks: list[BatchTask]) -> Path:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for task in tasks:
            task_path = Path(task.output.task_dir) / "task.json"
            status_path = Path(task.output.task_dir) / "status.json"
            entry = ManifestEntry(
                task_id=task.id,
                status="pending",
                attempt=0,
                task_path=str(task_path),
                status_path=str(status_path),
                updated_at=now_iso(),
            )
            f.write(json.dumps(entry.model_dump(mode="json", by_alias=True), ensure_ascii=False) + "\n")
    write_index(root, tasks)
    return manifest_path


def write_index(run_dir: str | Path, tasks: list[BatchTask]) -> Path:
    path = Path(run_dir) / "index.json"
    data = {
        "schema": "tags-machine-core.batch-index/v1",
        "tasks": [
            {"id": task.id, "status": "pending", "task_dir": task.output.task_dir}
            for task in tasks
        ],
    }
    path.write_text(
        json.dumps(sanitize_json_for_display(data, full=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
```

- [ ] **Step 5: 导出 planner/manifest**

Update `src/tags_machine_core/batch/__init__.py` by adding:

```python
from .manifest import write_initial_manifest
from .planner import BatchPlanner

__all__ += [
    "BatchPlanner",
    "write_initial_manifest",
]
```

- [ ] **Step 6: 运行测试**

Run:

```bash
uv run pytest tests/test_batch_planner.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/batch/planner.py src/tags_machine_core/batch/manifest.py src/tags_machine_core/batch/__init__.py tests/test_batch_planner.py
git commit -m "Add batch planner"
```

## Task 4: Archive 与 Report

**Files:**
- Create: `src/tags_machine_core/batch/archive.py`
- Create: `src/tags_machine_core/batch/report.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_manifest_archive_report.py`

- [ ] **Step 1: 写 archive/report 测试**

```python
# tests/test_batch_manifest_archive_report.py
import json
from pathlib import Path

from tags_machine_core.batch.archive import BatchArchive
from tags_machine_core.batch.models import BatchTask, RenderOptions
from tags_machine_core.batch.report import write_report


def _task(tmp_path: Path) -> BatchTask:
    return BatchTask(
        id="0001_test",
        index=0,
        composer="full",
        prompt="1girl",
        render=RenderOptions(artist="20260412", nt=1),
        output={"task_dir": str(tmp_path / "tasks" / "0001_test")},
    )


def test_archive_writes_task_status_and_artifacts(tmp_path: Path):
    task = _task(tmp_path)
    archive = BatchArchive()

    archive.write_task(task)
    archive.write_status(task, status="succeeded", attempt=1, image_paths=["image.png"])
    archive.write_json(task, "generation_result.json", {"images": [{"path": "image.png"}]})

    assert (Path(task.output.task_dir) / "task.json").exists()
    status = json.loads((Path(task.output.task_dir) / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["image_paths"] == ["image.png"]


def test_report_lists_images_and_counts(tmp_path: Path):
    report_path = write_report(
        run_dir=tmp_path,
        entries=[
            {
                "task_id": "0001_test",
                "status": "succeeded",
                "image_paths": ["image.png"],
                "error": None,
            }
        ],
    )

    text = report_path.read_text(encoding="utf-8")
    assert "succeeded: 1" in text
    assert "image.png" in text
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_manifest_archive_report.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tags_machine_core.batch.archive'
```

- [ ] **Step 3: 实现 archive**

```python
# src/tags_machine_core/batch/archive.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tags_machine_core.json_tools import sanitize_json_for_display

from .manifest import now_iso
from .models import BatchStatus, BatchTask


class BatchArchive:
    def write_task(self, task: BatchTask) -> Path:
        task_dir = Path(task.output.task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / "task.json"
        self._write_json(path, task.model_dump(mode="json", by_alias=True))
        return path

    def write_status(
        self,
        task: BatchTask,
        *,
        status: BatchStatus,
        attempt: int,
        image_paths: list[str] | None = None,
        error: str | None = None,
    ) -> Path:
        path = Path(task.output.task_dir) / "status.json"
        payload = {
            "schema": "tags-machine-core.batch-task-status/v1",
            "task_id": task.id,
            "status": status,
            "attempt": attempt,
            "image_paths": image_paths or [],
            "error": error,
            "updated_at": now_iso(),
        }
        self._write_json(path, payload)
        return path

    def write_json(self, task: BatchTask, filename: str, value: Any) -> Path:
        path = Path(task.output.task_dir) / filename
        self._write_json(path, value)
        return path

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(sanitize_json_for_display(value, full=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 4: 实现 report**

```python
# src/tags_machine_core/batch/report.py
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def write_report(run_dir: str | Path, entries: list[dict[str, Any]]) -> Path:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    counts = Counter(str(entry.get("status")) for entry in entries)
    json_path = root / "report.json"
    json_path.write_text(
        json.dumps({"counts": dict(counts), "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path = root / "report.md"
    lines = ["# Batch Report", ""]
    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")
    lines.append("")
    lines.append("| Task | Status | Images | Error |")
    lines.append("| --- | --- | --- | --- |")
    for entry in entries:
        images = "<br>".join(str(path) for path in entry.get("image_paths") or [])
        error = str(entry.get("error") or "")
        lines.append(f"| `{entry.get('task_id')}` | `{entry.get('status')}` | {images} | {error} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path
```

- [ ] **Step 5: 导出 archive/report**

Update `src/tags_machine_core/batch/__init__.py` by adding:

```python
from .archive import BatchArchive
from .report import write_report

__all__ += [
    "BatchArchive",
    "write_report",
]
```

- [ ] **Step 6: 运行测试**

Run:

```bash
uv run pytest tests/test_batch_manifest_archive_report.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/batch/archive.py src/tags_machine_core/batch/report.py src/tags_machine_core/batch/__init__.py tests/test_batch_manifest_archive_report.py
git commit -m "Add batch archive and report"
```

## Task 5: BatchExecutor 与 BatchRunner

**Files:**
- Create: `src/tags_machine_core/batch/executor.py`
- Create: `src/tags_machine_core/batch/runner.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_executor_runner.py`

- [ ] **Step 1: 写 executor/runner 测试**

```python
# tests/test_batch_executor_runner.py
from pathlib import Path

from tags_machine_core.batch.executor import BatchExecutor, BatchExecutionResult
from tags_machine_core.batch.models import BatchTask, RenderOptions
from tags_machine_core.batch.runner import BatchRunner


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, task):
        self.calls.append(task.id)
        return BatchExecutionResult(
            status="succeeded",
            image_paths=[f"{task.id}.png"],
            artifacts={"generation_result": {"images": [{"path": f"{task.id}.png"}]}},
        )


def _task(tmp_path: Path, task_id: str) -> BatchTask:
    return BatchTask(
        id=task_id,
        index=0,
        composer="full",
        prompt="1girl",
        render=RenderOptions(artist="20260412", nt=1),
        output={"task_dir": str(tmp_path / "tasks" / task_id)},
    )


def test_runner_executes_tasks_and_writes_status(tmp_path: Path):
    fake = FakeExecutor()
    runner = BatchRunner(executor=fake)

    result = runner.run_tasks(run_dir=tmp_path, tasks=[_task(tmp_path, "t1")])

    assert result["counts"]["succeeded"] == 1
    assert fake.calls == ["t1"]
    assert (tmp_path / "tasks" / "t1" / "status.json").exists()


def test_batch_execution_result_requires_agent_status():
    result = BatchExecutionResult(
        status="requires_agent",
        image_paths=[],
        artifacts={"agent_task": {"id": "agent-task"}},
    )

    assert result.status == "requires_agent"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_executor_runner.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tags_machine_core.batch.executor'
```

- [ ] **Step 3: 实现 executor 结果类型和骨架**

```python
# src/tags_machine_core/batch/executor.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tags_machine_core.composers import AgentCompositionRequired
from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GenerationResult
from tags_machine_core.execution import execute_render_request
from tags_machine_core.nodes import NodeReader, NovelAIArtistRepository, ResolvedNode, ResolvedNodeSet
from tags_machine_core.services import GenerationService

from .models import BatchStatus, BatchTask


@dataclass
class BatchExecutionResult:
    status: BatchStatus
    image_paths: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BatchExecutor:
    def __init__(
        self,
        *,
        service: GenerationService | None = None,
        node_reader: NodeReader | None = None,
    ):
        self.service = service or GenerationService()
        self.node_reader = node_reader or NodeReader()

    def execute(self, task: BatchTask, *, config: AppConfig | None = None) -> BatchExecutionResult:
        try:
            bundle, resolved_nodes, artist_node = self._compose(task, config=config)
            request = self.service.build_render_request(
                bundle,
                backend=task.render.backend,
                seed=task.render.seed,
                artist=artist_node,
                resolved_nodes=resolved_nodes,
                width=task.render.width or 1024,
                height=task.render.height or 1024,
                model=task.render.model,
                params={**task.render.params, "n_samples": task.render.nt},
            )
            generation = execute_render_request(request, config=config)
            return BatchExecutionResult(
                status="succeeded",
                image_paths=_image_paths(generation),
                artifacts={
                    "prompt_bundle": bundle,
                    "render_request": request,
                    "generation_result": generation,
                },
            )
        except AgentCompositionRequired as exc:
            return BatchExecutionResult(
                status="requires_agent",
                artifacts={"agent_task": exc.task},
            )
        except Exception as exc:
            return BatchExecutionResult(status="failed", error=str(exc))

    def _compose(
        self,
        task: BatchTask,
        *,
        config: AppConfig | None,
    ):
        resolved_nodes = self._resolved_nodes(task, config=config)
        artist_node = resolved_nodes.first("artist").node if resolved_nodes.first("artist") else None
        if task.composer == "full":
            bundle = self.service.compose_full_prompt(
                prompt=task.prompt or "",
                negative=task.negative or "",
                prompt_policy=task.policy or None,
            )
            return bundle, resolved_nodes, artist_node
        if task.composer == "agent":
            bundle = self.service.compose_resolved_nodes_with_agent(
                resolved_nodes,
                extra_prompt=task.extra_prompt,
                negative=task.negative or "",
            )
            return bundle, resolved_nodes, artist_node
        bundle = self.service.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=task.extra_prompt,
            negative=task.negative or "",
            prompt_policy=task.policy or None,
        )
        return bundle, resolved_nodes, artist_node

    def _resolved_nodes(self, task: BatchTask, *, config: AppConfig | None) -> ResolvedNodeSet:
        items = []
        artist_repo = None
        if config is not None:
            artist_repo = NovelAIArtistRepository(config.legacy.design_root)
        for node in task.nodes:
            if node.role == "artist" and artist_repo is not None:
                document = artist_repo.load_node(node.ref)
            else:
                document = self.node_reader.read(node.ref)
            items.append(ResolvedNode(role=node.role, ref=node.ref, node=document, index=node.index))
        return ResolvedNodeSet(items)


def _image_paths(result: GenerationResult) -> list[str]:
    return [str(image.path) for image in result.images if image.path]
```

- [ ] **Step 4: 实现 runner**

```python
# src/tags_machine_core/batch/runner.py
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tags_machine_core.config import AppConfig

from .archive import BatchArchive
from .executor import BatchExecutor
from .models import BatchTask
from .report import write_report


class BatchRunner:
    def __init__(
        self,
        *,
        executor: BatchExecutor | Any | None = None,
        archive: BatchArchive | None = None,
    ):
        self.executor = executor or BatchExecutor()
        self.archive = archive or BatchArchive()

    def run_tasks(
        self,
        *,
        run_dir: str | Path,
        tasks: list[BatchTask],
        config: AppConfig | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        root = Path(run_dir)
        entries: list[dict[str, Any]] = []
        selected = tasks[:limit] if limit is not None else tasks
        for task in selected:
            self.archive.write_task(task)
            self.archive.write_status(task, status="running", attempt=1)
            result = self.executor.execute(task) if config is None else self.executor.execute(task, config=config)
            if result.status == "succeeded":
                self._write_success_artifacts(task, result.artifacts)
            if result.status == "requires_agent":
                self.archive.write_json(task, "agent_task.json", result.artifacts.get("agent_task"))
            self.archive.write_status(
                task,
                status=result.status,
                attempt=1,
                image_paths=result.image_paths,
                error=result.error,
            )
            entries.append(
                {
                    "task_id": task.id,
                    "status": result.status,
                    "image_paths": result.image_paths,
                    "error": result.error,
                }
            )
        write_report(root, entries)
        return {"counts": dict(Counter(entry["status"] for entry in entries)), "entries": entries}

    def _write_success_artifacts(self, task: BatchTask, artifacts: dict[str, Any]) -> None:
        mapping = {
            "prompt_bundle": "prompt_bundle.json",
            "render_request": "render_request.json",
            "generation_result": "generation_result.json",
        }
        for key, filename in mapping.items():
            if key in artifacts:
                self.archive.write_json(task, filename, artifacts[key])
```

- [ ] **Step 5: 导出 executor/runner**

Update `src/tags_machine_core/batch/__init__.py`:

```python
from .executor import BatchExecutionResult, BatchExecutor
from .runner import BatchRunner

__all__ += [
    "BatchExecutionResult",
    "BatchExecutor",
    "BatchRunner",
]
```

- [ ] **Step 6: 运行测试**

Run:

```bash
uv run pytest tests/test_batch_executor_runner.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/batch/executor.py src/tags_machine_core/batch/runner.py src/tags_machine_core/batch/__init__.py tests/test_batch_executor_runner.py
git commit -m "Add batch runner execution skeleton"
```

## Task 6: CLI `plan-batch`、`run-batch`、`inspect-batch`

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_batch_cli.py`
- Create: `examples/batches/prompt_list_20260412.yaml`

- [ ] **Step 1: 写 CLI 测试**

```python
# tests/test_batch_cli.py
import json
from pathlib import Path

from tags_machine_core.cli import main


def test_plan_batch_writes_manifest(tmp_path: Path, capsys):
    spec = tmp_path / "batch.yaml"
    spec.write_text(
        "schema: tags-machine-core.batch/v1\n"
        "name: prompt-smoke\n"
        f"output_root: {tmp_path.as_posix()}/outputs\n"
        "defaults:\n"
        "  composer: full\n"
        "  artist: 20260412\n"
        "select:\n"
        "  prompts:\n"
        "    - selector: prompt_list\n"
        "      items:\n"
        "        - id: p1\n"
        "          prompt: 1girl, standing\n"
        "expand:\n"
        "  mode: prompt_list\n",
        encoding="utf-8",
    )

    code = main(["plan-batch", str(spec), "--full"])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task_count"] == 1
    assert Path(data["manifest_path"]).exists()
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run pytest tests/test_batch_cli.py::test_plan_batch_writes_manifest -q
```

Expected:

```text
SystemExit: 2
```

`argparse` should reject unknown command `plan-batch`.

- [ ] **Step 3: 在 `cli.py` 增加命令函数**

Add imports near existing imports:

```python
from tags_machine_core.batch import BatchPlanner, BatchRunner, load_batch_spec, write_initial_manifest
```

Add functions near other `cmd_*` functions:

```python
def cmd_plan_batch(args) -> int:
    spec_path = Path(args.batch_spec)
    spec = load_batch_spec(spec_path)
    planner = BatchPlanner(base_dir=spec_path.parent)
    tasks = planner.plan(spec)
    run_dir = Path(args.output_root or spec.output_root) / spec.name
    manifest_path = write_initial_manifest(run_dir, tasks)
    print_json(
        {
            "schema": "tags-machine-core.plan-batch-result/v1",
            "batch": spec.name,
            "task_count": len(tasks),
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
        },
        full=args.full,
    )
    return 0


def cmd_run_batch(args) -> int:
    spec_path = Path(args.batch_spec)
    config = _load_command_config(args.config) if args.config else None
    spec = load_batch_spec(spec_path)
    planner = BatchPlanner(base_dir=spec_path.parent)
    tasks = planner.plan(spec)
    run_dir = Path(args.output_root or spec.output_root) / spec.name
    write_initial_manifest(run_dir, tasks)
    result = BatchRunner().run_tasks(
        run_dir=run_dir,
        tasks=tasks,
        config=config,
        limit=args.limit,
    )
    print_json(
        {
            "schema": "tags-machine-core.run-batch-result/v1",
            "batch": spec.name,
            "run_dir": str(run_dir),
            **result,
        },
        full=args.full,
    )
    return 0
```

- [ ] **Step 4: 在 parser 中注册命令**

Inside `build_parser()`, near other subparsers:

```python
    plan_batch = subparsers.add_parser(
        "plan-batch",
        parents=[output_parent],
        help="Plan a batch generation run without calling NovelAI",
    )
    plan_batch.add_argument("batch_spec")
    plan_batch.add_argument("--output-root")
    plan_batch.set_defaults(func=cmd_plan_batch)

    run_batch = subparsers.add_parser(
        "run-batch",
        parents=[output_parent],
        help="Run a batch generation spec",
    )
    run_batch.add_argument("batch_spec")
    run_batch.add_argument("--config", help="Runtime config for real generation")
    run_batch.add_argument("--output-root")
    run_batch.add_argument("--limit", type=int)
    run_batch.set_defaults(func=cmd_run_batch)
```

- [ ] **Step 5: 新增示例 spec**

```yaml
# examples/batches/prompt_list_20260412.yaml
schema: tags-machine-core.batch/v1
name: prompt-list-20260412
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: full
  artist: 20260412
  nt: 1
  resolution: square
  model: nai-diffusion-4-5-full

select:
  prompts:
    - selector: prompt_list
      items:
        - id: standing_001
          prompt: "akemi_homura, 1girl, standing, looking at viewer"
        - id: foot_001
          prompt: "akemi_homura, 1girl, bare feet, foot focus, lower body"

expand:
  mode: prompt_list

run:
  resume: true
```

- [ ] **Step 6: 运行 CLI 测试**

Run:

```bash
uv run pytest tests/test_batch_cli.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/cli.py tests/test_batch_cli.py examples/batches/prompt_list_20260412.yaml
git commit -m "Add batch CLI entrypoints"
```

## Task 7: Resume、PNG 参数归档、report 补强

**Files:**
- Modify: `src/tags_machine_core/batch/manifest.py`
- Modify: `src/tags_machine_core/batch/runner.py`
- Modify: `src/tags_machine_core/batch/archive.py`
- Modify: `src/tags_machine_core/batch/report.py`
- Modify: `src/tags_machine_core/cli.py`
- Test: `tests/test_batch_manifest_archive_report.py`

- [ ] **Step 1: 添加 resume 测试**

Append to `tests/test_batch_manifest_archive_report.py`:

```python
from tags_machine_core.batch.manifest import task_already_succeeded


def test_task_already_succeeded_reads_status_json(tmp_path: Path):
    task = _task(tmp_path)
    archive = BatchArchive()
    archive.write_status(task, status="succeeded", attempt=1, image_paths=["image.png"])

    assert task_already_succeeded(task) is True
```

- [ ] **Step 2: 实现 `task_already_succeeded`**

```python
# src/tags_machine_core/batch/manifest.py
def task_already_succeeded(task: BatchTask) -> bool:
    status_path = Path(task.output.task_dir) / "status.json"
    if not status_path.exists():
        return False
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("status") == "succeeded"
```

Add `BatchTask` import at top:

```python
from .models import BatchTask, ManifestEntry
```

- [ ] **Step 3: 修改 runner 跳过成功任务**

In `src/tags_machine_core/batch/runner.py`, import:

```python
from .manifest import task_already_succeeded
```

Inside `run_tasks()` loop, before writing running status:

```python
            if task_already_succeeded(task):
                entries.append(
                    {
                        "task_id": task.id,
                        "status": "skipped",
                        "image_paths": [],
                        "error": None,
                    }
                )
                continue
```

- [ ] **Step 4: 保存 PNG 参数摘要**

In `BatchRunner._write_success_artifacts()`, after writing `generation_result.json`:

```python
        generation = artifacts.get("generation_result")
        png_info = getattr(generation, "png_info", None)
        if png_info:
            self.archive.write_json(task, "png_params.json", png_info)
```

- [ ] **Step 5: 增加 `inspect-batch` CLI**

Add command function:

```python
def cmd_inspect_batch(args) -> int:
    run_dir = Path(args.run_dir)
    statuses = []
    for status_path in run_dir.glob("tasks/*/status.json"):
        try:
            statuses.append(json.loads(status_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            statuses.append({"status": "failed", "error": f"invalid status json: {status_path}"})
    counts: dict[str, int] = {}
    for item in statuses:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    print_json(
        {
            "schema": "tags-machine-core.inspect-batch-result/v1",
            "run_dir": str(run_dir),
            "counts": counts,
            "tasks": statuses,
        },
        full=args.full,
    )
    return 0
```

Register parser:

```python
    inspect_batch = subparsers.add_parser(
        "inspect-batch",
        parents=[output_parent],
        help="Inspect a batch run directory",
    )
    inspect_batch.add_argument("run_dir")
    inspect_batch.set_defaults(func=cmd_inspect_batch)
```

- [ ] **Step 6: 运行测试**

Run:

```bash
uv run pytest tests/test_batch_manifest_archive_report.py tests/test_batch_executor_runner.py tests/test_batch_cli.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 7: 提交**

```bash
git add src/tags_machine_core/batch/manifest.py src/tags_machine_core/batch/runner.py src/tags_machine_core/batch/archive.py src/tags_machine_core/batch/report.py src/tags_machine_core/cli.py tests/test_batch_manifest_archive_report.py
git commit -m "Add batch resume and inspection"
```

## Task 8: Collection action 示例与真实 NovelAI 业务验收

**Files:**
- Create: `examples/batches/action_folder_20260412.yaml`
- Create: `examples/batches/agent_cache_miss.yaml`
- Modify: `docs/batch_generation_spec_v1.md` if the implemented CLI differs from the spec
- Create: `docs/batch_generation_business_test_YYYYMMDD.md`

- [ ] **Step 1: 新增 action folder 示例**

```yaml
# examples/batches/action_folder_20260412.yaml
schema: tags-machine-core.batch/v1
name: action-folder-20260412
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: agent
  artist: 20260412
  nt: 1
  resolution: random_standard
  model: nai-diffusion-4-5-full

collections:
  actions:
    foot:
      - F:/my_project/new/tags_machine/design/动作改2/st_ft_bare

select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら_魔法少女
  actions:
    - selector: collection
      name: foot
      recursive: true
      limit: 3
  artists:
    - selector: explicit
      refs:
        - 20260412

expand:
  mode: product
  max_tasks: 3

run:
  resume: true
```

- [ ] **Step 2: 新增 agent cache miss 示例**

```yaml
# examples/batches/agent_cache_miss.yaml
schema: tags-machine-core.batch/v1
name: agent-cache-miss
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: agent
  artist: 20260412
  nt: 1
  resolution: square

select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら_魔法少女
  actions:
    - selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_ft_bare
      recursive: true
      limit: 1
  artists:
    - selector: explicit
      refs:
        - 20260412

expand:
  mode: product
```

- [ ] **Step 3: 设置 NovelAI token**

Use the existing local token source without printing the token:

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$token = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
$env:NAI_ACCESS_TOKEN = $token
```

- [ ] **Step 4: 真实跑 prompt list 两张图**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --config configs\local.example.yaml --limit 2 --full
```

Expected:

```text
"schema": "tags-machine-core.run-batch-result/v1"
"succeeded": 2
```

Then inspect:

```powershell
uv run python -m tags_machine_core inspect-batch outputs\batches\prompt-list-20260412 --full
```

Expected:

```text
"succeeded": 2
```

- [ ] **Step 5: 验证 PNG 参数证据**

For each generated task directory:

```powershell
Get-ChildItem outputs\batches\prompt-list-20260412\tasks -Recurse -Filter generation_result.json
Get-ChildItem outputs\batches\prompt-list-20260412\tasks -Recurse -Filter png_params.json
```

Expected:

```text
2 generation_result.json files
2 png_params.json files
```

Open generated images and record visual result manually in the business test document.

- [ ] **Step 6: 跑 action folder / collection 真实图**

Run:

```powershell
uv run python -m tags_machine_core run-batch examples\batches\action_folder_20260412.yaml --config configs\local.example.yaml --limit 3 --full
```

Expected:

```text
At least one task succeeds with a real NovelAI image path.
Cache misses are allowed only if the selected agent tasks have no cached prompt.
```

If all tasks are `requires_agent`, document that selector/planner passed but agent cache needs prompt回填 before true image generation. Then run a prompt-list case as the image-generation gate.

- [ ] **Step 7: 写业务验收文档**

Create `docs/batch_generation_business_test_YYYYMMDD.md`:

```markdown
# Batch Generation 真实出图验收 YYYY-MM-DD

## 设置

- artist: 20260412
- backend: NovelAI
- command: run-batch
- nt: 1

## 结果

| Case | Status | Image | GenerationResult | PNG Params | Visual Result |
| --- | --- | --- | --- | --- | --- |
| prompt-list-20260412 / standing_001 | succeeded | F:/...png | generation_result.json | png_params.json | pass |
| prompt-list-20260412 / foot_001 | succeeded | F:/...png | generation_result.json | png_params.json | pass |

## 结论

- BatchRunner 能真实调用 NovelAI 出图。
- 每个成功任务保存了 GenerationResult 和 PNG 参数。
- report.md 可用于人工验收。
- 未解决问题列在下面。
```

- [ ] **Step 8: 提交**

```bash
git add examples/batches/action_folder_20260412.yaml examples/batches/agent_cache_miss.yaml docs/batch_generation_business_test_YYYYMMDD.md
git commit -m "Validate batch generation with real NovelAI output"
```

## Final Verification Gate

Run focused logic checks:

```bash
uv run pytest tests/test_batch_models.py tests/test_batch_selectors.py tests/test_batch_planner.py tests/test_batch_manifest_archive_report.py tests/test_batch_executor_runner.py tests/test_batch_cli.py -q
```

Expected:

```text
all selected tests passed
```

Run real business check:

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --config configs\local.example.yaml --limit 2 --full
```

Expected:

```text
2 real NovelAI images are generated.
Each succeeded task has generation_result.json and png_params.json.
inspect-batch reports succeeded: 2.
```

If the business check fails because of NovelAI 429/502/timeout, retry according to the batch retry policy and record the final result in the business test document. Do not claim completion without image paths and PNG parameter evidence.

## Implementation Notes

- Keep batch orchestration independent from prompt composition rules.
- Do not add hardcoded legacy formula behavior.
- Do not make AgentComposer pass through PromptPolicyPipeline.
- Do not default to concurrency.
- Keep examples small to avoid Anlas waste.
- Parent `prompt_preset_service.py` bridge can be designed after the core batch CLI is proven with real NovelAI output.
