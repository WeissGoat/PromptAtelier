# Publishing Workspace Mosaic Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前本地修改版 `anr_plugin_auto_mosaics` 集成到 `publishing_workspace`，让投稿任务可以通过配置执行真实的 YOLO 或 YOLO+SAM 自动打码，同时运行时完全不依赖 `F:\ThreeState`。

**Architecture:** 保留现有 `ImageProcessingPipeline -> OperationRegistry -> MosaicOperation` 处理边界。新增 `integrations/anr_mosaic` 作为插件适配层：模型管理负责路径、下载、复制和 SHA-256 校验；插件核心负责检测和打码；adapter 负责将任务 options 转换成插件调用。`PackageBuilder` 根据 workspace 配置创建 adapter registry，普通任务在未启用 mosaic 时不导入重依赖。

**Tech Stack:** Python 3.11, Pydantic 2, PyYAML, Pillow, OpenCV, NumPy, SciPy, PyTorch, Ultralytics, Segment Anything, pytest, uv。

## Global Constraints

- 运行时不得读取或访问 `F:\ThreeState`；旧目录只能通过安装命令的 `--source` 参数作为一次性迁移输入。
- 模型文件放在 `tools/publishing_workspace/models/anr_plugin_auto_mosaics` 或 workspace 配置指定目录，`.pt` 和 `.pth` 不提交 Git。
- mosaic 依赖放入可选 `mosaic` extra，普通 `uv sync` 不安装 PyTorch、Ultralytics 和 Segment Anything。
- 必须保留 GPLv3 上游 LICENSE，并新增 NOTICE 记录上游地址、迁移日期和本地修改。
- 继续复用现有 `ProcessingCache`、`ImageProcessingPipeline`、`OperationRegistry` 和原子 build 目录逻辑。
- 模型缺失、依赖缺失、校验失败或打码失败时，正式 build 必须失败，不产生正式 build 目录。
- 新增代码注释使用中文；task options 使用稳定英文枚举，不暴露插件内部中文标签。

---

### Task 1: Workspace Mosaic Configuration and Optional Dependencies

**Files:**
- Modify: `tools/publishing_workspace/pyproject.toml`
- Modify: `tools/publishing_workspace/src/publishing_workspace/config.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/config.py` (`WorkspacePaths`)
- Modify: `.gitignore` or `tools/publishing_workspace/.gitignore`
- Create: `tools/publishing_workspace/models/anr_plugin_auto_mosaics/.gitkeep`
- Create: `tools/publishing_workspace/assets/anr_plugin_auto_mosaics/emoji/.gitkeep`
- Create: `tools/publishing_workspace/third_party/anr_plugin_auto_mosaics/NOTICE.md`
- Test: `tools/publishing_workspace/tests/test_mosaic_config.py`

**Interfaces:**
- `PublishingWorkspaceConfig.integrations.mosaic` exposes provider, model root and model manifest.
- `MosaicIntegrationConfig.model_root` is optional; null resolves to the repository-local model directory.
- Model entries expose `filename`, `url`, and lowercase `sha256`.

- [ ] **Step 1: Write configuration tests** for default manifest, explicit relative model root, and unknown integration fields being rejected or ignored according to existing Pydantic policy.
- [ ] **Step 2: Run the focused tests** with `uv run --directory tools/publishing_workspace pytest tests/test_mosaic_config.py -q` and confirm they fail because the config models do not exist.
- [ ] **Step 3: Add the `mosaic` optional dependency group**, the integration Pydantic models, and a `WorkspacePaths.mosaic_models` property that resolves the repository-local default.
- [ ] **Step 4: Add ignored model directories and GPLv3 NOTICE metadata** without adding model binaries.
- [ ] **Step 5: Run the focused tests** and verify defaults serialize into `workspace.yaml` without changing existing workspace schema behavior.
- [ ] **Step 6: Commit** with `feat(publishing): add mosaic workspace configuration`.

