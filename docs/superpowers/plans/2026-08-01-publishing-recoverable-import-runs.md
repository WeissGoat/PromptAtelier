# Publishing Workspace 可恢复导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有一次性全事务图片导入升级为可规划、可分批提交、可中断恢复、可查询问题的持久化 ImportRun，同时保留现有 Reader、Enricher、分类和导出接口。

**Architecture:** Catalog 继续只保存 Asset、路径和节点事实；新的 `importing` 包保存运行、输入项、规划决策、批次执行和租约锁，新的 `problems` 包保存可复用的问题指纹。`PublishingService` 仍是 CLI Facade，但导入编排委托给 `ImportWorkflowService`，完成后只写一次 JSON 快照。

**Tech Stack:** Python 3.11、SQLite 3、Pydantic 2、Pillow、argparse、pytest、uv。

## Global Constraints

- 工作目录固定为 `F:/my_project/new/tags_machine/refactor/tools/publishing_workspace`。
- 不创建新分支，直接在当前 `main` 上按任务独立提交。
- 不修改、移动或删除任何原始图片；Catalog 和快照只记录原始路径。
- 默认追加到公共 Catalog，新输入中未出现的历史 Asset 不删除。
- 默认批次大小为 `200`，每批在一个 SQLite 事务中提交。
- `info` 进度每处理 `200` 项或距离上次输出超过 `5` 秒时输出一次。
- 同一 workspace 同时只允许一个写入型导入 Run；只读查询不获取写锁。
- 路径、大小和修改时间一致时，不重新计算 SHA-256，不调用 Pillow、Reader 或 Enricher。
- Reader 无法识别节点但图片本身有效时，以 `reader=unknown` 导入，不创建问题。
- 0 字节文件在 Planner 阶段识别，不交给 Pillow 或 Reader。
- 业务验收优先使用真实 `E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls`，基准为 10010 项、9987 个成功项、23 个问题。
- 阶段 1 不实现增量分类、增量导出和 `refresh`；现有 `classify`、`export` 继续全量工作。
- 现有工作区中与本功能无关的未提交文件不加入任何提交。

---

## File Map

### 新建文件

- `src/publishing_workspace/catalog/migrations.py`：Catalog v1 到 v2 的一致性备份和事务迁移。
- `src/publishing_workspace/importing/__init__.py`：导出导入子系统公开接口。
- `src/publishing_workspace/importing/models.py`：ImportRun、ImportItem、规划和执行结果模型。
- `src/publishing_workspace/importing/repository.py`：运行、输入项、计数和状态持久化。
- `src/publishing_workspace/importing/planner.py`：把 pending 输入项转换为持久化 decision。
- `src/publishing_workspace/importing/executor.py`：按批次执行 planned 项并提交结果。
- `src/publishing_workspace/importing/locks.py`：workspace SQLite 租约锁。
- `src/publishing_workspace/importing/progress.py`：统一阶段事件和节流进度日志。
- `src/publishing_workspace/importing/service.py`：create/import/resume/retry 的工作流编排。
- `src/publishing_workspace/problems/__init__.py`：导出问题子系统公开接口。
- `src/publishing_workspace/problems/repository.py`：问题指纹查询、创建、保持和解决。
- `tests/test_catalog_v2_migration.py`：schema v2、备份和历史转换测试。
- `tests/test_import_planner.py`：规划决策和问题保持测试。
- `tests/test_import_executor.py`：批次提交、中断恢复和租约测试。
- `tests/test_import_workflow.py`：完整导入、恢复和问题重试测试。
- `scripts/accept_recoverable_import.py`：真实一万项列表的业务验收与报告脚本。

### 修改文件

- `src/publishing_workspace/catalog/schema.py`：schema 版本升级到 v2，声明新表和新列。
- `src/publishing_workspace/catalog/repository.py`：只保留 Asset 事实读写，公开事务内 ingest API。
- `src/publishing_workspace/catalog/__init__.py`：导出新的 Catalog 结果类型。
- `src/publishing_workspace/config.py`：增加 `workspace/backups` 路径并初始化目录。
- `src/publishing_workspace/models.py`：保留通用 Asset/View 模型，移除旧一次性 ImportResult 依赖。
- `src/publishing_workspace/service.py`：导入委托给 ImportWorkflowService，保留 classify/export Facade。
- `src/publishing_workspace/cli.py`：增加 status、resume、problems、retry-problems 命令。
- `tests/test_pipeline.py`：把旧 v1 schema 测试迁移到专用文件，保留分类和导出覆盖。
- `tests/test_cli.py`：覆盖新的命令输出。
- `README.md`：补充导入、恢复、问题查询和真实验收用法。

---

### Task 1: Catalog Schema v2、Backup API 与历史迁移

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/catalog/migrations.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/schema.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/repository.py:33-113`
- Modify: `tools/publishing_workspace/src/publishing_workspace/config.py:81-131`
- Create: `tools/publishing_workspace/tests/test_catalog_v2_migration.py`
- Modify: `tools/publishing_workspace/tests/test_pipeline.py:224-299`

**Interfaces:**
- Consumes: v1 `catalog.sqlite`，其中 `schema_meta.version=1`，以及现有 `imports`、`import_items` 数据。
- Produces: `migrate_catalog_v1_to_v2(catalog_path: Path, backups_dir: Path) -> Path`。
- Produces: `WorkspacePaths.backups: Path`，固定为 `<root>/workspace/backups`。
- Produces: schema v2 表 `imports`、`import_items`、`import_problems`、`workspace_locks`、`classification_profiles`、`asset_view_memberships`。

- [ ] **Step 1: 写 schema v2 新建库和 v1 迁移失败测试**

测试文件先定义一个完整的 v1 fixture builder：

```python
V1_SCHEMA_SQL = """
CREATE TABLE schema_meta(schema_id TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE assets(
    asset_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,
    width INTEGER NOT NULL, height INTEGER NOT NULL, image_format TEXT NOT NULL,
    metadata_format TEXT NOT NULL, reader TEXT NOT NULL, warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE asset_paths(
    path_key TEXT PRIMARY KEY, path TEXT NOT NULL, asset_id TEXT NOT NULL,
    size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
    available INTEGER NOT NULL DEFAULT 1, last_seen_at TEXT NOT NULL
);
CREATE TABLE asset_nodes(
    asset_id TEXT NOT NULL, role TEXT NOT NULL, node_index INTEGER NOT NULL,
    node_id TEXT NOT NULL DEFAULT '', ref TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(asset_id, role, node_index, node_id, ref)
);
CREATE TABLE imports(
    import_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_ref TEXT NOT NULL,
    created_at TEXT NOT NULL, warnings_json TEXT NOT NULL
);
CREATE TABLE import_items(
    import_id TEXT NOT NULL, source_order INTEGER NOT NULL, source_path TEXT NOT NULL,
    resolved_path TEXT, display_name TEXT NOT NULL, asset_id TEXT, status TEXT NOT NULL,
    warnings_json TEXT NOT NULL, PRIMARY KEY(import_id, source_order)
);
CREATE TABLE export_states(
    exporter TEXT NOT NULL, view_key TEXT NOT NULL, content_hash TEXT NOT NULL,
    outputs_json TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(exporter, view_key)
);
"""


def create_v1_catalog_with_imports(tmp_path: Path) -> Path:
    catalog = tmp_path / "workspace" / "catalog.sqlite"
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as connection:
        connection.executescript(V1_SCHEMA_SQL)
        connection.execute(
            "INSERT INTO schema_meta(schema_id, version) VALUES (?, 1)",
            ("publishing-workspace.catalog/v1",),
        )
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sha256:existing", "existing", 8, 1, 1, "PNG", "unknown",
                "unknown", "[]", "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO imports VALUES (?, ?, ?, ?, ?)",
            ("legacy", "directory", "F:/images", "2026-08-01T00:00:00+00:00", "[]"),
        )
        connection.execute(
            "INSERT INTO import_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy", 0, "F:/images/a.png", "F:/images/a.png", "a.png",
                "sha256:existing", "imported", "[]",
            ),
        )
    return catalog
