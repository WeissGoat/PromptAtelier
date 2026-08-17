# 月度投稿日历 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Publishing Workspace 中增加一个独立的月度投稿编排层，支持手工月历、散图与已有 task 图集、独立 `all/post/cover` 顺序、到期构建和失败重试。

**Architecture:** 新增 `plans/<YYYY-MM>/plan.yaml` 作为日历编排数据，MonthlyPlan 不修改 Catalog 和既有 task。`ScheduleService` 负责编辑和锁定，`AssetSearchService` 负责按 import、节点和 `classify.yaml` 搜索，`SubmissionExecutor` 将 task 或散图选择转换为现有 PackageBuilder 输入，未来通过 Notifier/Publisher 扩展提醒和 Pixiv 发布。

**Tech Stack:** Python 3.11、Pydantic v2、PyYAML、SQLite Catalog、argparse、FastAPI + Uvicorn、原生 HTML/CSS/JavaScript。

## Global Constraints

- 不实现自动排期、工作日规则、周末规则和投稿复制。
- 月历数据放在 workspace 根目录的 `plans/`，不放入 `tasks/<task_id>/`。
- 不修改公共 Catalog 中的原图、Reader 结果和节点元数据。
- 不强制要求 `post` 是 `all` 的子集，也不强制要求 `cover` 属于 `post`；只记录 warning。
- 散图默认 `all = post`、`cover = []`。
- 已有 task 在执行时读取最新 selection，并在 execution 记录实际 build_id。
- 每条 ScheduleEntry 独立失败和重试，不阻塞同一计划的其他 entry。
- 月历计划只保存有序 `asset_id`，不保存运行时解析出的绝对图片路径。
- 继续使用中文注释、现有日志分级和现有 Publishing Workspace 命名风格。
- 只暂存本计划对应的文件，不覆盖工作区内其他未提交变更。

---

## 文件地图

### 新增

- `tools/publishing_workspace/src/publishing_workspace/plans/models.py`：月度计划、投稿条目、执行记录和内容引用模型。
- `tools/publishing_workspace/src/publishing_workspace/plans/paths.py`：`plans/<month>` 路径和原子文件路径。
- `tools/publishing_workspace/src/publishing_workspace/plans/repository.py`：YAML/JSON 读写、revision、执行记录持久化。
- `tools/publishing_workspace/src/publishing_workspace/plans/service.py`：创建、编辑、拖拽改期、锁定和删除投稿。
- `tools/publishing_workspace/src/publishing_workspace/plans/search.py`：Catalog 搜索、facet 和使用提醒。
- `tools/publishing_workspace/src/publishing_workspace/plans/materializer.py`：inline selection 到临时 task snapshot 的转换。
- `tools/publishing_workspace/src/publishing_workspace/plans/executor.py`：到期扫描、幂等、构建和单条重试。
- `tools/publishing_workspace/src/publishing_workspace/plans/notifier.py`：控制台/结构化日志通知接口。
- `tools/publishing_workspace/src/publishing_workspace/plans/__init__.py`：公开模型和服务。
- `tools/publishing_workspace/src/publishing_workspace/web/schedule_api.py`：月历 HTTP API。
- `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.html`：月历页面。
- `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.js`：页面状态和拖拽交互。
- `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.css`：页面布局。
- `tools/publishing_workspace/tests/test_plan_models.py`：模型和 YAML schema 测试。
- `tools/publishing_workspace/tests/test_plan_service.py`：计划编辑和锁定测试。
- `tools/publishing_workspace/tests/test_plan_search.py`：Catalog/facet/使用提醒测试。
- `tools/publishing_workspace/tests/test_plan_executor.py`：执行、幂等和失败隔离测试。
- `tools/publishing_workspace/tests/test_schedule_cli.py`：CLI 业务测试。
- `tools/publishing_workspace/tests/test_schedule_api.py`：API 业务测试。

### 修改

