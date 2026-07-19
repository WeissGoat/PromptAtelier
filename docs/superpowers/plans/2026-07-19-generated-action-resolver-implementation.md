# Generated Action Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `tags_machine_core.tools` 下实现一个可混合扫描旧版图片目录和新版任务归档目录、并优先映射到 `design/动作改2/new` 原始 Action 节点的独立工具。

**Architecture:** 使用 scanner、reader、index、resolver 四层分离输入发现、证据读取、节点索引和映射决策。独立模块 CLI 与主 `tags_machine_core resolve-actions` 子命令复用同一个 `run_cli()` 和公共 Python API，默认输出相对 `design_root` 的去重路径。

**Tech Stack:** Python 3.11、Pillow、标准库 `json/pathlib/argparse/dataclasses`、现有 `TaskArchiveResolver`、Pytest、Ruff。

## Global Constraints

- 不修改旧版图片、新版任务归档、manifest 或 `design` 节点。
- 旧版和新版 evidence 使用同一套映射优先级。
- `new` 原始节点优先，分类目录只作为 `category_fallback`。
- 默认递归扫描并去重任务及任务内图片。
- 默认路径相对 `legacy.design_root`，不打印盘符前缀。
- 业务验收必须运行用户提供的两个真实目录。
- 当前工作区存在大量其他未提交修改，提交必须使用精确暂存或隔离索引。

---

### Task 1: 定义数据模型和 Action 索引

**Files:**
- Create: `src/tags_machine_core/tools/action_resolver/__init__.py`
- Create: `src/tags_machine_core/tools/action_resolver/models.py`
- Create: `src/tags_machine_core/tools/action_resolver/index.py`
- Create: `tests/test_action_resolver_index.py`

**Interfaces:**
- Produces: `ActionEvidence`, `ResolvedAction`, `ScanResult`, `ActionNodeIndex`。
- `ActionNodeIndex.resolve_manifest(...)` 返回唯一 `new` 候选、多个候选或空结果。
- `ActionNodeIndex.category_candidates(...)` 返回实际存在的分类目录。

- [ ] **Step 1: 定义模型**

```python
@dataclass(frozen=True, slots=True)
class ActionEvidence:
    input_path: Path
    source_kind: str
    action: str = ""
    topic: str = ""
    ref: str | None = None
    source_detail: str = ""

@dataclass(frozen=True, slots=True)
class ResolvedAction:
    evidence: ActionEvidence
    status: str
    relative_path: str = ""
    absolute_path: Path | None = None
    reason: str = ""
```

`ResolvedAction.as_dict()` 必须把 `Path` 转成字符串，供 JSON CLI 使用。

- [ ] **Step 2: 实现 manifest 和目录索引**

`ActionNodeIndex` 初始化参数：

```python
ActionNodeIndex(design_root: Path, action_dir_name: str = "动作改2")
```

建立以下映射：

```python
by_dest: dict[str, set[Path]]
by_root_view: dict[tuple[str, str], set[Path]]
by_view: dict[str, set[Path]]
by_name: dict[str, set[Path]]
new_by_name: dict[str, set[Path]]
```

