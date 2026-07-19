# Batch 每日输出目录实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Batch YAML 与 `--output-dir` 支持 `{date}`，并保证 fresh、resume、CLI 与 Web 使用一致的每日输出目录语义。

**Architecture:** 在 Batch 包内新增无状态路径模板解析器，使用一次注入的本地时间将 `{date}` 展开为 `YYYYMMDD`。CLI 和 Web 入口在确定原始路径优先级后调用同一个解析器；恢复任务继续优先读取 `batch_source.json` 中已经解析的绝对路径。

**Tech Stack:** Python 3.11+、Pydantic、pathlib、pytest、现有 Batch CLI/Web 服务。

## Global Constraints

- 仅在 `refactor` 子模块开发，不修改旧 `tags_machine`。
- `{date}` 固定展开为服务器本地日期的 `YYYYMMDD`。
- 不含 `{date}` 的路径行为必须保持不变。
- 同一次运行只解析一次日期；跨午夜不切换输出目录。
- `resume-batch` 必须继续使用首次运行归档的已解析输出目录。
- 注释使用中文。
- 验收以 Mock Batch 的最终任务参数和归档结果为主，不触发 NovelAI。

---

### Task 1: 通用 Batch 路径模板解析器

**Files:**
- Create: `src/tags_machine_core/batch/paths.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Consumes: 原始 `str | Path` 路径和可选 `datetime`。
- Produces: `resolve_batch_output_path(value: str | Path, *, now: datetime | None = None) -> Path`。

- [ ] **Step 1: 写路径模板行为测试**

```python
def test_resolve_batch_output_path_expands_local_date():
    now = datetime(2026, 7, 12, 23, 59, 59)
    assert resolve_batch_output_path("G:/ai_auto/{date}", now=now) == Path(
        "G:/ai_auto/20260712"
    )


def test_resolve_batch_output_path_keeps_plain_path():
    assert resolve_batch_output_path("G:/ai_auto/fixed") == Path("G:/ai_auto/fixed")
```

- [ ] **Step 2: 运行定向测试并确认失败**

Run: `uv run --with pytest --with-editable . pytest tests/test_batch_output_paths.py -q`

Expected: FAIL，原因是 `resolve_batch_output_path` 尚不存在。

- [ ] **Step 3: 实现最小路径解析器并导出接口**

```python
from datetime import datetime
from pathlib import Path


def resolve_batch_output_path(
    value: str | Path,
    *,
    now: datetime | None = None,
) -> Path:
    resolved_now = now or datetime.now()
    return Path(str(value).replace("{date}", resolved_now.strftime("%Y%m%d")))
```

- [ ] **Step 4: 运行定向测试并确认通过**

Run: `uv run --with pytest --with-editable . pytest tests/test_batch_output_paths.py -q`

Expected: 2 passed。

### Task 2: CLI 与 Web 统一展开输出目录

**Files:**
- Modify: `src/tags_machine_core/cli.py`
- Modify: `src/tags_machine_core/web/services/batch_workspace.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Consumes: Task 1 的 `resolve_batch_output_path(...)`。
- Produces: CLI `_batch_output_dir(...)` 和 Web `BatchWorkspaceService._output_dir(...)` 返回已展开路径。

- [ ] **Step 1: 写 CLI 路径优先级和日期展开测试**

```python
def test_batch_output_dir_expands_date_from_spec(tmp_path, monkeypatch):
    spec = BatchSpec(name="daily", output_dir=str(tmp_path / "{date}"))
    result = cli._batch_output_dir(
        spec,
        spec_path=tmp_path / "batch.yaml",
        run_dir=tmp_path / "work",
    )
    assert "{date}" not in str(result)
    assert result.parent == tmp_path
```

- [ ] **Step 2: 写 Web 路径展开一致性测试**