- `tools/publishing_workspace/src/publishing_workspace/config.py`：增加 `WorkspacePaths.plans`，初始化 `plans/`。
- `tools/publishing_workspace/src/publishing_workspace/cli.py`：增加 `schedule` 命令组和 `web` 命令。
- `tools/publishing_workspace/src/publishing_workspace/service.py`：暴露计划服务，保持现有 import/task API 不变。
- `tools/publishing_workspace/pyproject.toml`：增加 Web API 运行时依赖和开发测试依赖。
- `tools/publishing_workspace/README.md`：增加月历 YAML、CLI 和 API 使用说明。

### 不修改职责

- `catalog/repository.py` 只提供资产读取和节点查询；如需新增查询方法，只增加只读方法。
- `tasks/service.py` 和 `packages/builder.py` 继续负责 task 选择和投稿包构建。
- `processing/pipeline.py` 继续负责图片处理 operation。
- `inputs/*` 继续负责 NeeView、目录和快捷方式输入。

---

## Task 1: 增加月历路径、模型和持久化

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/models.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/paths.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/repository.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/config.py: WorkspacePaths, init_workspace`
- Test: `tools/publishing_workspace/tests/test_plan_models.py`

**Interfaces:**

```python
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SelectionName = Literal["all", "post", "cover"]
PlanStatus = Literal["draft", "locked"]
ContentKind = Literal["task", "inline_selection"]

class TaskContent(BaseModel):
    kind: Literal["task"] = "task"
    task_id: str

class InlineContent(BaseModel):
    kind: Literal["inline_selection"] = "inline_selection"
    source_import_id: str | None = None
    sets: dict[SelectionName, list[str]] = Field(
        default_factory=lambda: {"all": [], "post": [], "cover": []}
    )

class ExecutionPolicy(BaseModel):
    build_on_due: bool = True
    notify_on_complete: bool = True
    publish: bool = False

class ScheduleEntry(BaseModel):
    entry_id: str
    scheduled_at: datetime
    title: str
    content: TaskContent | InlineContent
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

class MonthlyPlan(BaseModel):
    schema: Literal["publishing-workspace.monthly-plan/v1"] = (
        "publishing-workspace.monthly-plan/v1"
    )
    plan_id: str
    month: str
    timezone: str = "Asia/Shanghai"
    status: PlanStatus = "draft"
    default_import_id: str | None = None
    revision: int = 1
    entries: list[ScheduleEntry] = Field(default_factory=list)

class ExecutionRecord(BaseModel):
    execution_id: str
    entry_id: str
    plan_revision: int
    scheduled_at: datetime
    status: Literal["running", "completed", "failed"]
    build_id: str | None = None
    task_id: str | None = None
    notification_status: Literal["pending", "sent", "failed", "disabled"] = "pending"
    error: str | None = None
```

`PlanPaths` 必须提供：

```python
class PlanPaths:
    @classmethod
    def from_workspace(cls, workspace: WorkspacePaths, month: str) -> "PlanPaths": ...
    plan_yaml: Path
    executions_dir: Path
    execution_path(self, execution_id: str) -> Path: ...
```

- [ ] **Step 1: Write failing model tests**

测试必须覆盖：默认 `draft`、散图默认集合、task/inline 联合类型、非法月份、重复 entry ID、非本月时间。

```python
def test_inline_content_defaults_to_empty_selection_sets():
    content = InlineContent()
    assert content.sets == {"all": [], "post": [], "cover": []}

def test_plan_rejects_entry_outside_month():
    with pytest.raises(ValueError, match="scheduled_at"):
        MonthlyPlan(
            plan_id="2026-09",
            month="2026-09",
            entries=[entry_at("2026-10-01T12:00:00+08:00")],
        )
```

- [ ] **Step 2: Run model tests and confirm failure**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run pytest tools/publishing_workspace/tests/test_plan_models.py -q
```

Expected: FAIL because the `plans` package and models do not exist。

- [ ] **Step 3: Implement models and paths**