manifest 的 `source` 必须解析到 `action_root/source`，并验证目录存在。所有 key 将 `\` 归一为 `/`，但不改变节点名称大小写和 Unicode。

- [ ] **Step 3: 覆盖索引规则测试**

测试至少包含：

```python
def test_manifest_dest_maps_category_view_to_new_source(tmp_path): ...
def test_root_and_view_name_maps_old_png_metadata(tmp_path): ...
def test_missing_manifest_source_is_not_treated_as_resolved(tmp_path): ...
def test_new_name_match_requires_unique_directory(tmp_path): ...
def test_category_candidates_accept_numeric_prefix(tmp_path): ...
```

- [ ] **Step 4: 运行专项测试**

```powershell
uv run --with pytest pytest tests/test_action_resolver_index.py -q
uv run --with ruff ruff check src/tags_machine_core/tools/action_resolver tests/test_action_resolver_index.py
```

Expected: 全部通过。

---

### Task 2: 实现混合输入扫描和 evidence 读取

**Files:**
- Create: `src/tags_machine_core/tools/action_resolver/scanner.py`
- Create: `src/tags_machine_core/tools/action_resolver/readers.py`
- Create: `tests/test_action_resolver_inputs.py`

**Interfaces:**
- Consumes: Task 1 的 `ActionEvidence`、`ScanResult`。
- Produces: `GeneratedActionInputScanner.scan(inputs) -> ScanResult`。
- Produces: `read_task_evidence(task_dir) -> list[ActionEvidence]`。
- Produces: `read_image_evidence(image_path) -> ActionEvidence`。

- [ ] **Step 1: 实现递归扫描器**

归档标志文件沿用：

```python
ARCHIVE_NAMES = (
    "render_request.json",
    "prompt_bundle.json",
    "generation_result.json",
)
```

扫描器对每个输入执行：

1. 文件输入先尝试 `TaskArchiveResolver.find_task_dir()`。
2. 目录自身包含归档文件则直接记录任务。
3. 普通目录递归查找归档标志文件的父目录。
4. 普通目录递归查找支持图片。
5. 删除位于已发现任务目录下的图片。
6. 以 `resolve().casefold()` 去重。

- [ ] **Step 2: 实现新版任务 reader**

调用：

```python
context = TaskArchiveResolver().resolve_one(task_dir)
resources = context.resources_for("action")
```

每个 resource 转成 `ActionEvidence`：

```python
ActionEvidence(
    input_path=context.task_dir,
    source_kind="core_task",
    action=resource.id or Path(resource.ref or "").name,
    topic=_topic_from_ref(resource.ref),
    ref=resource.ref,
    source_detail=resource.source,
)
```

支持多个 Action resource，并按 role/index/ref 去重。

- [ ] **Step 3: 实现旧图片 reader**

使用 Pillow 打开图片并建立大小写不敏感 metadata：

```python
lowered = {str(key).casefold(): value for key, value in image.info.items()}
```

优先读取顶层 `action/topic`，缺失时解析 `comment` JSON。错误返回带 `_error` 的读取结果，由上层转换为 `read_error`。

- [ ] **Step 4: 覆盖扫描和 reader 测试**

测试至少包含：

```python
def test_scanner_deduplicates_task_images(tmp_path): ...
def test_scanner_keeps_standalone_legacy_images(tmp_path): ...
def test_image_reader_uses_top_level_action_and_topic(tmp_path): ...
def test_image_reader_falls_back_to_comment_json(tmp_path): ...
def test_task_reader_extracts_action_node_refs(tmp_path): ...
```

- [ ] **Step 5: 运行专项测试**

```powershell
uv run --with pytest pytest tests/test_action_resolver_inputs.py -q
uv run --with ruff ruff check src/tags_machine_core/tools/action_resolver tests/test_action_resolver_inputs.py
```

Expected: 全部通过。

---

### Task 3: 实现统一解析器和公共 Python API

**Files:**
- Create: `src/tags_machine_core/tools/action_resolver/resolver.py`
- Modify: `src/tags_machine_core/tools/action_resolver/__init__.py`
- Create: `tests/test_action_resolver.py`

**Interfaces:**
- Consumes: `GeneratedActionInputScanner`、readers、`ActionNodeIndex`。
- Produces: `GeneratedActionResolver.resolve(evidence) -> ResolvedAction`。
- Produces: `resolve_generated_actions(inputs, design_root) -> list[ResolvedAction]`。

- [ ] **Step 1: 实现阶段前缀和路径归一化**

```python
PHASE_PREFIXES = ("00_start", "01_pre", "02_core", "03_cum", "04_post")

def strip_phase_prefix(value: str) -> str: ...
def normalize_relative_path(value: str) -> str: ...
```

- [ ] **Step 2: 实现统一映射顺序**

严格按 spec 顺序实现：

1. 直接 `new` ref。
2. manifest `dest`。
3. manifest `root + view_name`。
4. manifest 唯一 `view_name/name`。
5. 去阶段前缀后唯一匹配 `new`。
6. 分类目录数字前缀匹配。
7. 分类目录 fallback。
8. ambiguous/unresolved。

返回相对路径使用：

```python
absolute.resolve().relative_to(design_root.resolve()).as_posix()
```

Windows 展示时将 `/` 转成 `\`，JSON 中保留平台原生 `str(Path(...))` 风格或明确的相对字符串；默认 paths 模式必须打印 `动作改2/new/...`。

- [ ] **Step 3: 实现公共入口**

```python
def resolve_generated_actions(
    inputs: Sequence[str | Path],
    *,
    design_root: str | Path,
) -> list[ResolvedAction]:
    scan = GeneratedActionInputScanner().scan(inputs)
    index = ActionNodeIndex(Path(design_root))
    resolver = GeneratedActionResolver(index)
    ...