### Task 2: Model Manifest, Status, Install, and Hash Verification

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/constants.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/model_manager.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/cli.py`
- Test: `tools/publishing_workspace/tests/test_mosaic_model_manager.py`
- Test: `tools/publishing_workspace/tests/test_mosaic_cli.py`

**Interfaces:**
- `MosaicModelManager(root, config)` provides `status() -> list[ModelStatus]` and `install(source: Path | None = None) -> list[ModelStatus]`.
- `mosaic status <root>` prints model target, existence, actual hash, expected hash, and `ready|missing|checksum_mismatch`.
- `mosaic install <root> [--source <models-directory>]` copies or downloads to temporary files, verifies SHA-256, and atomically replaces only valid targets.

- [ ] **Step 1: Write tests** for local source copy, correct hash status, missing model status, checksum mismatch, and failed copy leaving the existing valid file untouched.
- [ ] **Step 2: Run the focused model tests** and confirm failure on missing manager/CLI.
- [ ] **Step 3: Implement constants and model manifest resolution** using config values and repository-local defaults; never import or reference `F:\ThreeState`.
- [ ] **Step 4: Implement streaming SHA-256, source filename resolution, URL download, temporary file cleanup, and atomic replacement.
- [ ] **Step 5: Add `mosaic status` and `mosaic install` parser branches and JSON output.
- [ ] **Step 6: Run focused tests** and verify `uv run publishing-workspace mosaic status <temporary-root>` works without mosaic Python dependencies.
- [ ] **Step 7: Commit** with `feat(publishing): add mosaic model management`.

### Task 3: Migrate the Plugin Core Without UI or Global State

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/detector.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/sam_detector.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/mosaics.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/settings.py`
- Copy/adapt: `tools/publishing_workspace/third_party/anr_plugin_auto_mosaics/LICENSE`
- Test: `tools/publishing_workspace/tests/test_mosaic_core.py`

**Interfaces:**
- `Detector` implementations expose a lazy `detect(image) -> list[Detection]` contract.
- `MosaicProcessor` receives explicit detector, method, output path, temporary directory, and options; it never reads `config.json`, current working directory, or plugin UI state.
- Core imports for torch, ultralytics, cv2, scipy, and segment-anything occur lazily so normal workspace commands remain usable.

- [ ] **Step 1: Copy the current local plugin source into focused core modules**, preserving the local `process_mosaic` behavior and supported methods `pixel`, `blur`, `line`, `solid`, and `emoji`.
- [ ] **Step 2: Remove Gradio, `main()`, `save_config()`, loguru, global config loading, fixed `./outputs` paths, and metadata restoration.
- [ ] **Step 3: Make model paths and emoji paths explicit constructor parameters**, and load YOLO/SAM only on first use.
- [ ] **Step 4: Add focused pure-image tests** for method validation, output dimensions, temporary path isolation, and missing optional dependency errors using a fake detector; do not require torch for these tests.
- [ ] **Step 5: Run the focused core tests** and verify normal imports succeed when torch is unavailable.
- [ ] **Step 6: Commit** with `feat(publishing): migrate automatic mosaic core`.

### Task 4: Implement the Publishing Workspace Adapter and Registry Wiring