在 `MonthlyPlan` 的 model validator 中校验 `month` 为 `YYYY-MM`，并保证每个 entry 的 `scheduled_at` 转换到 `timezone` 后仍属于 `month`。YAML 输出使用 `model_dump(mode="json")`，时间统一写 ISO-8601。

在 `WorkspacePaths` 增加：

```python
plans: Path
```

并在 `from_root()` 和 `init_workspace()` 中创建 `<root>/plans`。

- [ ] **Step 4: Implement atomic repository**

提供以下精确接口：

```python
class PlanRepository:
    def create(self, paths: PlanPaths, *, default_import_id: str | None = None) -> MonthlyPlan: ...
    def load(self, paths: PlanPaths) -> MonthlyPlan: ...
    def save(self, paths: PlanPaths, plan: MonthlyPlan, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def load_execution(self, paths: PlanPaths, execution_id: str) -> ExecutionRecord: ...
    def save_execution(self, paths: PlanPaths, record: ExecutionRecord) -> Path: ...
    def list_executions(self, paths: PlanPaths, entry_id: str | None = None) -> list[ExecutionRecord]: ...
```

`save()` 在传入 `expected_revision` 且当前 revision 不一致时抛出 `PlanRevisionConflictError`；成功保存时 revision 加一。所有写文件使用临时文件加 `os.replace()`。

- [ ] **Step 5: Run tests and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_models.py -q
git add tools/publishing_workspace/src/publishing_workspace/plans tools/publishing_workspace/src/publishing_workspace/config.py tools/publishing_workspace/tests/test_plan_models.py
git commit -m "feat: add monthly publishing plan models"
```

Expected: all model, path, atomic save and revision tests PASS。

## Task 2: 实现计划编辑、拖拽改期和锁定

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/service.py`
- Test: `tools/publishing_workspace/tests/test_plan_service.py`

**Interfaces:**

```python
class ScheduleService:
    def create_plan(self, root: str | Path, month: str, *, default_import_id: str | None = None) -> MonthlyPlan: ...
    def get_plan(self, root: str | Path, month: str) -> MonthlyPlan: ...
    def add_entry(self, root: str | Path, month: str, entry: ScheduleEntry, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def update_entry(self, root: str | Path, month: str, entry: ScheduleEntry, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def move_entry_date(self, root: str | Path, month: str, entry_id: str, target_date: date, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def delete_entry(self, root: str | Path, month: str, entry_id: str, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def lock(self, root: str | Path, month: str, *, expected_revision: int | None = None) -> MonthlyPlan: ...
    def unlock(self, root: str | Path, month: str, *, expected_revision: int | None = None) -> MonthlyPlan: ...
```

行为规则：

- `move_entry_date()` 只替换日期，保留原始小时、分钟和时区。
- `add_entry()` 和 `update_entry()` 禁止 entry_id 重复。
- 同一时间多条投稿只写 warning，不抛错。
- `lock()` 校验 task/asset 引用、月份和 `post` 非空；`all`/`cover` 关系只 warning。
- `locked` 计划不允许普通编辑，必须先 `unlock()`。
- 该服务不实现“复制投稿”。

- [ ] **Step 1: Write failing service tests**

```python
def test_move_entry_date_preserves_time(tmp_path):
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(tmp_path, "2026-09", entry_at("2026-09-05T20:00:00+08:00"))
    plan = service.move_entry_date(
        tmp_path, "2026-09", "entry-1", date(2026, 9, 8)
    )
    assert plan.entries[0].scheduled_at.isoformat() == "2026-09-08T20:00:00+08:00"

def test_locked_plan_rejects_edit(tmp_path):
    service = ready_plan_service(tmp_path)
    service.lock(tmp_path, "2026-09")
    with pytest.raises(PlanLockedError):
        service.delete_entry(tmp_path, "2026-09", "entry-1")
```