```

```python
def test_new_catalog_uses_schema_v2(tmp_path: Path):
    repository = CatalogRepository(tmp_path / "workspace" / "catalog.sqlite")
    with repository.connection() as connection:
        schema = connection.execute(
            "SELECT schema_id, version FROM schema_meta"
        ).fetchone()
        import_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(imports)")
        }
    assert dict(schema) == {
        "schema_id": "publishing-workspace.catalog/v2",
        "version": 2,
    }
    assert {"mode", "status", "pipeline_stage", "processed_items"} <= import_columns


def test_v1_migration_creates_consistent_backup_and_preserves_legacy_status(tmp_path: Path):
    catalog = create_v1_catalog_with_imports(tmp_path)
    repository = CatalogRepository(catalog)

    backups = sorted((catalog.parent / "backups").glob("catalog-v1-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT version FROM schema_meta").fetchone()[0] == 1
    with repository.connection() as connection:
        run = connection.execute(
            "SELECT mode, status, pipeline_stage FROM imports WHERE import_id='legacy'"
        ).fetchone()
        item = connection.execute(
            "SELECT decision, status, asset_id FROM import_items "
            "WHERE import_id='legacy' AND source_order=0"
        ).fetchone()
    assert tuple(run) == ("legacy", "completed", "completed")
    assert tuple(item) == ("legacy", "legacy", "sha256:existing")


def test_v1_migration_failure_rolls_back_and_keeps_backup(tmp_path: Path, monkeypatch):
    catalog = create_v1_catalog_with_imports(tmp_path)
    monkeypatch.setattr(
        "publishing_workspace.catalog.migrations._migrate_import_items",
        lambda connection: (_ for _ in ()).throw(RuntimeError("模拟迁移失败")),
    )
    with pytest.raises(RuntimeError, match="模拟迁移失败"):
        CatalogRepository(catalog)
    with sqlite3.connect(catalog) as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 1
    assert len(list((catalog.parent / "backups").glob("catalog-v1-*.sqlite"))) == 1
```

- [ ] **Step 2: 运行迁移测试确认失败**

Run:

```powershell
uv run pytest tests/test_catalog_v2_migration.py -v
```

Expected: FAIL，原因包括 `SCHEMA_VERSION == 1`、`backups` 路径不存在、v2 列和迁移函数不存在。

- [ ] **Step 3: 声明 schema v2**

将 `catalog/schema.py` 的常量改为：

```python
SCHEMA_VERSION = 2
SCHEMA_ID = "publishing-workspace.catalog/v2"
```

新建库的 `imports` 和 `import_items` 必须使用设计文档第 8 节的完整字段，包括 `imports.strict INTEGER NOT NULL DEFAULT 0`，并新增：

```sql
CREATE TABLE IF NOT EXISTS import_problems (
    problem_id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL,
    path_key TEXT,
    source_path TEXT NOT NULL,
    error_code TEXT NOT NULL,
    message TEXT NOT NULL,
    observed_size INTEGER,
    observed_modified_ns INTEGER,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_import_problems_open_fingerprint
ON import_problems(status, path_key, observed_size, observed_modified_ns);

CREATE TABLE IF NOT EXISTS workspace_locks (
    lock_name TEXT PRIMARY KEY,
    owner_run_id TEXT NOT NULL,
    owner_token TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

同时按 spec 建立 `classification_profiles` 和 `asset_view_memberships` 空表，阶段 1 不写入这两张表。

- [ ] **Step 4: 实现 SQLite Backup API 和事务迁移**

`catalog/migrations.py` 提供：

```python
def migrate_catalog_v1_to_v2(catalog_path: Path, backups_dir: Path) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"catalog-v1-{timestamp}.sqlite"
    with sqlite3.connect(catalog_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    with sqlite3.connect(catalog_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            _migrate_imports(connection)
            _migrate_import_items(connection)
            _create_v2_support_tables(connection)
            _backfill_legacy_runs(connection)
            connection.execute(
                "UPDATE schema_meta SET schema_id=?, version=2",
                (SCHEMA_ID,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return backup_path
```

迁移使用“新表复制”而不是连续 `ALTER TABLE`：创建 `imports_v2` / `import_items_v2`，按 legacy 映射插入，删除旧表后改名。旧 `status=imported` 映射为 `decision=legacy,status=legacy`；旧 `failed` 和 `missing` 项分别创建 `legacy_failure`、`missing_path` open problem。

- [ ] **Step 5: 调整 Catalog 初始化顺序和 backups 路径**

`CatalogRepository.initialize()` 必须先只读检测版本：无 schema 时创建 v2；v1 时关闭检测连接，调用 Backup API 后再打开连接验证 v2；其他版本直接拒绝。构造签名固定为：

```python
def __init__(self, path: str | Path, *, backups_dir: str | Path | None = None):
    self.path = Path(path)
    self.backups_dir = Path(backups_dir) if backups_dir else self.path.parent / "backups"
    self.path.parent.mkdir(parents=True, exist_ok=True)
    self.initialize()
```

`WorkspacePaths` 增加：

```python
backups: Path
```

并由 `from_root()` 设置为 `workspace / "backups"`，`init_workspace()` 创建该目录。

- [ ] **Step 6: 运行迁移和现有 pipeline 测试**

Run:

```powershell
uv run pytest tests/test_catalog_v2_migration.py tests/test_pipeline.py -v
```

Expected: PASS；分类、Reader、Exporter 测试不因 schema 升级回归。

- [ ] **Step 7: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/catalog tools/publishing_workspace/src/publishing_workspace/config.py tools/publishing_workspace/tests/test_catalog_v2_migration.py tools/publishing_workspace/tests/test_pipeline.py
git commit -m "feat(publishing): migrate catalog to import run schema"
```

---

### Task 2: ImportRun 模型与持久化 Repository

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/models.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/repository.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/models.py:177-189`
- Create: `tools/publishing_workspace/tests/test_import_workflow.py`

**Interfaces:**
- Consumes: schema v2 `imports` 和 `import_items`。
- Produces: `ImportRunRecord`、`ImportItemRecord`、`ImportRunSummary`、`ImportCounters`。
- Produces: `ImportRunRepository.create_run(source_type: str, source_ref: str, mode: ImportMode, strict: bool) -> ImportRunRecord`。
- Produces: `ImportRunRepository.persist_selection(run_id, selection) -> None`。
- Produces: `ImportRunRepository.next_items(run_id, *, status, limit) -> list[ImportItemRecord]`。
- Produces: 所有批次写方法接受显式 `sqlite3.Connection`，供 Executor 保持一个批次一个事务。

- [ ] **Step 1: 写运行创建、Selection 持久化和计数测试**

```python
def make_item(order: int, path: str) -> ImportedItem:
    return ImportedItem(
        source_path=path,
        resolved_path=path,
        source_type="directory",
        source_ref="E:/images",
        source_order=order,
        display_name=Path(path).name,
    )


def make_run_repository(tmp_path: Path) -> ImportRunRepository:
    return ImportRunRepository(CatalogRepository(tmp_path / "catalog.sqlite"))


def test_import_run_repository_persists_selection_before_planning(tmp_path: Path):
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    run = runs.create_run(
        source_type="auto",
        source_ref="E:/selected.nvpls",
        mode="import",
        strict=False,
    )
    selection = SelectionSet(
        id=run.import_id,
        source_type="neev_playlist",
        source_ref="E:/selected.nvpls",
        items=[make_item(0, "E:/a.png"), make_item(1, "E:/b.png")],
    )
    runs.persist_selection(run.import_id, selection)

    stored = runs.get_run(run.import_id)
    items = runs.next_items(run.import_id, status="pending", limit=200)
    assert stored.status == "scanning"
    assert stored.total_items == 2
    assert stored.source_type == "neev_playlist"
    assert [item.source_order for item in items] == [0, 1]
    assert all(item.decision == "pending" and item.status == "pending" for item in items)


def test_import_run_repository_rejects_invalid_transition(tmp_path: Path):
    runs = make_run_repository(tmp_path)
    run = runs.create_run(source_type="auto", source_ref="x", mode="import", strict=False)
    with pytest.raises(ValueError, match="非法 ImportRun 状态转换"):
        runs.transition(run.import_id, status="completed", pipeline_stage="completed")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run pytest tests/test_import_workflow.py -v
```

Expected: FAIL with `ModuleNotFoundError: publishing_workspace.importing`。

- [ ] **Step 3: 定义导入领域模型**

`importing/models.py` 定义以下 Literal 和模型：

```python
ImportMode = Literal["import", "refresh", "retry_problems", "legacy"]
ImportRunStatus = Literal[
    "created", "scanning", "planned", "running", "completed",
    "completed_with_errors", "interrupted", "failed",
]
PipelineStage = Literal[
    "input", "planning", "execution", "classification", "export", "completed",
]
ImportDecision = Literal[
    "pending", "reuse_path", "parse", "missing_path", "empty_file",
    "hold_problem", "legacy",
]
ImportItemStatus = Literal[
    "pending", "planned", "processing", "reused_path", "reused_content",
    "parsed_new", "missing", "failed", "held_problem", "legacy",
]


class ImportCounters(BaseModel):
    total_items: int = 0
    planned_items: int = 0
    processed_items: int = 0
    reused_path_items: int = 0
    reused_content_items: int = 0
    parsed_new_items: int = 0
    missing_items: int = 0
    failed_items: int = 0
    held_problem_items: int = 0


class ImportRunRecord(BaseModel):
    import_id: str
    source_type: str
    source_ref: str
    source_fingerprint: str | None = None
    mode: ImportMode
    status: ImportRunStatus
    pipeline_stage: PipelineStage
    strict: bool = False
    counters: ImportCounters
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None


class ImportItemRecord(BaseModel):
    import_id: str
    source_order: int
    source_path: str
    resolved_path: str | None
    display_name: str
    observed_size: int | None = None
    observed_modified_ns: int | None = None
    decision: ImportDecision
    status: ImportItemStatus
    attempts: int = 0
    asset_id: str | None = None
    problem_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
```

`strict` 已由 Task 1 写入 schema；本任务只负责模型和 Repository 映射，`resume` 不依赖原 CLI 参数恢复严格模式。

- [ ] **Step 4: 实现 ImportRunRepository**

状态转换白名单固定为：

```python
ALLOWED_TRANSITIONS = {
    "created": {"scanning", "failed"},
    "scanning": {"planned", "interrupted", "failed"},
    "planned": {"running", "interrupted", "failed"},
    "running": {"completed", "completed_with_errors", "interrupted", "failed"},
    "interrupted": {"scanning", "planned", "running", "failed"},
    "completed": set(),
    "completed_with_errors": set(),
    "failed": set(),
}
```

`persist_selection()` 在一个短事务内插入全部输入项，初始 `decision=pending,status=pending`，同时更新 source_type、source_fingerprint、total_items 和 status=scanning。来源指纹实现为对以下 canonical JSON 做 SHA-256：

```python
{
    "source_type": selection.source_type,
    "source_ref": selection.source_ref,
    "items": [
        [item.source_order, item.source_path, item.resolved_path, item.display_name]
        for item in selection.items
    ],
}
```

Repository 必须额外提供：

- `mark_planned(connection: sqlite3.Connection, item: ImportItemRecord, *, decision: ImportDecision, size: int | None, modified_ns: int | None, problem_id: str | None = None) -> None`
- `mark_processing(connection: sqlite3.Connection, import_id: str, source_order: int) -> None`
- `complete_item(connection: sqlite3.Connection, import_id: str, source_order: int, *, status: ImportItemStatus, asset_id: str | None = None, problem_id: str | None = None, warnings: list[str] | None = None) -> None`
- `reset_processing_to_planned(import_id: str) -> int`
- `recalculate_counters(connection: sqlite3.Connection, import_id: str) -> ImportCounters`
- `latest_run() -> ImportRunRecord | None`
- `has_items(import_id: str, *, status: ImportItemStatus) -> bool`
- `has_unfinished_items(import_id: str) -> bool`

`has_unfinished_items()` 只把 `pending`、`planned`、`processing` 视为未完成；所有终态计数都由 `recalculate_counters()` 从 import_items 重算，避免进程中断造成累加计数漂移。

- [ ] **Step 5: 运行模型和 Repository 测试**

Run:

```powershell
uv run pytest tests/test_import_workflow.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/importing tools/publishing_workspace/src/publishing_workspace/catalog/schema.py tools/publishing_workspace/src/publishing_workspace/models.py tools/publishing_workspace/tests/test_import_workflow.py
git commit -m "feat(publishing): persist import runs and items"
```

---

### Task 3: ProblemQueue 与 ImportPlanner

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/problems/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/problems/repository.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/planner.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/repository.py`
- Create: `tools/publishing_workspace/tests/test_import_planner.py`

**Interfaces:**
- Consumes: `ImportRunRepository.next_items(run_id: str, status="pending", limit: int) -> list[ImportItemRecord]`。
- Produces: `CatalogRepository.lookup_path_asset(connection, path_key, size, modified_ns) -> str | None`，只读取现有 `asset_paths` 缓存，不更新 Catalog。
- Produces: `ProblemRepository.find_open_fingerprint(connection, path_key: str, size: int | None, modified_ns: int | None) -> ImportProblemRecord | None`。
- Produces: `ProblemRepository.record(connection, run_id: str, item: ImportItemRecord, path_key: str, error_code: ProblemCode, message: str, size: int | None, modified_ns: int | None) -> ImportProblemRecord`，同一 run/item/error 更新 attempts，不重复插入。
- Produces: `ImportPlanner.plan(run_id, *, retry_failed=False, batch_size=200, reporter=None) -> ImportPlanSummary`。

- [ ] **Step 1: 写完整决策矩阵测试**

```python
def make_pending_planner(
    tmp_path: Path,
    *,
    resolved_path: Path | None,
) -> tuple[ImportPlanner, ImportRunRepository, ProblemRepository, str]:
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    run = runs.create_run(
        source_type="directory",
        source_ref=str(tmp_path),
        mode="import",
        strict=False,
    )
    source_path = str(resolved_path or (tmp_path / "missing.png"))
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(tmp_path),
            items=[
                ImportedItem(
                    source_path=source_path,
                    resolved_path=str(resolved_path) if resolved_path else None,
                    source_type="directory",
                    source_ref=str(tmp_path),
                    source_order=0,
                    display_name=Path(source_path).name,
                )
            ],
        ),
    )
    return ImportPlanner(catalog, runs, problems), runs, problems, run.import_id


def test_planner_marks_missing_and_empty_without_reading_images(tmp_path: Path):
    missing_planner, missing_runs, _, missing_run = make_pending_planner(
        tmp_path / "missing-case", resolved_path=None
    )
    empty = tmp_path / "empty.png"
    empty.touch()
    empty_planner, empty_runs, _, empty_run = make_pending_planner(
        tmp_path / "empty-case", resolved_path=empty
    )

    missing_planner.plan(missing_run)
    empty_planner.plan(empty_run)

    assert missing_runs.get_item(missing_run, 0).decision == "missing_path"
    assert empty_runs.get_item(empty_run, 0).decision == "empty_file"


def test_planner_uses_path_cache_before_parse(tmp_path: Path):
    path = tmp_path / "cached.png"
    Image.new("RGB", (1, 1)).save(path)
    planner, runs, _, run_id = make_pending_planner(tmp_path / "cached-case", resolved_path=path)
    stat = path.stat()
    with planner.catalog.connection() as connection:
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sha256:cached", "cached", stat.st_size, 1, 1, "PNG", "unknown",
                "unknown", "[]", utc_now_iso(), utc_now_iso(),
            ),
        )
        connection.execute(
            "INSERT INTO asset_paths VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                normalize_path_key(path.resolve()), str(path.resolve()), "sha256:cached",
                stat.st_size, stat.st_mtime_ns, utc_now_iso(),
            ),
        )
    planner.plan(run_id)
    assert runs.get_item(run_id, 0).decision == "reuse_path"