```

扫描错误和 reader 错误必须转换成 `ResolvedAction(status="read_error")`，不能在 Python API 内打印或退出。

- [ ] **Step 4: 覆盖统一解析规则测试**

测试至少包含：

```python
def test_new_task_category_ref_maps_to_new_source(tmp_path): ...
def test_old_png_topic_action_maps_to_new_source(tmp_path): ...
def test_category_directory_is_returned_as_fallback(tmp_path): ...
def test_duplicate_images_collapse_to_one_default_result(tmp_path): ...
def test_ambiguous_new_name_does_not_guess(tmp_path): ...
```

- [ ] **Step 5: 运行专项测试**

```powershell
uv run --with pytest pytest tests/test_action_resolver.py -q
uv run --with ruff ruff check src/tags_machine_core/tools/action_resolver tests/test_action_resolver.py
```

Expected: 全部通过。

---

### Task 4: 接入独立 CLI 和主 CLI

**Files:**
- Create: `src/tags_machine_core/tools/action_resolver/cli.py`
- Create: `src/tags_machine_core/tools/action_resolver/__main__.py`
- Modify: `src/tags_machine_core/cli.py`
- Create: `tests/test_action_resolver_cli.py`

**Interfaces:**
- Produces: `add_action_resolver_subparser(...)`。
- Produces: `run_cli(argv=None) -> int`。
- Produces: 主命令 `resolve-actions`。

- [ ] **Step 1: 实现配置解析**

优先级：

```text
--design-root
--config -> legacy.design_root
configs/local.yaml
configs/local.example.yaml
```

独立 CLI 根据 `cli.py` 的项目位置定位 `configs`。主 CLI 和独立 CLI 必须调用同一个解析函数。

- [ ] **Step 2: 实现输出模式**

默认 paths：

```python
for result in deduplicate_results(results):
    if result.relative_path:
        print(str(Path(result.relative_path)))
```

`--table` 输出列：

```text
status source action topic path reason
```

`--json` 输出 `ResolvedAction.as_dict()` 数组。`--per-input` 控制是否聚合；`--strict` 按 spec 返回 1。

- [ ] **Step 3: 添加两个入口**

独立入口：

```python
if __name__ == "__main__":
    raise SystemExit(run_cli())
```

主 CLI：

```python
from tags_machine_core.tools.action_resolver.cli import add_action_resolver_subparser

add_action_resolver_subparser(subparsers, output_parent=output_parent)
```

- [ ] **Step 4: 覆盖 CLI 测试**

测试至少包含：

```python
def test_main_parser_accepts_multiple_inputs(): ...
def test_paths_output_is_relative_to_design_root(): ...
def test_json_output_contains_status_and_reason(): ...
def test_strict_returns_one_for_category_fallback(): ...
def test_standalone_and_main_cli_use_same_handler(): ...
```

- [ ] **Step 5: 运行专项测试**

```powershell
uv run --with pytest pytest tests/test_action_resolver_cli.py -q
uv run --with ruff ruff check src/tags_machine_core/tools/action_resolver src/tags_machine_core/cli.py tests/test_action_resolver_cli.py
```

Expected: 全部通过。

---

### Task 5: 文档和真实业务验收

**Files:**
- Create: `docs/action_resolver_readme.md`
- Create: `docs/action_resolver_business_acceptance_20260719.md`
- Modify: `docs/superpowers/specs/2026-07-19-generated-action-resolver-design.md` only if implementation reveals a necessary clarification.

**Interfaces:**
- Documents: 安装前提、两种入口、参数、状态、输出结构和真实示例。

- [ ] **Step 1: 写使用文档**

文档必须包含：

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

说明默认递归、默认去重、design-root 相对路径、fallback 和 strict。

- [ ] **Step 2: 运行完整专项测试和 Ruff**

```powershell
uv run --with pytest pytest `
  tests/test_action_resolver_index.py `
  tests/test_action_resolver_inputs.py `
  tests/test_action_resolver.py `
  tests/test_action_resolver_cli.py -q

uv run --with ruff ruff check `
  src/tags_machine_core/tools/action_resolver `
  src/tags_machine_core/cli.py `
  tests/test_action_resolver_*.py
```

Expected: 全部通过。

- [ ] **Step 3: 运行旧版真实目录验收**

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961"
```

Expected:

```text
动作改2\new\银发萝莉事后M字开腿
```

- [ ] **Step 4: 运行新版真实目录验收**

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

Expected:

```text
动作改2\new\萝莉躺床撩裙露内
```

- [ ] **Step 5: 运行混合目录和结构化验收**

```powershell
uv run python -m tags_machine_core.tools.action_resolver `
  --json `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

Expected: 两条 `resolved_new` 结果，路径分别为两个目标 Action，旧目录三张重复 PNG 不产生三条默认聚合结果。

- [ ] **Step 6: 记录业务验收报告**

记录命令、实际输出、状态、输入文件数量和映射理由，不复制大段 PNG metadata。

- [ ] **Step 7: 精确提交功能**

只提交 action resolver 模块、对应测试、CLI 的单一接入 hunk 和两份文档。不得提交工作区其他 Batch、Web、Policy 或 ArtistInputFilter 改动。