- [ ] **Step 2: Run and observe failure**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_service.py -q
```

Expected: FAIL because `ScheduleService` and lock exceptions do not exist。

- [ ] **Step 3: Implement service**

服务从 `load_workspace()` 获得 `WorkspacePaths`，使用 `PlanPaths.from_workspace()` 和 `PlanRepository`。保存时把 entry 按 `scheduled_at, entry_id` 排序，确保月历重载顺序稳定。

`lock()` 只负责结构和引用校验，不触发 build；执行由 `SubmissionExecutor` 负责。

- [ ] **Step 4: Run and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_service.py -q
git add tools/publishing_workspace/src/publishing_workspace/plans/service.py tools/publishing_workspace/tests/test_plan_service.py
git commit -m "feat: add monthly plan editing and locking"
```

## Task 3: 增加 Catalog 素材检索和 classify facet

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/search.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/repository.py`
- Test: `tools/publishing_workspace/tests/test_plan_search.py`

**Interfaces:**

```python
class AssetSearchFilter(BaseModel):
    import_id: str | None = None
    text: str = ""
    artist: str | None = None
    character: str | None = None
    action_group: str | None = None
    action: str | None = None
    facets: dict[str, set[str]] = Field(default_factory=dict)
    limit: int = 100

class AssetSearchResult(BaseModel):
    asset_id: str
    path: str
    display_name: str
    values: dict[str, list[str]]
    facets: dict[str, list[str]]
    warnings: list[str]
    usage: list[str]

class AssetSearchService:
    def search(self, root: str | Path, filters: AssetSearchFilter) -> list[AssetSearchResult]: ...
    def facets(self, root: str | Path, *, import_id: str | None = None) -> dict[str, list[str]]: ...
```

搜索规则：

- 空文本和空字段表示不限制。
- 文本匹配使用 case-insensitive substring，节点字段也支持 substring。
- 节点值通过 `AssetRecord.node_values()`，action/action_group 继续经过现有 action resolver。
- facet 字段固定为 `phase/species/cast/domain/subtype/pose/environment/tone/flags/clothing`。
- action 的 `classify.yaml` 从 action node ref 对应目录读取；不存在时不认为是错误，只返回空 facet。
- `usage` 从 plans 的 inline selections 和 task selection/build 历史中计算，结果只用于角标提醒。
- 返回结果始终使用 `asset_id`，UI 不依赖路径作为身份。

- [ ] **Step 1: Create fixtures and failing tests**

建立两个包含节点和 `classify.yaml` 的临时 asset fixture，覆盖：指定 import、模糊 character、两个 facet 交集、空筛选、已被计划引用的角标。

```python
def test_search_filters_by_classify_facets(tmp_path):
    seed_catalog(tmp_path)
    result = AssetSearchService().search(
        tmp_path,
        AssetSearchFilter(import_id="import-1", facets={"clothing": {"nude"}}),
    )
    assert [item.asset_id for item in result] == ["sha256:asset-1"]
```

- [ ] **Step 2: Run and confirm failure**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_search.py -q
```

Expected: FAIL because the search service and Catalog read method are missing。

- [ ] **Step 3: Implement read-only Catalog access**

在 `CatalogRepository` 增加 `asset_ids_for_import(import_id)` 和 `asset_usage_paths()` 两个只读方法；不改变 schema。`assets_for_import()` 继续作为完整 AssetRecord 读取入口。

实现 `ClassifyFacetReader`，对同一个 action 目录按 `classify.yaml` 读取 mapping，忽略未知字段并保留配置中的列表值。Reader 异常转换为 warning，不阻止搜索结果。

- [ ] **Step 4: Implement search and facet aggregation**

先按 import 缩小 AssetRecord 集合，再依次应用节点筛选、文本筛选和 facets；最后按 `display_name.casefold(), asset_id` 排序并截断 `limit`。不把搜索条件写回 Catalog。

- [ ] **Step 5: Run and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_search.py -q
git add tools/publishing_workspace/src/publishing_workspace/plans/search.py tools/publishing_workspace/src/publishing_workspace/catalog/repository.py tools/publishing_workspace/tests/test_plan_search.py
git commit -m "feat: add publishing asset search facets"
```

## Task 4: 将 inline selection 接入现有 Task/PackageBuilder

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/materializer.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/tasks/paths.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/tasks/repository.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/packages/builder.py`
- Test: `tools/publishing_workspace/tests/test_plan_materializer.py`

