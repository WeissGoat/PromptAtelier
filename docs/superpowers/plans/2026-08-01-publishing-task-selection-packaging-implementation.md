# 投稿任务、选择集合与打包实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ([ ]) syntax for tracking.

**Goal:** 在现有 publishing_workspace 工具中实现独立的投稿任务、人工选择集合、图片处理和 all/post/cover 打包链路。

**Architecture:** 复用现有 InputAdapterRegistry 和 SelectionSet 读取 NeeView .nvpls、普通目录和快捷方式目录。新增任务层把输入物化为任务目录中的图片快照；构建层只扫描当前选择目录，在 build 开始时生成不可变选择快照，再通过可注册 Operation 处理并输出目录及可选 ZIP。Catalog 只负责公共素材索引，任务创建和构建不依赖 Catalog 在线。

**Tech Stack:** Python 3.11、Pydantic 2、PyYAML、Pillow、argparse、zipfile、hashlib、tempfile、pathlib、pytest。

## Global Constraints

- refresh 和增量分类暂不纳入本阶段。
- 公共 workspace 与具体投稿任务分离；任务图片复制完成后，任务目录成为独立快照。
- selection/all、selection/post、selection/cover 只存放图片，不放内部 manifest。
- 导入历史写入 selection/history；人工维护的三个图片目录当前内容是构建事实来源。
- 每次 build 开始时生成不可变 selection_snapshot.json，构建期间只使用该快照，不再次读取 Catalog 或 selection 目录。
- candidates、all、post、cover 必须走同一个 InputAdapterRegistry 和 SelectionSet 协议。
- all、post、cover 都支持 .nvpls、普通目录和快捷方式目录。
- post 不强制是 all 的子集，cover 不强制属于 post；关系只产生 warning，不阻止构建。
- cover 不自动移动到 post 第一张。
- 初始物化文件名使用共享 OutputNamePolicy；人工重命名后 PackageBuilder 不再编号或覆盖文件名。
- strip_metadata 默认开启；mosaic 默认关闭，未配置插件时可以完成不打码构建。
- build 始终生成 output/all、output/post、output/cover 目录；ZIP 是可选附加输出。
- 对外目录和 ZIP 不包含 prompt、seed、本地路径、节点信息、Catalog 数据、history 或 manifest。
- 不修改公共 workspace 原图，不把任务构建逻辑放回 tags_machine_core。

## Current Code Map

- models.py 已有 SelectionSet、ImportedItem、AssetRecord、ViewEntry。
- inputs/base.py 已有 InputAdapter、InputContext、InputAdapterRegistry。
- inputs/directory.py、inputs/neev_playlist.py、inputs/shortcut.py 已支持目录、NeeView 播放列表和快捷方式输入。
- config.py 已有 WorkspacePaths，paths.tasks 是投稿任务根目录。
- service.py 和 cli.py 目前只负责公共 workspace 的导入、分类和视图导出。
- views/exporters.py 是分类视图 Exporter，不承担投稿图片包处理。

新增代码不能把任务状态写入 Catalog，也不能复用 Catalog 的分类视图作为投稿任务事实来源。

## File Map

### Create

- src/publishing_workspace/tasks/__init__.py
- src/publishing_workspace/tasks/models.py
- src/publishing_workspace/tasks/paths.py
- src/publishing_workspace/tasks/repository.py
- src/publishing_workspace/tasks/naming.py
- src/publishing_workspace/tasks/selection.py
- src/publishing_workspace/tasks/scanner.py
- src/publishing_workspace/tasks/service.py
- src/publishing_workspace/processing/__init__.py
- src/publishing_workspace/processing/models.py：运行时 Operation 和 ProcessingResult；任务配置中的 OperationConfig、ProcessingConfig 保留在 tasks/models.py，由两层共同使用。
- src/publishing_workspace/processing/operations.py
- src/publishing_workspace/processing/cache.py
- src/publishing_workspace/processing/pipeline.py
- src/publishing_workspace/packages/__init__.py
- src/publishing_workspace/packages/models.py
- src/publishing_workspace/packages/builder.py
- tests/test_task_models.py
- tests/test_task_selection.py
- tests/test_processing.py
- tests/test_package_builder.py
- tests/test_task_cli.py
- examples/task/publishing-task.yaml

所有路径均相对于 tools/publishing_workspace。

### Modify