```python
def test_web_batch_output_dir_expands_date(tmp_path):
    service = BatchWorkspaceService(base_dir=tmp_path)
    spec = BatchSpec(name="daily", output_dir=str(tmp_path / "{date}"))
    result = service._output_dir(
        spec,
        data={},
        spec_path=tmp_path / "batch.yaml",
        run_dir=tmp_path / "work",
    )
    assert "{date}" not in str(result)
```

- [ ] **Step 3: 运行新增测试并确认失败**

Run: `uv run --with pytest --with-editable . pytest tests/test_batch_output_paths.py -q`

Expected: FAIL，当前入口仍返回包含 `{date}` 的路径。

- [ ] **Step 4: 在两个入口调用共用解析器**

```python
raw = override or spec.output_dir
if raw:
    relative_path = _batch_relative_path(raw, spec_path=spec_path)
    return resolve_batch_output_path(relative_path)
return run_dir / "outputs"
```

Web 服务对其现有相对路径解析结果执行同样的 `resolve_batch_output_path(...)`。

- [ ] **Step 5: 运行定向测试并确认通过**

Run: `uv run --with pytest --with-editable . pytest tests/test_batch_output_paths.py -q`

Expected: CLI 与 Web 测试全部通过。

### Task 3: Fresh、Resume 和业务配置验收

**Files:**
- Modify: `examples/batches/blackboard_action_new.yaml`
- Modify: `docs/batch_generation_readme.md`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Consumes: 已展开的实际 `output_dir` 和现有 `batch_source.json` 归档机制。
- Produces: 每日输出配置示例、恢复语义测试和 Mock Batch 验收结果。

- [ ] **Step 1: 写恢复时沿用归档路径的测试**

```python
def test_resume_uses_archived_resolved_output_dir(tmp_path):
    archived = tmp_path / "20260712"
    source = {"output_dir": str(archived), "run_id": "daily001"}
    (tmp_path / "batch_source.json").write_text(json.dumps(source), encoding="utf-8")
    assert cli._batch_source_data(tmp_path)["output_dir"] == str(archived)
```

- [ ] **Step 2: 将 Blackboard 替代配置改为日期目录**

```yaml
output_dir: "G:/ai_auto/{date}"
```

- [ ] **Step 3: 补充 README 使用说明**

记录 `{date}`、服务器本地时区、跨午夜、同日多次 fresh 和次日 resume 的行为，并给出：

```powershell
uv run python -m tags_machine_core run-batch `
  examples/batches/blackboard_action_new.yaml `
  --fresh `
  --mock-client `
  --full
```

- [ ] **Step 4: 运行 Batch 定向测试**

Run: `uv run --with pytest --with-editable . pytest tests/test_batch_output_paths.py tests/test_batch_generation.py -q`

Expected: 当前 Batch 测试集通过。

- [ ] **Step 5: 执行真实编排链路的 Mock Batch**

Run: `uv run python -m tags_machine_core run-batch examples/batches/blackboard_action_new.yaml --fresh --mock-client --limit 3 --full`

Expected:

- 返回的 `output_dir` 是 `G:/ai_auto/<当天 YYYYMMDD>`。
- 三个任务的 `output.output_dir` 指向同一日期目录。
- `batch_source.json` 保存展开后的绝对路径，不包含 `{date}`。
- 任务成功生成 Mock 归档，不请求 NovelAI。

- [ ] **Step 6: 检查改动范围**

Run: `git diff --check`

Expected: 无空白错误；不修改 AgentComposer、Renderer 或 NovelAI Client。

- [ ] **Step 7: 提交实现**

```powershell
git add src/tags_machine_core/batch/paths.py `
  src/tags_machine_core/batch/__init__.py `
  src/tags_machine_core/cli.py `
  src/tags_machine_core/web/services/batch_workspace.py `
  tests/test_batch_generation.py `
  examples/batches/blackboard_action_new.yaml `
  docs/batch_generation_readme.md
git commit -m "feat: support dated batch output paths"
```