**Interfaces:**

```python
class MaterializedPlanTask(BaseModel):
    task_id: str
    task_root: Path
    temporary: bool = True

class InlineTaskMaterializer:
    def materialize(
        self,
        root: str | Path,
        *,
        plan_id: str,
        entry: ScheduleEntry,
        catalog: CatalogRepository,
    ) -> MaterializedPlanTask: ...

    def cleanup(self, materialized: MaterializedPlanTask) -> None: ...
```

实现规则：

- 任务目录放在 `workspace/cache/monthly-plan/<plan_id>/<entry_id>/<execution_id>/`，不放进公共 `tasks/`。
- 从 Catalog 根据有序 asset_id 解析当前路径，并复制到临时 task 的 `selection/all|post|cover`。
- 文件名使用现有 `OutputNamePolicy`，顺序按 plan 中 asset_id 顺序，不按路径排序。
- 写入与普通 task 相同的 `task.yaml` 和 `selection_snapshot.json`。
- PackageBuilder 通过新增 `build_materialized(root, task_paths)` 或等价的内部 task path 接口复用现有处理链路。
- build 完成或失败后都清理临时 task；成功输出 build 目录保留。
- 原图、Catalog 和已有 task 不修改。

- [ ] **Step 1: Write failing materializer tests**

```python
def test_inline_materializer_preserves_all_post_cover_order(tmp_path):
    entry = inline_entry(["sha256:b", "sha256:a"], ["sha256:a"], [])
    materialized = InlineTaskMaterializer().materialize(
        tmp_path, plan_id="2026-09", entry=entry, catalog=seed_catalog(tmp_path)
    )
    assert image_names(materialized.task_root / "selection" / "all") == ["0001_b.png", "0002_a.png"]
    assert image_names(materialized.task_root / "selection" / "post") == ["0001_a.png"]
```

- [ ] **Step 2: Run failure and implement**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_materializer.py -q
```

Expected: FAIL before materializer and PackageBuilder bridge exist。

Implement only a path-based bridge in `PackageBuilder`; do not duplicate processing operations or archive logic。

- [ ] **Step 3: Verify real package output and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_materializer.py tools/publishing_workspace/tests/test_package_builder.py -q
git add tools/publishing_workspace/src/publishing_workspace/plans/materializer.py tools/publishing_workspace/src/publishing_workspace/tasks/paths.py tools/publishing_workspace/src/publishing_workspace/tasks/repository.py tools/publishing_workspace/src/publishing_workspace/packages/builder.py tools/publishing_workspace/tests/test_plan_materializer.py
git commit -m "feat: materialize monthly inline selections"
```

## Task 5: 实现到期执行、幂等和通知

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/notifier.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/plans/executor.py`
- Test: `tools/publishing_workspace/tests/test_plan_executor.py`

**Interfaces:**

```python
class NotificationResult(BaseModel):
    status: Literal["sent", "failed", "disabled"]
    message: str | None = None

class Notifier(Protocol):
    def notify(self, event: SubmissionEvent) -> NotificationResult: ...

class SubmissionExecutor:
    def run_due(self, root: str | Path, *, now: datetime | None = None) -> list[ExecutionRecord]: ...
    def build_now(self, root: str | Path, month: str, entry_id: str) -> ExecutionRecord: ...
    def retry(self, root: str | Path, month: str, entry_id: str) -> ExecutionRecord: ...