**Files:**
- Create: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/adapter.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/integrations/anr_mosaic/__init__.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/processing/operations.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/processing/pipeline.py` only if registry injection needs a narrow helper
- Modify: `tools/publishing_workspace/src/publishing_workspace/packages/builder.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/processing/models.py` only if the protocol needs a documented typed result
- Test: `tools/publishing_workspace/tests/test_mosaic_adapter.py`
- Test: `tools/publishing_workspace/tests/test_package_builder.py`

**Interfaces:**
- `AnrAutoMosaicsAdapter.name == "anr_plugin_auto_mosaics"`.
- `AnrAutoMosaicsAdapter.process(source: Path, target: Path, options: dict[str, Any]) -> None` validates models and options, runs the processor, and writes exactly `target`.
- Accepted options are `detector: yolo|yolo_sam`, `method: pixel|blur|line|solid|emoji`, `parts: list[penis|pussy|female_nipple|anus]`, plus method-specific numeric/color settings.
- `PackageBuilder` creates the adapter registry from `PublishingWorkspaceConfig.integrations.mosaic`; callers that inject a custom pipeline remain unchanged.

- [ ] **Step 1: Write adapter tests** for enum normalization, legacy part mapping, unsupported `anus` warning/ignore behavior, missing models, and output path creation using a fake processor.
- [ ] **Step 2: Run focused adapter tests** and confirm failure before implementation.
- [ ] **Step 3: Implement adapter validation, lazy processor cache, model status checks, temporary workspace creation, and error propagation.
- [ ] **Step 4: Wire `PackageBuilder` to pass `default_operation_registry({"anr_plugin_auto_mosaics": adapter})` while keeping explicit pipeline injection intact.
- [ ] **Step 5: Bump `MosaicOperation.version` to `"2"` so old processing cache entries cannot bypass the new implementation.
- [ ] **Step 6: Run processing and package regression tests** and verify mosaic-disabled builds do not import heavy dependencies.
- [ ] **Step 7: Commit** with `feat(publishing): connect mosaic adapter to package builds`.

### Task 5: Documentation, Examples, and Migration Commands

**Files:**
- Modify: `tools/publishing_workspace/README.md` or create it if absent
- Create: `tools/publishing_workspace/examples/workspace.yaml`
- Create: `tools/publishing_workspace/examples/tasks/mosaic-task.yaml`
- Modify: `docs/superpowers/specs/2026-08-02-publishing-mosaic-integration-design.md` only for implementation status links

- [ ] **Step 1: Document installation, `mosaic status`, `mosaic install`, model locations, supported task options, and the no-`F:\ThreeState` runtime guarantee.
- [ ] **Step 2: Add a minimal workspace and task example with `strip_metadata -> mosaic` ordering.
- [ ] **Step 3: Run CLI help and example parsing commands** and confirm the examples do not require model binaries.
- [ ] **Step 4: Commit** with `docs(publishing): document mosaic integration`.

### Task 6: Real Model Installation and Business Acceptance

**Files:**
- Runtime data only: `tools/publishing_workspace/models/anr_plugin_auto_mosaics/yolo/censor.pt`
- Runtime data only: `tools/publishing_workspace/models/anr_plugin_auto_mosaics/sams/sam_vit_b_01ec64.pth`
- Test artifacts only under an ignored temporary/output directory.

- [ ] **Step 1: Install the optional dependencies** with `uv sync --extra mosaic`; if the environment needs a specific PyTorch wheel, install that wheel using the documented PyTorch command before running the adapter.
- [ ] **Step 2: Copy the current local model files** with `uv run publishing-workspace mosaic install <workspace> --source F:\ThreeState\anr_plugin_auto_mosaics\models` and verify both hashes.
- [ ] **Step 3: Run one real YOLO+SAM task** on a representative image with `method: pixel`, checking that the output exists, dimensions are unchanged, the input is unchanged, and the sensitive region is visibly covered.
- [ ] **Step 4: Run the same task twice** and verify the second build reports a processing cache hit without re-running detection.
- [ ] **Step 5: Run a missing-model or invalid-option case** and verify no formal build directory is created.
- [ ] **Step 6: Record exact commands, output paths, model status, and acceptance observations in the final implementation summary.

## Self-Review Checklist

- [ ] Every design section is covered by Tasks 1-6: configuration, model lifecycle, plugin migration, adapter contract, registry wiring, cache version, docs, licensing, and real output validation.
- [ ] No runtime module references `F:\ThreeState`, `config.json`, Gradio, loguru, or the plugin working directory.
- [ ] Normal workspace tests do not import optional mosaic dependencies.
- [ ] Adapter and model manager signatures match the existing `MosaicAdapter` and `PackageBuilder` boundaries.
- [ ] `git diff --check` is clean for all files changed by this plan.