- src/publishing_workspace/service.py：委托任务 API，保持已有 Catalog API。
- src/publishing_workspace/cli.py：增加 task create/import-selection/status/build。
- README.md：补充任务配置、人工筛选、构建和结果结构。
- examples/README.md：补充最小投稿任务示例。

---

## Task 1: 任务模型、路径和 Repository

**Files**

- Create: tasks/__init__.py
- Create: tasks/models.py
- Create: tasks/paths.py
- Create: tasks/repository.py
- Create: tests/test_task_models.py

**Interfaces**

- TaskPaths.from_workspace(paths: WorkspacePaths, task_id: str) -> TaskPaths
- TaskPaths.ensure_layout() -> None
- TaskRepository.create(paths: TaskPaths, title: str | None) -> TaskConfig
- TaskRepository.load(paths: TaskPaths) -> TaskConfig
- TaskRepository.save(paths: TaskPaths, config: TaskConfig) -> None
- TaskRepository.record_history(paths: TaskPaths, record: SelectionImportHistory) -> Path

### Step 1: failing tests

~~~python
def test_task_paths_create_selection_directories(tmp_path):
    paths = TaskPaths.from_workspace(
        WorkspacePaths.from_root(tmp_path / "publish"),
        "homura_foot",
    )
    paths.ensure_layout()
    assert paths.task_root == tmp_path / "publish" / "tasks" / "homura_foot"
    assert paths.history_dir.is_dir()
    assert set(paths.selection_dirs) == {"all", "post", "cover"}


def test_task_id_cannot_escape_tasks_root(tmp_path):
    with pytest.raises(ValueError, match="task_id"):
        TaskPaths.from_workspace(
            WorkspacePaths.from_root(tmp_path / "publish"),
            "../outside",
        )
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_models.py -q
~~~

Expected: FAIL because the task package does not exist.

### Step 2: implementation contract

Implement these Pydantic models in tasks/models.py:

~~~python
SelectionName = Literal["all", "post", "cover"]
ImportMode = Literal["replace", "append"]


class OperationConfig(BaseModel):
    enabled: bool = True
    version: str = "1"
    adapter: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ProcessingConfig(BaseModel):
    profile: str = "pixiv_default"
    operations: dict[str, OperationConfig] = Field(
        default_factory=lambda: {
            "strip_metadata": OperationConfig(enabled=True),
            "mosaic": OperationConfig(enabled=False),
        }
    )


class DirectoryOutputConfig(BaseModel):
    enabled: Literal[True] = True


class ZipOutputConfig(BaseModel):
    enabled: bool = False
    targets: list[SelectionName] = Field(
        default_factory=lambda: ["all", "post", "cover"]
    )


class PackageConfig(BaseModel):
    directories: DirectoryOutputConfig = Field(default_factory=DirectoryOutputConfig)
    zip: ZipOutputConfig = Field(default_factory=ZipOutputConfig)


class TaskConfig(BaseModel):
    version: Literal[1] = 1
    task_id: str
    title: str
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    packages: PackageConfig = Field(default_factory=PackageConfig)


class SelectionImportHistory(BaseModel):
    schema: Literal["publishing-workspace.selection-import/v1"]
    history_id: str
    selection: SelectionName
    mode: ImportMode
    source_type: str
    source_ref: str
    imported_at: str
    source_items: list[dict[str, Any]]
    materialized_files: list[str]
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_materialization(
        cls,
        *,
        history_id: str,
        selection: SelectionName,
        mode: ImportMode,
        source_type: str,
        source_ref: str,
        imported_at: str,
        source_items: list[dict[str, Any]],
        materialized_files: list[str],
        warnings: list[str],
    ) -> "SelectionImportHistory":
        return cls(
            schema="publishing-workspace.selection-import/v1",
            history_id=history_id,
            selection=selection,
            mode=mode,
            source_type=source_type,
            source_ref=source_ref,
            imported_at=imported_at,
            source_items=source_items,
            materialized_files=materialized_files,
            warnings=warnings,
        )


class MaterializeResult(BaseModel):
    materialized_files: list[str] = Field(default_factory=list)
    skipped_duplicates: int = 0
    warnings: list[str] = Field(default_factory=list)


class SelectionFile(BaseModel):
    selection: SelectionName
    filename: str
    relative_path: str
    absolute_path: str
    content_sha256: str
    asset_id: str | None = None