```

实现规则：

- 仅扫描 `locked` 计划和 `scheduled_at <= now` 的 entry。
- 幂等键为 `sha256(plan_id + entry_id + str(plan.revision) + scheduled_at.isoformat())`。
- 已有 `completed` execution 不重复 build；失败 execution 只有显式 retry 才再次执行。
- task entry 使用最新 task selection；inline entry 使用 materializer。
- 每个 entry 单独捕获异常并写 `failed` execution，循环继续。
- 通知失败不回滚 build，execution 仍为 `completed`，notification_status 为 `failed`。
- `publish` 永远不在本计划执行；值为 true 时记录 warning 并视为 disabled，避免误上传。
- `build_now` reason 为 `manual_preview`，不占用正常到期幂等记录。

- [ ] **Step 1: Write failing business tests**

```python
def test_run_due_continues_after_one_entry_fails(tmp_path):
    plan = locked_plan_with_task_and_broken_task(tmp_path)
    records = SubmissionExecutor().run_due(tmp_path, now=plan_time)
    assert [record.status for record in records] == ["failed", "completed"]

def test_run_due_is_idempotent_after_success(tmp_path):
    create_locked_ready_plan(tmp_path)
    first = SubmissionExecutor().run_due(tmp_path, now=plan_time)
    second = SubmissionExecutor().run_due(tmp_path, now=plan_time)
    assert len(first) == 1
    assert second == []
```

- [ ] **Step 2: Run and observe failure**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_executor.py -q
```

Expected: FAIL because executor and execution persistence do not exist。

- [ ] **Step 3: Implement executor and console notifier**

`ConsoleNotifier.notify()` 输出 entry_id、build_root、post 数量和失败信息；不依赖外部网络。执行日志使用现有 logger，关键字段使用结构化 key/value。

- [ ] **Step 4: Run business tests and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_plan_executor.py tools/publishing_workspace/tests/test_plan_materializer.py -q
git add tools/publishing_workspace/src/publishing_workspace/plans/notifier.py tools/publishing_workspace/src/publishing_workspace/plans/executor.py tools/publishing_workspace/tests/test_plan_executor.py
git commit -m "feat: execute due publishing entries"
```

## Task 6: 增加 schedule CLI

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/cli.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/service.py`
- Test: `tools/publishing_workspace/tests/test_schedule_cli.py`
- Modify: `tools/publishing_workspace/README.md`

新增命令：

```text
publishing-workspace schedule create ROOT MONTH [--default-import-id ID]
publishing-workspace schedule show ROOT MONTH
publishing-workspace schedule add-entry ROOT MONTH --entry-json FILE
publishing-workspace schedule update-entry ROOT MONTH --entry-json FILE --expected-revision N
publishing-workspace schedule move-date ROOT MONTH ENTRY_ID YYYY-MM-DD
publishing-workspace schedule delete-entry ROOT MONTH ENTRY_ID
publishing-workspace schedule lock ROOT MONTH --expected-revision N
publishing-workspace schedule unlock ROOT MONTH --expected-revision N
publishing-workspace schedule run-due ROOT [--now ISO]
publishing-workspace schedule build-now ROOT MONTH ENTRY_ID
publishing-workspace schedule retry ROOT MONTH ENTRY_ID
publishing-workspace schedule status ROOT MONTH
```

CLI 输出统一 JSON；错误返回非零退出码并输出 `code`、`message`。不增加 `--auto`、`--copy-entry` 或类似参数。

- [ ] **Step 1: Add failing CLI tests**

```python
def test_schedule_cli_create_add_move_and_show(tmp_path, capsys):
    assert main(["schedule", "create", str(tmp_path), "2026-09"]) == 0
    assert main(["schedule", "add-entry", str(tmp_path), "2026-09", "--entry-json", str(entry_json)]) == 0
    assert main(["schedule", "move-date", str(tmp_path), "2026-09", "entry-1", "2026-09-08"]) == 0
    assert json.loads(capsys.readouterr().out)["entries"][0]["scheduled_at"].startswith("2026-09-08")
```

- [ ] **Step 2: Run failure, implement parser and service facade**

在 `service.py` 增加 `PublishingService` 的：

```python
def schedule_create(...): ...
def schedule_show(...): ...
def schedule_run_due(...): ...
```