def test_same_problem_is_held_unless_retry_is_forced(tmp_path: Path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not-an-image")
    planner, runs, problems, run_id = make_pending_planner(tmp_path / "problem-case", resolved_path=path)
    item = runs.get_item(run_id, 0)
    stat = path.stat()
    with planner.catalog.connection() as connection:
        problems.record(
            connection,
            run_id=run_id,
            item=item,
            path_key=normalize_path_key(path.resolve()),
            error_code="unreadable_image",
            message="cannot identify image",
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
    planner.plan(run_id)
    assert runs.get_item(run_id, 0).decision == "hold_problem"

    retry_planner, retry_runs, retry_problems, retry_run = make_pending_planner(
        tmp_path / "retry-case", resolved_path=path
    )
    retry_item = retry_runs.get_item(retry_run, 0)
    with retry_planner.catalog.connection() as connection:
        retry_problems.record(
            connection,
            run_id=retry_run,
            item=retry_item,
            path_key=normalize_path_key(path.resolve()),
            error_code="unreadable_image",
            message="cannot identify image",
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
    retry_planner.plan(retry_run, retry_failed=True)
    assert retry_runs.get_item(retry_run, 0).decision == "parse"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run pytest tests/test_import_planner.py -v
```

Expected: FAIL，planner 和 problem repository 尚不存在。

- [ ] **Step 3: 实现 ProblemRepository**

先在 `problems/repository.py` 定义：

```python
ProblemStatus = Literal["open", "resolved", "ignored"]
ProblemCode = Literal[
    "missing_path", "empty_file", "unreadable_image", "unsupported_format",
    "metadata_read_error", "shortcut_resolve_error", "legacy_failure",
]


class ImportProblemRecord(BaseModel):
    problem_id: str
    import_id: str
    source_order: int
    path_key: str | None = None
    source_path: str
    error_code: ProblemCode
    message: str
    observed_size: int | None = None
    observed_modified_ns: int | None = None
    status: ProblemStatus
    attempts: int = 1
    created_at: str
    updated_at: str
    resolved_at: str | None = None
```

在 `importing/planner.py` 定义：

```python
class ImportPlanSummary(BaseModel):
    run_id: str
    planned_items: int
    decisions: dict[ImportDecision, int] = Field(default_factory=dict)
```

问题指纹比较规则为：

```python
def same_fingerprint(problem, *, path_key, size, modified_ns) -> bool:
    return (
        problem.status == "open"
        and problem.path_key == path_key
        and problem.observed_size == size
        and problem.observed_modified_ns == modified_ns
    )
```

公开方法的精确签名：

- `find_open_fingerprint(connection: sqlite3.Connection, *, path_key: str, size: int | None, modified_ns: int | None) -> ImportProblemRecord | None`
- `record(connection: sqlite3.Connection, *, run_id: str, item: ImportItemRecord, path_key: str, error_code: ProblemCode, message: str, size: int | None, modified_ns: int | None) -> ImportProblemRecord`
- `resolve_matching(connection: sqlite3.Connection, *, path_key: str, size: int | None, modified_ns: int | None) -> int`
- `list(*, status: ProblemStatus | None = None, run_id: str | None = None, error_code: ProblemCode | None = None) -> list[ImportProblemRecord]`

`record()` 对同一 `import_id + source_order + error_code` 更新 attempts、message、updated_at；不同 Run 保留独立问题历史。

- [ ] **Step 4: 实现 Planner 决策顺序**

`ImportPlanner._decide()` 固定执行：

```python
if not item.resolved_path or not path.exists():
    return decision_for_problem("missing_path", path_key, None, None)
stat = path.stat()
if stat.st_size == 0:
    return decision_for_problem("empty_file", path_key, 0, stat.st_mtime_ns)
cached_asset = catalog.lookup_path_asset(connection, path_key, stat.st_size, stat.st_mtime_ns)
if cached_asset:
    return PlannedDecision("reuse_path", stat.st_size, stat.st_mtime_ns, cached_asset)
open_problem = problems.find_open_fingerprint(
    connection, path_key=path_key, size=stat.st_size, modified_ns=stat.st_mtime_ns
)
if open_problem and not retry_failed:
    return PlannedDecision(
        "hold_problem", stat.st_size, stat.st_mtime_ns, problem_id=open_problem.problem_id
    )
return PlannedDecision("parse", stat.st_size, stat.st_mtime_ns)
```

其中 `decision_for_problem()` 在相同 open problem 且未强制重试时返回 `hold_problem`，否则返回 `missing_path` 或 `empty_file`。每 200 项在同一事务中将 pending 更新为 planned；planning 中断后下次从最小 pending source_order 继续。

同时把现有私有 `_path_key()` 重命名并公开为 `normalize_path_key(path: Path) -> str`，Planner、ProblemRepository 和 Catalog ingest 共用同一条 Windows 路径规范化规则。

- [ ] **Step 5: 运行 Planner 测试**

Run:

```powershell
uv run pytest tests/test_import_planner.py -v
```

Expected: PASS；Reader stub 调用数始终为 0。

- [ ] **Step 6: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/problems tools/publishing_workspace/src/publishing_workspace/importing/planner.py tools/publishing_workspace/src/publishing_workspace/catalog/repository.py tools/publishing_workspace/tests/test_import_planner.py
git commit -m "feat(publishing): plan imports and retain problems"
```

---

### Task 4: 拆分 Catalog Asset Ingest API

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/repository.py:115-317`
- Modify: `tools/publishing_workspace/src/publishing_workspace/catalog/__init__.py`
- Create: `tools/publishing_workspace/tests/test_catalog_ingest.py`

**Interfaces:**
- Consumes: 显式 `sqlite3.Connection`、图片路径、Planner 已观察到的 size/modified_ns、ReaderRegistry 和 Enricher。
- Produces: `CatalogIngestResult(asset: AssetRecord, outcome: Literal["reused_path", "reused_content", "parsed_new"])`。
- Produces: `CatalogRepository.lookup_path_asset(connection, path_key, size, modified_ns) -> str | None`。
- Produces: `CatalogRepository.ingest_asset(connection, path, *, expected_size, expected_modified_ns, readers, enrichers) -> CatalogIngestResult`。
- Removes: `CatalogRepository.import_selection()`、`_import_item()` 和 `_insert_import_item()` 的运行编排职责。

- [ ] **Step 1: 写三种 ingest 结果和文件竞争测试**

```python
def make_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), "white").save(path)
    return path


class FailIfCalledReaders:
    def read(self, path: Path, metadata: dict) -> ImageNodeInfo:
        raise AssertionError("reused_path 不应调用 Reader")


def ingest(repository: CatalogRepository, path: Path) -> CatalogIngestResult:
    stat = path.stat()
    with repository.connection() as connection:
        return repository.ingest_asset(
            connection,
            path,
            expected_size=stat.st_size,
            expected_modified_ns=stat.st_mtime_ns,
            readers=default_image_node_reader_registry(),
            enrichers=[],
        )


def ingest_with_expected(
    repository: CatalogRepository,
    path: Path,
    size: int,
    modified_ns: int,
) -> CatalogIngestResult:
    with repository.connection() as connection:
        return repository.ingest_asset(
            connection,
            path,
            expected_size=size,
            expected_modified_ns=modified_ns,
            readers=default_image_node_reader_registry(),
            enrichers=[],
        )


def test_ingest_reports_parsed_new_then_reused_path(tmp_path: Path):
    path = make_png(tmp_path / "a.png")
    repository = CatalogRepository(tmp_path / "catalog.sqlite")
    stat = path.stat()
    with repository.connection() as connection:
        first = repository.ingest_asset(
            connection,
            path,
            expected_size=stat.st_size,
            expected_modified_ns=stat.st_mtime_ns,
            readers=default_image_node_reader_registry(),
            enrichers=[],
        )
    with repository.connection() as connection:
        second = repository.ingest_asset(
            connection,
            path,
            expected_size=stat.st_size,
            expected_modified_ns=stat.st_mtime_ns,
            readers=FailIfCalledReaders(),
            enrichers=[],
        )
    assert first.outcome == "parsed_new"
    assert second.outcome == "reused_path"


def test_ingest_reuses_content_at_new_path(tmp_path: Path):
    first_path = make_png(tmp_path / "a.png")
    second_path = tmp_path / "b.png"
    shutil.copy2(first_path, second_path)
    repository = CatalogRepository(tmp_path / "catalog.sqlite")
    first = ingest(repository, first_path)
    second = ingest(repository, second_path)
    assert first.asset.asset_id == second.asset.asset_id
    assert second.outcome == "reused_content"


def test_ingest_rejects_file_changed_after_planning(tmp_path: Path):
    path = make_png(tmp_path / "a.png")
    stat = path.stat()
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(RuntimeError, match="规划后发生变化"):
        ingest_with_expected(repository, path, stat.st_size, stat.st_mtime_ns)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run pytest tests/test_catalog_ingest.py -v
```

Expected: FAIL，公开 ingest 接口不存在。

- [ ] **Step 3: 实现事务内 Asset ingest**

`ingest_asset()` 开始时重新 `stat`，若 size 或 modified_ns 与 Planner 记录不同则抛出 `AssetChangedAfterPlanningError`，由 Executor 把项目重置为 pending，而不是使用过期决策。处理顺序保持：路径指纹命中 -> SHA 命中 -> Pillow/metadata/Reader/Enricher 新解析。

`CatalogIngestResult` 定义为：

```python
class AssetChangedAfterPlanningError(RuntimeError):
    pass


class CatalogIngestResult(BaseModel):
    asset: AssetRecord
    outcome: Literal["reused_path", "reused_content", "parsed_new"]
```

`lookup_path_asset()` 只查询，不更新 `last_seen_at`；真正执行 `reuse_path` 时由 `ingest_asset()` 更新 available 和 last_seen_at。

- [ ] **Step 4: 删除旧一次性导入编排并运行回归测试**

在 Task 6 接入新 workflow 前，旧 `PublishingService.import_source()` 暂时会失败。因此本步骤只运行 Catalog、Reader、分类和导出测试，不运行旧 CLI import 测试：

```powershell
uv run pytest tests/test_catalog_ingest.py tests/test_png_metadata.py tests/test_pipeline.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/catalog tools/publishing_workspace/tests/test_catalog_ingest.py
git commit -m "refactor(publishing): isolate catalog asset ingestion"
```

---

### Task 5: ImportExecutor、批次事务、租约锁与 ProgressReporter

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/locks.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/progress.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/executor.py`
- Create: `tools/publishing_workspace/tests/test_import_executor.py`

**Interfaces:**
- Consumes: planned `ImportItemRecord`、Catalog ingest API、ProblemRepository、ReaderRegistry、Enricher。
- Produces: `WorkspaceLeaseRepository.acquire(run_id, *, allow_takeover) -> WorkspaceLease`。
- Produces: `WorkspaceLeaseRepository.refresh(connection, lease) -> WorkspaceLease` 和 `WorkspaceLeaseRepository.release(lease) -> None`。
- Produces: `ProgressReporter.emit(event, *, current, total, counters, force=False) -> None`。
- Produces: `ImportExecutor.execute(run_id: str, *, lease: WorkspaceLease, batch_size: int = 200, reporter: ProgressReporter | None = None) -> ImportExecutionSummary`。

- [ ] **Step 1: 写租约、批次提交和恢复测试**

```python
class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def make_lease_repository(
    tmp_path: Path,
    clock: FakeClock | None = None,
) -> WorkspaceLeaseRepository:
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    return WorkspaceLeaseRepository(catalog, now=(clock or FakeClock()).now)


@dataclass
class PlannedWorkflow:
    catalog: CatalogRepository
    runs: ImportRunRepository
    problems: ProblemRepository
    leases: WorkspaceLeaseRepository
    run_id: str

    def executor(self) -> ImportExecutor:
        return ImportExecutor(
            catalog=self.catalog,
            runs=self.runs,
            problems=self.problems,
            readers=default_image_node_reader_registry(),
            enrichers=[],
        )


def make_planned_workflow(tmp_path: Path, *, item_count: int) -> PlannedWorkflow:
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    leases = WorkspaceLeaseRepository(catalog)
    run = runs.create_run(
        source_type="directory",
        source_ref=str(tmp_path / "images"),
        mode="import",
        strict=False,
    )
    items = []
    for index in range(item_count):
        path = tmp_path / "images" / f"{index:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1, 1), (index % 255, 0, 0)).save(path)
        items.append(
            ImportedItem(
                source_path=str(path), resolved_path=str(path), source_type="directory",
                source_ref=str(path.parent), source_order=index, display_name=path.name,
            )
        )
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(tmp_path / "images"),
            items=items,
        ),
    )
    ImportPlanner(catalog, runs, problems).plan(run.import_id)
    return PlannedWorkflow(catalog, runs, problems, leases, run.import_id)


class InterruptAfterFirstBatchReporter:
    def emit(self, event: str, *, current: int, total: int, counters, force: bool = False):
        if event == "execution_progress" and current >= 200:
            raise KeyboardInterrupt


def test_active_lease_blocks_second_writer(tmp_path: Path):
    leases = make_lease_repository(tmp_path)
    first = leases.acquire("run-a", allow_takeover=False)
    with pytest.raises(RuntimeError, match="run-a"):
        leases.acquire("run-b", allow_takeover=False)
    leases.release(first)


def test_expired_lease_can_only_be_taken_over_explicitly(tmp_path: Path, clock):
    leases = make_lease_repository(tmp_path, clock=clock)
    leases.acquire("run-a", allow_takeover=False)
    clock.advance(seconds=91)
    with pytest.raises(RuntimeError, match="需要 resume 接管"):
        leases.acquire("run-b", allow_takeover=False)
    lease = leases.acquire("run-a", allow_takeover=True)
    assert lease.owner_run_id == "run-a"


def test_executor_commits_completed_batches_before_interruption(tmp_path: Path):
    workflow = make_planned_workflow(tmp_path, item_count=450)
    executor = workflow.executor()
    lease = workflow.leases.acquire(workflow.run_id, allow_takeover=False)
    with pytest.raises(KeyboardInterrupt):
        executor.execute(
            workflow.run_id,
            lease=lease,
            batch_size=200,
            reporter=InterruptAfterFirstBatchReporter(),
        )
    workflow.leases.release(lease)
    assert workflow.runs.get_run(workflow.run_id).counters.processed_items == 200
    assert len(workflow.runs.next_items(workflow.run_id, status="planned", limit=500)) == 250


def test_resume_resets_processing_and_continues_in_source_order(tmp_path: Path):
    workflow = make_planned_workflow(tmp_path, item_count=3)
    with workflow.catalog.connection() as connection:
        connection.execute(
            "UPDATE import_items SET status='processing' WHERE import_id=? AND source_order=0",
            (workflow.run_id,),
        )
    assert workflow.runs.reset_processing_to_planned(workflow.run_id) == 1
    lease = workflow.leases.acquire(workflow.run_id, allow_takeover=False)
    workflow.executor().execute(workflow.run_id, lease=lease, batch_size=2)
    workflow.leases.release(lease)
    with workflow.catalog.connection() as connection:
        rows = connection.execute(
            "SELECT source_order, status FROM import_items WHERE import_id=? ORDER BY source_order",
            (workflow.run_id,),
        ).fetchall()
    assert [row["source_order"] for row in rows] == [0, 1, 2]
    assert all(row["status"] == "parsed_new" for row in rows)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
uv run pytest tests/test_import_executor.py -v
```

Expected: FAIL，executor、lease 和 reporter 尚不存在。

- [ ] **Step 3: 实现 90 秒租约锁**

锁名固定为 `publishing_import`，默认租约 `90` 秒。`acquire()` 使用 `BEGIN IMMEDIATE` 原子检查并写入；未过期锁始终拒绝，过期锁只有 `allow_takeover=True` 且 owner_run_id 与恢复 run 一致时可接管。owner_token 使用 `uuid4().hex`，刷新和释放必须同时匹配 run_id 与 token。

公开类型和签名固定为：

```python
class WorkspaceLease(BaseModel):
    lock_name: str
    owner_run_id: str
    owner_token: str
    lease_expires_at: str
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ImportStrictFailure(RuntimeError):
    pass


class ImportExecutionSummary(BaseModel):
    run_id: str
    processed_this_call: int
    counters: ImportCounters
```

- `WorkspaceLeaseRepository.acquire(run_id: str, *, allow_takeover: bool) -> WorkspaceLease`
- `WorkspaceLeaseRepository.refresh(connection: sqlite3.Connection, lease: WorkspaceLease) -> WorkspaceLease`
- `WorkspaceLeaseRepository.release(lease: WorkspaceLease) -> None`

Executor 接收 `WorkspaceLeaseRepository` 和当前 `WorkspaceLease`，不把数据库连接保存到 Pydantic 模型中。

- [ ] **Step 4: 实现节流进度事件**

`ProgressReporter` 构造签名：

```python
def __init__(
    self,
    *,
    logger: logging.Logger,
    every_items: int = 200,
    every_seconds: float = 5.0,
    monotonic: Callable[[], float] = time.monotonic,
):
    self.logger = logger
    self.every_items = every_items
    self.every_seconds = every_seconds
    self.monotonic = monotonic
    self._last_item = 0
    self._last_time = monotonic()
```

`trace` 输出单项 source_order、decision、path；`info` 输出阶段开始、节流进度和结束；`warning` 输出新问题或 held problem；`error` 只用于 Run 无法继续。最终结构化结果不经过 logger，仍由 CLI 输出 stdout。

- [ ] **Step 5: 实现 Executor 批次状态机**

每个批次必须在同一个 `CatalogRepository.connection()` 中执行：

```python
for item in batch:
    runs.mark_processing(connection, run_id, item.source_order)
    if item.decision == "reuse_path":
        complete_catalog_item(connection, item)
    elif item.decision == "parse":
        complete_catalog_item(connection, item)
    elif item.decision in {"missing_path", "empty_file"}:
        complete_problem_item(connection, item)
    elif item.decision == "hold_problem":
        runs.complete_item(
            connection, run_id, item.source_order,
            status="held_problem", problem_id=item.problem_id,
        )
runs.recalculate_counters(connection, run_id)
lease = leases.refresh(connection, lease)
```

异常分类固定为：`FileNotFoundError -> missing_path`、`UnidentifiedImageError -> unreadable_image`、不支持扩展名 -> `unsupported_format`、Reader 抛出的 `ImageNodeReadError -> metadata_read_error`、其他单项异常 -> `unreadable_image`。`strict=False` 记录问题后继续；`strict=True` 完成当前失败项后设置批次级 `strict_failure` 标记，先正常离开事务并提交当前批次，再抛出 `ImportStrictFailure`，由 workflow 标记 interrupted，不能在事务内部直接抛出导致已处理项回滚。

若捕获 `AssetChangedAfterPlanningError`，把该项恢复为 `decision=pending,status=pending`，当前批次提交后回到 Planner，不记录错误问题。

- [ ] **Step 6: 运行 Executor 测试**

Run:

```powershell
uv run pytest tests/test_import_executor.py -v
```

Expected: PASS；450 项模拟中断后数据库明确保留 200 个完成项。

- [ ] **Step 7: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/importing tools/publishing_workspace/tests/test_import_executor.py
git commit -m "feat(publishing): execute recoverable import batches"
```

---

### Task 6: ImportWorkflowService 与 PublishingService 接入

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/importing/service.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/importing/__init__.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/service.py:43-92`
- Modify: `tools/publishing_workspace/src/publishing_workspace/models.py:177-189`
- Modify: `tools/publishing_workspace/tests/test_import_workflow.py`

**Interfaces:**
- Consumes: InputAdapterRegistry、ImportRunRepository、Planner、Executor、Lease、ProblemRepository。
- Produces: `ImportWorkflowService.import_source(source: str | Path, input_type: str | None, context: InputContext, strict: bool, retry_failed: bool) -> ImportRunSummary`。
- Produces: `ImportWorkflowService.resume(run_id: str) -> ImportRunSummary`，不再次调用 InputAdapter。
- Produces: `ImportWorkflowService.retry_problems(run_id: str | None, error_code: ProblemCode | None) -> ImportRunSummary`。
- Produces: 完成后原子写入 `workspace/imports/<run_id>.json`。

- [ ] **Step 1: 写端到端导入、重复复用和 resume 测试**

```python
def make_workspace_with_images(tmp_path: Path, *, count: int) -> tuple[Path, Path]:
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir(parents=True)
    for index in range(count):
        Image.new("RGB", (2, 2), (index, 0, 0)).save(source / f"{index}.png")
    init_workspace(root)
    return root, source


class FailIfLoadedInputRegistry:
    def load(self, *args, **kwargs):
        raise AssertionError("resume 不应重新调用 InputAdapter")


def make_interrupted_run(tmp_path: Path) -> tuple[Path, str]:
    root, source = make_workspace_with_images(tmp_path, count=1)
    paths, _ = load_workspace(root)
    catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    run = runs.create_run(
        source_type="directory",
        source_ref=str(source),
        mode="import",
        strict=False,
    )
    image = source / "0.png"
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(source),
            items=[
                ImportedItem(
                    source_path=str(image), resolved_path=str(image), source_type="directory",
                    source_ref=str(source), source_order=0, display_name=image.name,
                )
            ],
        ),
    )
    ImportPlanner(catalog, runs, problems).plan(run.import_id)
    runs.transition(run.import_id, status="planned", pipeline_stage="execution")
    runs.transition(run.import_id, status="running", pipeline_stage="execution")
    runs.interrupt(run.import_id, reason="test interruption")
    return root, run.import_id


def test_workflow_imports_then_reuses_same_selection(tmp_path: Path):
    root, source = make_workspace_with_images(tmp_path, count=3)
    first = PublishingService().import_source(root, source, input_type="directory")
    second = PublishingService().import_source(root, source, input_type="directory")
    assert first.status == "completed"
    assert first.parsed_new_items == 3
    assert second.status == "completed"
    assert second.reused_path_items == 3
    assert second.parsed_new_items == 0


def test_resume_does_not_reload_input_adapter(tmp_path: Path, monkeypatch):
    root, run_id = make_interrupted_run(tmp_path)
    monkeypatch.setattr(
        "publishing_workspace.service.default_input_registry",
        lambda: FailIfLoadedInputRegistry(),
    )
    result = PublishingService().resume_import(root, run_id)
    assert result.status == "completed"


def test_completed_snapshot_is_written_once(tmp_path: Path, monkeypatch):
    root, source = make_workspace_with_images(tmp_path, count=1)
    writes = []
    monkeypatch.setattr(
        "publishing_workspace.importing.service.write_json_atomic",
        lambda path, data: writes.append((path, data)),
    )
    result = PublishingService().import_source(root, source, input_type="directory")
    assert len(writes) == 1
    assert writes[0][0].name == f"{result.run_id}.json"
    assert writes[0][1]["schema"] == "publishing-workspace.import-run/v2"
```

- [ ] **Step 2: 运行 workflow 测试确认失败**

Run:

```powershell
uv run pytest tests/test_import_workflow.py -v
```

Expected: FAIL，PublishingService 仍调用已删除的 `import_selection()`。

- [ ] **Step 3: 实现 ImportWorkflowService 编排**

新导入顺序固定为：

```python
run = runs.create_run(source_type=input_type or "auto", source_ref=str(source), mode="import", strict=strict)
lease = leases.acquire(run.import_id, allow_takeover=False)
try:
    selection = inputs.load(source, input_type=input_type, context=context)
    selection = selection.model_copy(update={"id": run.import_id})
    runs.persist_selection(run.import_id, selection)
    planner.plan(run.import_id, retry_failed=retry_failed, reporter=reporter)
    runs.transition(run.import_id, status="planned", pipeline_stage="execution")
    runs.transition(run.import_id, status="running", pipeline_stage="execution")
    while runs.has_unfinished_items(run.import_id):
        if runs.has_items(run.import_id, status="pending"):
            planner.plan(run.import_id, retry_failed=retry_failed, reporter=reporter)
        executor.execute(run.import_id, reporter=reporter, lease=lease)
    summary = runs.finalize(run.import_id)
    write_snapshot(summary)
    return summary
except KeyboardInterrupt:
    runs.interrupt(run.import_id, reason="keyboard_interrupt")
    raise
except ImportStrictFailure as exc:
    runs.interrupt(run.import_id, reason=str(exc))
    return runs.summary(run.import_id)
except Exception as exc:
    runs.fail(run.import_id, exc)
    raise
finally:
    leases.release(lease)
```

`resume()` 先校验状态属于 created/scanning/planned/running/interrupted，再以 `allow_takeover=True` 获取同一 run 的租约，重置 processing，继续 pending planning 和 planned execution。它只读数据库中的 import_items，不接收 source 或 input 参数。

- [ ] **Step 4: 定义最终 ImportRunSummary 和快照**

```python
class ImportRunSummary(BaseModel):
    run_id: str
    status: ImportRunStatus
    pipeline_stage: PipelineStage
    source_type: str
    source_ref: str
    total_items: int
    planned_items: int
    processed_items: int
    reused_path_items: int
    reused_content_items: int
    parsed_new_items: int
    missing_items: int
    failed_items: int
    held_problem_items: int
    unique_assets: int
    open_problems: int
    reader_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    snapshot_path: str | None = None
```

快照包含 `schema`、`run`、按 source_order 排序的 `items`、`problems`、`reader_counts` 和去重 warnings。运行中不写临时大 JSON。

- [ ] **Step 5: PublishingService 只保留 Facade**

`PublishingService.import_source()` 保留现有基础参数并增加 `retry_failed: bool = False`，内部只负责 load workspace、构造依赖和调用 workflow。增加以下精确签名：

- `resume_import(root: str | Path, run_id: str) -> ImportRunSummary`
- `import_status(root: str | Path, run_id: str | None = None) -> ImportRunRecord`
- `list_problems(root: str | Path, *, status: ProblemStatus | None = "open", run_id: str | None = None, error_code: ProblemCode | None = None) -> list[ImportProblemRecord]`
- `retry_problems(root: str | Path, *, run_id: str | None = None, error_code: ProblemCode | None = None) -> ImportRunSummary`

`classify()` 和 `export()` 继续通过 CatalogRepository 读取完成或带错误完成的历史 import_items，不改变 ViewBuilder/Exporter 接口。

- [ ] **Step 6: 运行完整 Python 测试**

Run:

```powershell
uv run pytest -v
```

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/importing tools/publishing_workspace/src/publishing_workspace/service.py tools/publishing_workspace/src/publishing_workspace/models.py tools/publishing_workspace/tests/test_import_workflow.py
git commit -m "feat(publishing): orchestrate resumable imports"
```

---

### Task 7: CLI 状态、恢复和问题重试命令

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/cli.py`
- Modify: `tools/publishing_workspace/tests/test_cli.py`
- Modify: `tools/publishing_workspace/README.md`

**Interfaces:**
- Consumes: Task 6 的 PublishingService Facade。
- Produces: `status ROOT [RUN_ID]`、`resume ROOT RUN_ID`、`problems ROOT`、`retry-problems ROOT`。
- Produces: 所有命令 stdout 为 JSON；错误说明写 stderr 并返回 exit code 1。

- [ ] **Step 1: 写 CLI 业务输出测试**

```python
def make_empty_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "publish"
    init_workspace(root)
    return root


def make_cli_interrupted_workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    root = make_empty_workspace(tmp_path)
    source = tmp_path / "images"
    source.mkdir()
    image = source / "a.png"
    Image.new("RGB", (1, 1)).save(image)
    paths, _ = load_workspace(root)
    catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    run = runs.create_run(
        source_type="directory", source_ref=str(source), mode="import", strict=False
    )
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(source),
            items=[
                ImportedItem(
                    source_path=str(image), resolved_path=str(image), source_type="directory",
                    source_ref=str(source), source_order=0, display_name=image.name,
                )
            ],
        ),
    )
    ImportPlanner(catalog, runs, problems).plan(run.import_id)
    runs.transition(run.import_id, status="planned", pipeline_stage="execution")
    runs.transition(run.import_id, status="running", pipeline_stage="execution")
    runs.interrupt(run.import_id, reason="cli test")
    return root, source, run.import_id


def test_cli_status_resume_and_problems(tmp_path: Path, capsys):
    root, source, interrupted_run = make_cli_interrupted_workspace(tmp_path)

    assert main(["status", str(root), interrupted_run]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["import_id"] == interrupted_run
    assert status["status"] == "interrupted"

    assert main(["resume", str(root), interrupted_run]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["run_id"] == interrupted_run
    assert resumed["status"] in {"completed", "completed_with_errors"}

    assert main(["problems", str(root), "--status", "open"]) == 0
    problems = json.loads(capsys.readouterr().out)
    assert problems["count"] == len(problems["items"])


def test_cli_retry_problems_requires_matching_open_problem(tmp_path: Path, capsys):
    root = make_empty_workspace(tmp_path)
    assert main(["retry-problems", str(root), "--code", "empty_file"]) == 1
    assert "没有匹配的 open problem" in capsys.readouterr().err
```

- [ ] **Step 2: 运行 CLI 测试确认失败**

Run:

```powershell
uv run pytest tests/test_cli.py -v
```

Expected: FAIL，新命令尚未注册。

- [ ] **Step 3: 注册命令和参数**

`import` 增加：

```text
--retry-failed   强制重试相同文件指纹的 open problem
```

新增命令：

```text
status ROOT [RUN_ID]
resume ROOT RUN_ID
problems ROOT [--status open|resolved|ignored] [--run-id ID] [--code CODE]
retry-problems ROOT [--run-id ID] [--code CODE]
```

`status` 无 RUN_ID 时优先返回未过期活动锁对应 Run，否则返回最新 Run。`resume` 只恢复原 run_id。`retry-problems` 创建 mode=retry_problems 的新 Run，输入顺序按原 import_id 创建时间和 source_order 稳定排序。

- [ ] **Step 4: 补充 README 使用说明**

README 必须给出以下完整示例，并说明阶段 1 的 `classify`、`export` 仍是全量：

```powershell
uv run publishing-workspace import G:\ai_publish E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls --log-level info
uv run publishing-workspace status G:\ai_publish
uv run publishing-workspace resume G:\ai_publish <run_id> --log-level info
uv run publishing-workspace problems G:\ai_publish --status open
uv run publishing-workspace retry-problems G:\ai_publish --code empty_file --log-level info
```

- [ ] **Step 5: 运行 CLI 和完整回归测试**

Run:

```powershell
uv run pytest tests/test_cli.py -v
uv run pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```powershell
git add tools/publishing_workspace/src/publishing_workspace/cli.py tools/publishing_workspace/tests/test_cli.py tools/publishing_workspace/README.md
git commit -m "feat(publishing): expose import recovery commands"
```

---

### Task 8: 真实 10010 项 NeeView 列表业务验收

**Files:**
- Create: `tools/publishing_workspace/scripts/accept_recoverable_import.py`
- Create: `tools/publishing_workspace/docs/acceptance-recoverable-import.md`
- Modify: `tools/publishing_workspace/README.md`

**Interfaces:**
- Consumes: `E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls` 和原图只读路径。
- Consumes: 独立验收 workspace `G:/ai_publish_acceptance/recoverable-import-20260801`。
- Produces: `acceptance-recoverable-import.md`，记录首次导入、重复导入、中断恢复和问题保持结果。
- Produces: 不修改长期公共 workspace `G:/ai_publish`。

- [ ] **Step 1: 实现真实验收脚本**

脚本接受：

```text
--workspace G:/ai_publish_acceptance/recoverable-import-20260801
--playlist E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls
--mode first|repeat|interrupt-resume|report
```

`first` 初始化 workspace 并执行一次 import；`repeat` 对同一列表再次执行；`interrupt-resume` 启动子进程，在 SQLite 中观察 `processed_items >= 200` 后终止进程，再调用 resume；`report` 只读 SQLite 汇总最近运行。脚本不得删除已存在 workspace；若 `first` 目标已包含 import，必须拒绝并提示换新目录。

核心中断逻辑固定为：

```python
def wait_for_latest_run(catalog: Path, *, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if catalog.exists():
            with sqlite3.connect(catalog) as connection:
                row = connection.execute(
                    "SELECT import_id FROM imports ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            if row:
                return str(row[0])
        time.sleep(0.2)
    raise TimeoutError("等待 ImportRun 创建超时")


def wait_for_processed_items(
    catalog: Path,
    run_id: str,
    *,
    minimum: int,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with sqlite3.connect(catalog) as connection:
            row = connection.execute(
                "SELECT processed_items FROM imports WHERE import_id=?",
                (run_id,),
            ).fetchone()
        if row and int(row[0]) >= minimum:
            return
        time.sleep(0.5)
    raise TimeoutError(f"等待 processed_items >= {minimum} 超时")


def wait_for_lease_expiry(catalog: Path, *, timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with sqlite3.connect(catalog) as connection:
            row = connection.execute(
                "SELECT lease_expires_at FROM workspace_locks "
                "WHERE lock_name='publishing_import'"
            ).fetchone()
        if row is None or datetime.fromisoformat(row[0]) <= datetime.now(timezone.utc):
            return
        time.sleep(0.5)
    raise TimeoutError("等待写入租约过期超时")


project_root = Path(__file__).resolve().parents[1]
workspace = Path(args.workspace).expanduser().resolve()
playlist = Path(args.playlist).expanduser().resolve()
catalog = workspace / "workspace" / "catalog.sqlite"
base_command = [sys.executable, "-m", "publishing_workspace"]
command = [
    *base_command,
    "import",
    str(workspace),
    str(playlist),
    "--input-type",
    "neev_playlist",
    "--log-level",
    "info",
]
process = subprocess.Popen(command, cwd=project_root)
run_id = wait_for_latest_run(catalog, timeout_seconds=30)
wait_for_processed_items(catalog, run_id, minimum=200, timeout_seconds=300)
process.terminate()
process.wait(timeout=30)
wait_for_lease_expiry(catalog)
subprocess.run(
    [*base_command, "resume", str(workspace), run_id, "--log-level", "info"],
    check=True,
)
```

- [ ] **Step 2: 运行首次真实导入**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run python scripts/accept_recoverable_import.py --workspace G:/ai_publish_acceptance/recoverable-import-20260801 --playlist E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls --mode first
```

Expected business result:

```text
total_items = 10010
processed_items = 10010
parsed_new_items + reused_content_items + reused_path_items = 9987
missing_items + failed_items + held_problem_items = 23
open_problems = 23
status = completed_with_errors
```

同时确认 `info` 日志在长时间处理中持续输出，不再出现 13 分钟无反馈。

- [ ] **Step 3: 运行相同列表重复导入**

Run:

```powershell
uv run python scripts/accept_recoverable_import.py --workspace G:/ai_publish_acceptance/recoverable-import-20260801 --playlist E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls --mode repeat
```

Expected business result:

```text
reused_path_items = 9987
parsed_new_items = 0
held_problem_items = 23
open_problems = 23
```

记录第一次和第二次总耗时；第二次必须明显快于第一次，并通过 trace 抽查确认未调用 Pillow/Reader 处理 reused_path 项。

- [ ] **Step 4: 在独立验收 workspace 运行中断恢复**

Run:

```powershell
uv run python scripts/accept_recoverable_import.py --workspace G:/ai_publish_acceptance/recoverable-import-resume-20260801 --playlist E:/NeeView41.3/Profile/Playlists/合_20260728.nvpls --mode interrupt-resume
```

Expected business result:

```text
interrupted committed_items >= 200
resumed run_id == interrupted run_id
final processed_items = 10010
final successful items = 9987
final open_problems = 23
duplicate import_items = 0
```

- [ ] **Step 5: 确认现有全量分类和导出仍工作**

Run:

```powershell
uv run publishing-workspace classify G:/ai_publish_acceptance/recoverable-import-20260801
uv run publishing-workspace export G:/ai_publish_acceptance/recoverable-import-20260801 --exporter neev
```

Expected business result:

```text
views = 4626
unknown views = 25
```

分类和导出输出内容与原阶段 1 验收一致；本阶段不要求它们变成增量。

- [ ] **Step 6: 写验收报告并运行最终检查**

`docs/acceptance-recoverable-import.md` 必须记录每个 Run 的 run_id、状态、各计数、耗时、问题 code 分布、快照路径、Catalog 路径和分类视图数。然后运行：

```powershell
uv run pytest -v
uv run ruff check src tests scripts
git status --short
```

Expected: pytest 和 ruff PASS；`git status` 只显示本任务验收文档/脚本及用户原有未提交文件。

- [ ] **Step 7: 提交**

```powershell
git add tools/publishing_workspace/scripts/accept_recoverable_import.py tools/publishing_workspace/docs/acceptance-recoverable-import.md tools/publishing_workspace/README.md
git commit -m "test(publishing): validate recoverable import workflow"
```

---

## Final Verification

- [ ] 确认 v1 Catalog 迁移前生成 SQLite Backup API 一致性备份，迁移失败时原库仍是 v1。
- [ ] 确认历史 imported item 为 `decision=legacy,status=legacy`。
- [ ] 确认 InputAdapter 成功后全部 10010 项先持久化为 pending，planning 恢复不重读输入。
- [ ] 确认每批 200 项提交，进程终止后已提交项不丢失。
- [ ] 确认 resume 使用同一 run_id，并从最小未完成 source_order 继续。
- [ ] 确认相同路径指纹命中时不计算 SHA、不调用 Pillow/Reader/Enricher。
- [ ] 确认 0 字节图片产生 23 个 open problem，重复导入变为 held_problem。
- [ ] 确认有效但无节点信息的图片仍导入为 reader=unknown。
- [ ] 确认同一 workspace 的第二个写入 Run 被租约锁拒绝。
- [ ] 确认 info 日志在长导入期间至少每 200 项或 5 秒出现一次。
- [ ] 确认完成后只写一次 `workspace/imports/<run_id>.json`。
- [ ] 确认现有分类结果仍为 4626 个视图、25 个 unknown 视图。
- [ ] 确认原始图片未修改、未移动、未删除。