class SelectionSnapshot(BaseModel):
    schema: Literal["publishing-workspace.selection-snapshot/v1"]
    build_id: str
    created_at: str
    selections: dict[SelectionName, list[SelectionFile]]
~~~

DirectoryOutputConfig.enabled 只能为 true，保证第一版始终产生目录；ZipOutputConfig.enabled 默认 false，targets 默认 all、post、cover。

TaskPaths 只接受单个目录名，允许字母、数字、下划线和连字符，拒绝空值、路径分隔符、点号、绝对路径和路径穿越。路径对象必须暴露 task_root、task_yaml、selection_root、history_dir、selection_dirs、candidates_snapshot、candidates_playlist、builds_root。

TaskRepository 用同目录临时文件和 os.replace 原子写 YAML/JSON。create 重复 task_id 时直接报错，不覆盖已有任务。

### Step 3: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_models.py -q
~~~

Expected: PASS，覆盖默认配置、路径拒绝、目录布局、原子 task.yaml 和 history 写入。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/tasks tools/publishing_workspace/tests/test_task_models.py
git commit -m "feat(publishing): add task models and repositories"
~~~

---

## Task 2: 命名策略和选择集合物化

**Files**

- Create: tasks/naming.py
- Create: tasks/selection.py
- Modify: tasks/models.py
- Create: tests/test_task_selection.py

**Interfaces**

- OutputNamePolicy.make_name(index: int, source_name: str, used_names: set[str]) -> str
- SelectionMaterializer.materialize(selection: SelectionSet, target: Path, mode: ImportMode, image_extensions: set[str]) -> MaterializeResult
- SelectionSnapshotWriter.write_candidates(paths: TaskPaths, selection: SelectionSet) -> tuple[Path, Path]
- SelectionHistoryWriter.write(paths: TaskPaths, history: SelectionImportHistory) -> Path

### Step 1: failing business tests

~~~python
def test_materializer_preserves_input_order_and_does_not_write_manifest(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "10.png")
    _image(source / "2.png")
    selection = default_input_registry().load(
        source, input_type="directory", context=InputContext()
    )

    result = SelectionMaterializer().materialize(
        selection,
        tmp_path / "task/selection/all",
        mode="replace",
        image_extensions={".png"},
    )

    assert result.materialized_files == ["0001_2.png", "0002_10.png"]
    assert not (tmp_path / "task/selection/all/selection.json").exists()