`cli.py` 只做参数解析、JSON 输出和退出码转换，不包含计划业务规则。

- [ ] **Step 3: Run CLI business tests and commit**

```powershell
uv run pytest tools/publishing_workspace/tests/test_schedule_cli.py -q
git add tools/publishing_workspace/src/publishing_workspace/cli.py tools/publishing_workspace/src/publishing_workspace/service.py tools/publishing_workspace/tests/test_schedule_cli.py tools/publishing_workspace/README.md
git commit -m "feat: add monthly schedule CLI"
```

## Task 7: 增加月历 Web API

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/web/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/web/schedule_api.py`
- Create: `tools/publishing_workspace/tests/test_schedule_api.py`
- Modify: `tools/publishing_workspace/pyproject.toml`
- Modify: `tools/publishing_workspace/src/publishing_workspace/cli.py`

使用 FastAPI 提供本地 Web API；所有业务调用现有 `ScheduleService` 和 `AssetSearchService`，路由不读写 YAML。

接口：

```text
GET  /api/plans/{month}
POST /api/plans/{month}/entries
PUT  /api/plans/{month}/entries/{entry_id}
PATCH /api/plans/{month}/entries/{entry_id}/date
DELETE /api/plans/{month}/entries/{entry_id}
POST /api/plans/{month}/lock
POST /api/plans/{month}/unlock
GET  /api/assets/search
GET  /api/assets/facets
GET  /api/assets/{asset_id}/preview
GET  /api/entries/{entry_id}/images/{selection}
```

请求必须带 `revision` 的接口返回 409 `plan_revision_conflict`。`/preview` 只允许返回 Catalog 已登记的图片路径，不接受任意文件系统路径，避免 API 变成任意文件读取器。Windows 本地运行时使用 `Path` 解析并确认路径存在于 Catalog 的 asset_paths。

启动命令：

```text
publishing-workspace web ROOT --host 127.0.0.1 --port 61300
```

- [ ] **Step 1: Add dependency and failing API tests**

```python
def test_plan_api_returns_revision_and_entries(client, tmp_path):
    create_plan(tmp_path, "2026-09")
    response = client.get("/api/plans/2026-09")
    assert response.status_code == 200
    assert response.json()["revision"] == 1
```

- [ ] **Step 2: Implement app factory and routes**

提供 `create_app(root: str | Path) -> FastAPI`，测试使用 `httpx` TestClient；不在 import 时启动全局服务。静态文件由 Task 8 挂载。

- [ ] **Step 3: Test API error contracts and commit**

覆盖 404 plan、409 revision、422 非法 entry、asset preview 404 和 search filters。

```powershell
uv run pytest tools/publishing_workspace/tests/test_schedule_api.py -q
git add tools/publishing_workspace/pyproject.toml tools/publishing_workspace/src/publishing_workspace/web tools/publishing_workspace/src/publishing_workspace/cli.py tools/publishing_workspace/tests/test_schedule_api.py
git commit -m "feat: add monthly schedule web api"
```

## Task 8: 实现月历 Web UI

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.html`
- Create: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.js`
- Create: `tools/publishing_workspace/src/publishing_workspace/web/static/schedule.css`
- Modify: `tools/publishing_workspace/src/publishing_workspace/web/schedule_api.py`
- Test: `tools/publishing_workspace/tests/test_schedule_api.py`

UI 必须实现：

- 月份切换、跳转月份和当前锁定状态。
- 默认空日历、同一天多个时间槽。
- workspace import 选择。
- artist、character、action_group、action 模糊搜索。
- `classify.yaml` facet 筛选。
- 搜索结果多选加入散图投稿。
- 左侧和右侧缩略图点击大图预览。
- 已使用/风险素材角标提醒。
- task 图集和 inline selection 两种内容来源。
- `all/post/cover` tabs，各自拖拽排序。
- 投稿卡片拖拽到其他日期，保留时间并提交 PATCH。
- “移动时间”和“删除”。
- 不渲染自动排期和复制投稿按钮。

页面状态分为：

```javascript
const state = {
  month: "2026-09",
  plan: null,
  revision: null,
  selectedEntryId: null,
  selectedSet: "post",
  assetFilters: { import_id: null, text: "", facets: {} },
  selectedAssetIds: []
};
```

拖拽流程：`dragstart(entry_id)` -> `drop(target_date)` -> `PATCH /date` -> 用返回 plan 替换本地 state；409 时显示“计划已被其他页面修改”，重新加载，不做静默覆盖。

图片预览使用 `<dialog>`，只接受 API 返回的 preview URL；不把绝对路径写入 DOM。

- [ ] **Step 1: Implement static page against mocked API response**

先用固定 JSON 让日历、右侧编辑器、三个集合和拖拽交互可见；页面不包含自动排期和复制投稿文案。

- [ ] **Step 2: Connect real API and add UI smoke business test**

启动本地 API，使用浏览器验证：创建空计划、加入两张图、建立同日两个时间槽、拖拽改日期、独立调整 post 顺序、重新加载后 revision 和顺序保持。

- [ ] **Step 3: Commit UI**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/web
git commit -m "feat: add monthly publishing calendar ui"
```