def test_append_deduplicates_by_content_and_keeps_existing_mtime(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "task/selection/all"
    source.mkdir()
    target.mkdir(parents=True)
    original = _image(source / "original.png")
    existing = target / "0001_existing.png"
    shutil.copy2(original, existing)
    before = existing.stat().st_mtime_ns

    selection = default_input_registry().load(source, input_type="directory")
    result = SelectionMaterializer().materialize(
        selection, target, mode="append", image_extensions={".png"}
    )

    assert result.skipped_duplicates == 1
    assert existing.stat().st_mtime_ns == before
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_selection.py -q
~~~

Expected: FAIL because naming and materialization do not exist.

### Step 2: implement OutputNamePolicy

The exact algorithm is:

~~~python
def make_name(self, index: int, source_name: str, used_names: set[str]) -> str:
    suffix = Path(source_name).suffix.casefold()
    stem = _replace_windows_illegal_chars(Path(source_name).stem)
    stem = stem.strip(" .") or "image"
    stem = stem[: self.max_stem_length]
    candidate = f"{index:04d}_{stem}{suffix}"
    counter = 2
    while candidate.casefold() in {name.casefold() for name in used_names}:
        candidate = f"{index:04d}_{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(candidate)
    return candidate
~~~

替换 Windows 非法字符 <>:"/\\|?* 和控制字符；保留扩展名；按大小写不敏感处理重名；不覆盖已有文件。

### Step 3: implement SelectionMaterializer

固定流程：

1. unresolved、缺失或不支持扩展名的输入项不复制，转为 history warning。
2. 每个源文件计算 SHA-256；replace 在输入内按内容去重，append 与目标目录当前图片内容哈希比较。
3. replace 写临时目录，成功后替换目标目录中的图片；append 只复制新内容。
4. 使用 shutil.copy2，不修改公共原图。
5. 返回 materialized_files、skipped_duplicates、warnings，不创建 selection.json。
6. 目标目录只包含图片；history 不在其中。

SelectionSnapshotWriter 将 candidates SelectionSet 写到 selection/candidates.snapshot.json，并生成保留顺序的 candidates.nvpls。该播放列表引用任务内 selection/all 的绝对路径，不引用公共原图。history 文件名为 UTC 时间、集合名和 history_id 的组合，内容包含输入顺序、物化文件名、重复项和 warnings。

### Step 4: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_selection.py -q
~~~

Expected: PASS，覆盖 .nvpls 顺序、目录输入、replace/append、重复内容、非法文件名、history 和原图未修改。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/tasks tools/publishing_workspace/tests/test_task_selection.py
git commit -m "feat(publishing): materialize task selection sets"
~~~

---

## Task 3: 任务服务和固定 CLI

**Files**

- Create: tasks/service.py
- Modify: src/publishing_workspace/service.py
- Modify: src/publishing_workspace/cli.py
- Create: tests/test_task_cli.py

**Interfaces**

- TaskWorkflowService.create(root, task_id, title, candidates, input_type, recursive) -> TaskConfig
- TaskWorkflowService.import_selection(root, task_id, selection_name, source, input_type, recursive, mode) -> SelectionImportHistory
- TaskWorkflowService.status(root, task_id) -> dict[str, Any]
- PublishingService.create_task、import_task_selection、task_status 委托给 TaskWorkflowService。

### Step 1: failing CLI test

~~~python
def test_task_cli_create_then_status_reflects_manual_delete_and_rename(tmp_path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "01.png")
    _image(source / "02.png")

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main([
        "task", "create", str(root), "task-001",
        "--candidates", str(source), "--input-type", "directory",
    ]) == 0
    capsys.readouterr()

    all_dir = root / "tasks/task-001/selection/all"
    (all_dir / "0001_01.png").unlink()
    (all_dir / "0002_02.png").rename(all_dir / "0001_best.png")

    assert main(["task", "status", str(root), "task-001"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["selection_counts"] == {"all": 1, "post": 0, "cover": 0}
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_cli.py::test_task_cli_create_then_status_reflects_manual_delete_and_rename -q
~~~

Expected: FAIL because task commands do not exist.

### Step 2: add the command parser

Add a top-level task parser with fixed subcommands:

~~~text
task create ROOT TASK_ID [--title TITLE] [--candidates SOURCE] [--input-type TYPE] [--recursive]
task import-selection ROOT TASK_ID --set all|post|cover --source SOURCE [--mode replace|append] [--input-type TYPE] [--recursive]
task status ROOT TASK_ID
task build ROOT TASK_ID
~~~

TYPE accepts neev_playlist, directory and shortcut. Each task command accepts the existing --log-level option. Existing top-level commands and their output remain unchanged.

task create without candidates creates an empty task. With candidates it loads through InputAdapterRegistry, writes candidates snapshots/history, and materializes all. task import-selection uses exactly the same loader and materializer for all, post and cover.

### Step 3: implement TaskWorkflowService

~~~python
class TaskWorkflowService:
    def create(self, root, task_id, *, title=None, candidates=None,
               input_type=None, recursive=False) -> TaskConfig:
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        config = TaskRepository.create(task_paths, title=title)
        if candidates is not None:
            selection = self._load_selection(
                workspace_config, candidates, input_type=input_type,
                recursive=recursive,
            )
            self._materialize_candidates(
                task_paths, selection, workspace_config,
            )
        return config

    def import_selection(self, root, task_id, selection_name, source, *,
                         input_type=None, recursive=False, mode="replace"):
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        TaskRepository.load(task_paths)
        selection = self._load_selection(
            workspace_config, source, input_type=input_type,
            recursive=recursive,
        )
        result = SelectionMaterializer().materialize(
            selection,
            task_paths.selection_dirs[selection_name],
            mode=mode,
            image_extensions=set(workspace_config.image_extensions),
        )
        history = SelectionImportHistory.from_materialization(
            history_id=uuid4().hex,
            selection=selection_name,
            mode=mode,
            source_type=selection.source_type,
            source_ref=selection.source_ref,
            imported_at=utc_now_iso(),
            source_items=[item.model_dump(mode="json") for item in selection.items],
            materialized_files=result.materialized_files,
            warnings=result.warnings,
        )
        SelectionHistoryWriter().write(task_paths, history)
        return history
~~~

不调用 Catalog，不复制到 workspace/exports，只写 tasks/<task_id>。

### Step 4: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_cli.py -q
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_cli.py tools/publishing_workspace/tests/test_pipeline.py -q
~~~

Expected: 新任务测试和现有公共 workspace 测试全部 PASS。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/tasks/service.py tools/publishing_workspace/src/publishing_workspace/service.py tools/publishing_workspace/src/publishing_workspace/cli.py tools/publishing_workspace/tests/test_task_cli.py
git commit -m "feat(publishing): add task selection commands"
~~~

---

## Task 4: 当前选择扫描、构建快照和 warning

**Files**

- Create: tasks/scanner.py
- Create: packages/models.py
- Modify: tasks/models.py
- Create or modify: tests/test_package_builder.py

**Interfaces**

- CurrentSelectionScanner.scan(task_paths, image_extensions) -> dict[SelectionName, list[SelectionFile]]
- SelectionValidator.validate(selections) -> list[WarningRecord]
- BuildManifest：保存 build id、task id、处理 profile、集合数量、输出数量、处理统计、warnings/errors。

packages/models.py 必须定义这些稳定模型：

~~~python
class WarningRecord(BaseModel):
    code: str
    message: str
    selection: SelectionName | None = None
    filename: str | None = None


class BuildManifest(BaseModel):
    schema: Literal["publishing-workspace.build/v1"]
    build_id: str
    task_id: str
    status: Literal["success", "failed"]
    processing_profile: str
    selection: dict[SelectionName, int]
    outputs: dict[SelectionName, int]
    processing_result: dict[str, int]
    warnings: list[WarningRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
~~~

### Step 1: failing scanner and warning tests

~~~python
def test_scanner_uses_current_names_and_ignores_history(tmp_path):
    task_paths = _task_paths(tmp_path)
    _image(task_paths.selection_dirs["all"] / "10_best.png")
    _image(task_paths.selection_dirs["all"] / "2_best.png")
    (task_paths.history_dir / "old.json").write_text("{}", encoding="utf-8")

    selections = CurrentSelectionScanner().scan(task_paths, {".png"})

    assert [item.filename for item in selections["all"]] == [
        "2_best.png", "10_best.png"
    ]
    assert selections["post"] == []


def test_validator_warns_for_post_not_in_all(tmp_path):
    task_paths = _task_paths(tmp_path)
    _image(task_paths.selection_dirs["all"] / "all.png")
    _image(task_paths.selection_dirs["post"] / "different.png")

    selections = CurrentSelectionScanner().scan(task_paths, {".png"})
    warnings = SelectionValidator().validate(selections)

    assert any(item.code == "post_not_in_all" for item in warnings)
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_package_builder.py -q
~~~

Expected: FAIL because current-directory scanning does not exist.

### Step 2: implement current-directory semantics

CurrentSelectionScanner only inspects direct child files under all, post and cover. It ignores history, hidden files, directories and unsupported extensions; sorts using inputs.directory.natural_key; calculates SHA-256; and returns empty lists after TaskPaths.ensure_layout.

asset_id is optional and defaults to None. A missing asset_id never rejects a file. The scanner must not query Catalog.

SelectionSnapshot is serialized before processing. The builder passes the in-memory snapshot forward and never rescans selection directories during the same build.

### Step 3: implement warning-only validation

Compare content hashes and emit WarningRecord for:

~~~text
post_not_in_all
cover_not_in_post
duplicate_within_selection
~~~

Missing or unreadable images are build-blocking errors reported before the formal build directory is created. Relationship warnings never raise.

### Step 4: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_package_builder.py -q
~~~

Expected: PASS，确认人工删除、重命名、自然排序、history 隔离和非子集 warning。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/tasks/scanner.py tools/publishing_workspace/src/publishing_workspace/packages/models.py tools/publishing_workspace/tests/test_package_builder.py
git commit -m "feat(publishing): snapshot current task selections"
~~~

---

## Task 5: 可扩展图片 Operation 和处理缓存

**Files**

- Create: processing/__init__.py
- Create: processing/models.py
- Create: processing/operations.py
- Create: processing/cache.py
- Create: processing/pipeline.py
- Create: tests/test_processing.py

**Interfaces**

- ImageOperation.type: str
- ImageOperation.version: str
- ImageOperation.validate(options) -> None
- ImageOperation.process(input_path, output_path, options) -> None
- OperationRegistry.register(operation) -> None
- OperationRegistry.get(operation_type) -> ImageOperation
- ProcessingCache.key(input_sha256, profile, operations) -> str
- ImageProcessingPipeline.process(source, target, config) -> ProcessingResult

### Step 1: failing processing tests

~~~python
def test_strip_metadata_removes_png_text_and_preserves_dimensions(tmp_path):
    source = _image_with_text(
        tmp_path / "source.png",
        {"prompt": "secret", "seed": "42"},
    )
    output = tmp_path / "output.png"

    ImageProcessingPipeline().process(
        source, output, ProcessingConfig(profile="pixiv_default")
    )

    assert Image.open(output).size == Image.open(source).size
    assert read_png_text_chunks(output) == {}


def test_processing_cache_reuses_same_input_and_config(tmp_path):
    source = _image(tmp_path / "source.png")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    pipeline = ImageProcessingPipeline(cache_root=tmp_path / "cache")
    config = ProcessingConfig(profile="pixiv_default")

    first_result = pipeline.process(source, first, config)
    second_result = pipeline.process(source, second, config)

    assert first_result.cache_hit is False
    assert second_result.cache_hit is True
    assert first.read_bytes() == second.read_bytes()


def test_mosaic_without_adapter_fails_before_output(tmp_path):
    with pytest.raises(ValueError, match="mosaic.*adapter"):
        ImageProcessingPipeline().process(
            _image(tmp_path / "source.png"),
            tmp_path / "output.png",
            ProcessingConfig(
                operations={"mosaic": OperationConfig(enabled=True)}
            ),
        )
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_processing.py -q
~~~

Expected: FAIL because Operation registry and pipeline do not exist.

### Step 2: implement strip_metadata

StripMetadataOperation 用 Pillow 读取图片，写出时不传递 image.info、pnginfo 或 EXIF；保留尺寸、模式、格式和扩展名；不覆盖输入。源图片损坏时在 cache 发布前抛 ValueError。

处理结果先写临时文件，重新用 Pillow 验证，再原子移动到 cache。cache 失效或异常时不能留下可被后续命中的半成品。

### Step 3: implement registry, cache and mosaic boundary

默认 registry 只有：

~~~text
strip_metadata -> StripMetadataOperation(version="1")
mosaic -> MosaicOperation(version="1", adapter required)
~~~

MosaicOperation 通过注入的 MosaicAdapter 执行，不直接 import 旧项目。协议为：

~~~python
class MosaicAdapter(Protocol):
    name: str
    def process(self, source: Path, target: Path, options: dict[str, Any]) -> None:
        pass
~~~

mosaic.enabled 为 false 时跳过；为 true 且 adapter 缺失或未知时，在正式 build 产生前失败。

cache key 是 canonical JSON 的 SHA-256，字段包括 input_sha256、profile，以及每个启用 Operation 的 type、version、adapter 和排序后的 options。缓存位于 WorkspacePaths.cache/processing/<key>.<suffix>，all/post/cover 共享。

### Step 4: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_processing.py -q
~~~

Expected: PASS，验证清参数、缓存复用、插件缺失失败和源文件不变。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/processing tools/publishing_workspace/tests/test_processing.py
git commit -m "feat(publishing): add image processing operations"
~~~

---

## Task 6: PackageBuilder 原子构建目录和 ZIP

**Files**

- Create: packages/__init__.py
- Create: packages/builder.py
- Modify: tasks/service.py
- Modify: service.py
- Modify: tests/test_package_builder.py

**Interfaces**

- PackageBuilder.build(root, task_id) -> BuildResult
- BuildResult.build_id
- BuildResult.build_root
- BuildResult.manifest_path
- BuildResult.output_paths
- BuildResult.archive_paths

packages/models.py 同时定义：

~~~python
class BuildResult(BaseModel):
    build_id: str
    build_root: Path
    manifest_path: Path
    output_paths: dict[SelectionName, Path]
    archive_paths: dict[SelectionName, Path]
    selection: dict[SelectionName, int]
~~~

### Step 1: failing end-to-end build test

~~~python
def test_builder_creates_three_directories_and_optional_zip(tmp_path):
    root, task_paths = _create_task_with_images(tmp_path)
    _image_with_text(
        task_paths.selection_dirs["all"] / "0001_a.png",
        {"prompt": "private", "seed": "9"},
    )
    shutil.copy2(
        task_paths.selection_dirs["all"] / "0001_a.png",
        task_paths.selection_dirs["post"] / "manual_name.png",
    )
    _image(task_paths.selection_dirs["cover"] / "cover.png")
    TaskRepository.save(
        task_paths,
        TaskConfig(
            task_id="task-001", title="test",
            packages={"zip": {"enabled": True}},
        ),
    )

    result = PackageBuilder().build(root, "task-001")

    assert result.output_paths["all"].is_dir()
    assert result.output_paths["post"].is_dir()
    assert result.output_paths["cover"].is_dir()
    assert result.archive_paths["all"].suffix == ".zip"
    assert json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )["status"] == "success"
    assert (result.build_root / "selection_snapshot.json").is_file()
~~~

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_package_builder.py -q
~~~

Expected: FAIL because PackageBuilder does not exist.

### Step 2: implement exact build phases

1. Load TaskConfig and call TaskPaths.ensure_layout.
2. Generate unique build_id from UTC timestamp plus random suffix.
3. Create builds/.build_id.tmp/output/all, output/post and output/cover.
4. Scan current selection directories once and validate every image with Pillow.
5. Write selection_snapshot.json into the temporary build directory.
6. Validate relationship warnings and required operations.
7. Process each snapshot item with its current filename; do not call OutputNamePolicy again.
8. Write build_manifest.json with counts, cache statistics, warnings and errors.
9. Create configured ZIP targets only; each ZIP contains that set's processed image files and no manifest.
10. Atomically rename the temporary directory to builds/build_id after all output succeeds.

Failure deletes only the temporary directory, keeps previous successful builds, and leaves selection/public originals unchanged. Missing or unreadable image, unwritable output, unavailable required Operation and unhandled processing error block the build.

### Step 3: manifest and result contract

Manifest minimum:

~~~yaml
schema: publishing-workspace.build/v1
build_id: 20260801_223000_ab12
task_id: task-001
status: success
processing_profile: pixiv_default
selection:
  candidates: 0
  all: 1
  post: 1
  cover: 1
outputs:
  all: 1
  post: 1
  cover: 1
processing_result:
  cache_hit: 1
  processed: 2
  skipped_mosaic: 3
warnings: []
errors: []
~~~

selection_snapshot.json can include relative task paths and optional asset_id but never enters output or ZIP. CLI build output includes build_id, manifest_path, output_paths, archive_paths and selection counts.

### Step 4: verify and commit

Run:
~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_package_builder.py -q
~~~

Expected: PASS，验证三套目录始终生成、ZIP 可选、人工文件名保留、跨集合共享处理缓存、失败不污染正式 build。

~~~bash
git add tools/publishing_workspace/src/publishing_workspace/packages tools/publishing_workspace/src/publishing_workspace/tasks/service.py tools/publishing_workspace/src/publishing_workspace/service.py tools/publishing_workspace/tests/test_package_builder.py
git commit -m "feat(publishing): build task packages atomically"
~~~

---

## Task 7: README、示例和真实业务验收

**Files**

- Modify: README.md
- Modify: examples/README.md
- Create: examples/task/publishing-task.yaml
- Modify: tests/test_task_cli.py

### Step 1: canonical task config

examples/task/publishing-task.yaml:

~~~yaml
version: 1
task_id: 20260801_homura_foot
title: homura foot

processing:
  profile: pixiv_default
  operations:
    strip_metadata:
      enabled: true
    mosaic:
      enabled: false

packages:
  directories:
    enabled: true
  zip:
    enabled: true
    targets:
      - all
      - post
      - cover
~~~

task create 自动生成同一结构；示例只用于查看和编辑，不引入第二套配置协议。

### Step 2: document commands

README 必须包含以下工作流：

~~~powershell
uv run publishing-workspace init G:\ai_publish
uv run publishing-workspace task create G:\ai_publish 20260801_homura_foot --candidates E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot --set post --source E:\NeeView41.3\Profile\Playlists\post.nvpls --mode replace
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot --set cover --source E:\NeeView41.3\Profile\Playlists\cover.nvpls --mode replace
uv run publishing-workspace task status G:\ai_publish 20260801_homura_foot
uv run publishing-workspace task build G:\ai_publish 20260801_homura_foot
~~~

文档解释 workspace 是公共素材池，tasks/<task_id> 是独立任务；candidates 自动进入 all；history 不是构建输入；用户可以直接删除、改名和排序；post/cover 非子集只 warning；build 输出在 tasks/<task_id>/builds/<build_id>/output 和 archives；对外包不含 manifest 和 PNG 内部参数。

### Step 3: real business acceptance

~~~python
def test_real_business_flow_uses_current_directory_state(tmp_path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "source"
    source.mkdir()
    first = _image_with_text(source / "first.png", {"prompt": "private"})
    second = _image_with_text(source / "second.png", {"seed": "42"})
    playlist = _write_playlist(tmp_path / "candidates.nvpls", [second, first])

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main([
        "task", "create", str(root), "task-001",
        "--candidates", str(playlist),
    ]) == 0
    capsys.readouterr()

    all_dir = root / "tasks/task-001/selection/all"
    (all_dir / "0001_second.png").rename(all_dir / "0001_cover.png")
    (all_dir / "0002_first.png").unlink()

    assert main(["task", "build", str(root), "task-001"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["selection"]["all"] == 1
    output = Path(result["output_paths"]["all"])
    assert [path.name for path in output.glob("*.png")] == ["0001_cover.png"]
    assert read_png_text_chunks(output / "0001_cover.png") == {}
~~~

### Step 4: complete verification

Run from F:\my_project\new\tags_machine\refactor:

~~~powershell
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests/test_task_models.py tools/publishing_workspace/tests/test_task_selection.py tools/publishing_workspace/tests/test_task_cli.py tools/publishing_workspace/tests/test_processing.py tools/publishing_workspace/tests/test_package_builder.py -q
uv run --project tools/publishing_workspace pytest tools/publishing_workspace/tests -q
uv run --project tools/publishing_workspace publishing-workspace --help
~~~

Expected: all tests PASS; help contains task; existing Catalog/Reader/import/export tests remain PASS.

真实 NeeView 业务验收：

~~~powershell
uv run --project tools/publishing_workspace publishing-workspace task create G:\ai_publish acceptance_20260801 --candidates E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls --log-level info
uv run --project tools/publishing_workspace publishing-workspace task status G:\ai_publish acceptance_20260801
uv run --project tools/publishing_workspace publishing-workspace task build G:\ai_publish acceptance_20260801
~~~

检查：selection/all 数量和实际物化结果一致；history 有导入来源；手工删除/改名后 selection_snapshot 和目录一致；三个 output 目录始终存在；PNG 可打开且没有 prompt、negative_prompt、seed；ZIP 不含内部记录；失败不新增正式 build。

### Step 5: commit

~~~bash
git diff --check
git add tools/publishing_workspace/README.md tools/publishing_workspace/examples/README.md tools/publishing_workspace/examples/task tools/publishing_workspace/tests/test_task_cli.py
git commit -m "docs(publishing): document task packaging workflow"
~~~

## Spec Coverage Review

| Spec requirement | Plan coverage |
| --- | --- |
| 公共 workspace 与任务分离 | Task 1、Task 3、Task 7 |
| candidates/all/post/cover 统一输入 | Task 2、Task 3 |
| .nvpls、目录、快捷方式 | 现有 InputAdapter，Task 3、Task 7 |
| candidates 自动进入 all | Task 3 |
| history 与图片目录分离 | Task 1、Task 2、Task 3、Task 7 |
| 人工删除/重命名/排序是事实来源 | Task 4、Task 6、Task 7 |
| 构建选择快照 | Task 4、Task 6 |
| 通用文件名策略 | Task 2 |
| strip_metadata 默认开启 | Task 1、Task 5、Task 6 |
| mosaic 可选插件 | Task 1、Task 5、Task 6 |
| warning-only 集合关系 | Task 4、Task 6 |
| 原子 build 和历史 build 保留 | Task 6 |
| 目录始终输出、ZIP 可选 | Task 1、Task 6、Task 7 |
| CLI 固定入口 | Task 3、Task 7 |
| 真实业务验收 | Task 7 |

## Plan Self-Review

- 没有未完成标记或未定义的实现分支。
- 所有新模块都有明确路径和职责；任务层、处理层、打包层不依赖 Catalog。
- SelectionSnapshot、SelectionFile、ProcessingConfig、OperationConfig 在前置任务定义，后续任务使用同名接口。
- 目录当前内容是事实来源；没有将 selection.json 作为持续构建输入。
- 目录输出固定启用，ZIP 可选。
- 验收优先通过公开 CLI、真实图片和真实 .nvpls 验证，不把单元测试作为唯一验收依据。