## Task 9: 完成 README、示例和真实业务验收

**Files:**
- Create: `tools/publishing_workspace/examples/monthly-plan/2026-09.yaml`
- Create: `tools/publishing_workspace/docs/acceptance-monthly-publishing-calendar.md`
- Modify: `tools/publishing_workspace/README.md`
- Test: `tools/publishing_workspace/tests/test_monthly_calendar_acceptance.py`

示例必须体现：

- 1 条已有 task 图集。
- 1 条 inline 散图。
- 同一天 2 条不同时间投稿。
- 独立 `all/post/cover` 顺序。
- `publish: false`。

业务验收命令：

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run pytest tools/publishing_workspace/tests/test_monthly_calendar_acceptance.py -q
uv run publishing-workspace schedule show G:\ai_publish 2026-09
uv run publishing-workspace schedule run-due G:\ai_publish --now 2026-09-05T20:01:00+08:00
```

验收记录必须保存：

- plan YAML 路径和 revision。
- 每个 entry 的 execution JSON。
- task build_id 和 build manifest 路径。
- all/post/cover 数量和顺序摘要。
- 失败 entry 与其他 entry 继续完成的日志。
- 第二次 run-due 没有重复成功构建的结果。

- [ ] **Step 1: Write acceptance fixture**

使用 3-5 张测试图片和一个现有 task fixture，不把 workspace 中的 10,010 张原始文件作为单次测试输入。

- [ ] **Step 2: Run full publishing workspace regression**

```powershell
uv run pytest tools/publishing_workspace/tests -q
```

Expected: 现有 import、reader、export、task、processing、mosaic 测试与月历测试全部 PASS。

- [ ] **Step 3: Run manual business flow and record result**

按 README 示例操作一次真实 workspace 的小计划；确认实际 build 目录、日志和 JSON 结果，再更新验收文档。

- [ ] **Step 4: Commit docs and acceptance**

```powershell
git add tools/publishing_workspace/examples/monthly-plan tools/publishing_workspace/docs/acceptance-monthly-publishing-calendar.md tools/publishing_workspace/README.md tools/publishing_workspace/tests/test_monthly_calendar_acceptance.py
git commit -m "docs: add monthly publishing calendar acceptance"
```

## 最终检查

- [ ] 对照设计文档逐项检查：无自动排期、无复制投稿、支持拖拽改期、支持 task/散图、支持 classify facet、支持三集合独立排序、支持大图预览。
- [ ] 检查计划模型和执行器没有把绝对路径作为 asset 身份。
- [ ] 检查 inline task 的临时目录在成功和失败后都清理。
- [ ] 检查通知失败不回滚已完成 build。
- [ ] 检查已有 task build 和原有 CLI 回归测试通过。
- [ ] 检查所有新文件只在 `refactor/tools/publishing_workspace` 内。
