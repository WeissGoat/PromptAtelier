# Publishing Workspace Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `tags_machine_core.publishing` 中实现公共素材工作区的导入、图片节点读取、Catalog 持久化、分类视图构建和增量导出，并提供可直接使用的 `publish init/import/classify/export` CLI。

**Architecture:** Publishing 是独立业务域，不进入 Composer、Renderer、Batch 或生图 Client。输入适配器统一产生 `SelectionSet`，图片节点 Reader Registry 统一产生 `ImageNodeInfo`，Catalog 保存业务事实，分类器只产生 `ExportPlan`，Exporter Registry 负责外部视图格式。

**Tech Stack:** Python 3.11、Pydantic 2、Pillow、PyYAML、SQLite、pytest、Windows PowerShell/COM（仅可选 `.lnk` 导出）。

**Implementation Status (2026-07-27):** 第一阶段已完成。实际交付包含公共 Catalog 默认聚合导出、局部 import 隔离导出，以及通过 `category_view_manifest.json` 补全新版图片缺失的 `action_group`；这些是实现期业务验收后对原计划的必要修正。

## Global Constraints

- 所有新增注释和用户可见错误信息使用中文。
- 不修改 AgentComposer、ScriptComposer、PromptPolicyPipeline、Renderer、Batch 和生图 Client 行为。
- 不复制、移动、重命名或删除原始图片。
- 新版 PNG 元数据优先；损坏时允许回退旧字段，但必须记录 warning。
- 第一阶段默认自动导出 `.nvpls`；`.lnk` 为 Windows 可选能力。
- 业务验收优先使用真实 NeeView 播放列表和真实新旧图片。
- 只提交 Publishing 相关文件，禁止 `git add -A`。

---

## File Map

```text
src/tags_machine_core/publishing/
  __init__.py                 # 对外公开模型和服务
  cli.py                      # publish 子命令入口
  config.py                   # workspace.yaml 模型、读写与路径
  models.py                   # SelectionSet、AssetRecord、ImageNodeInfo
  service.py                  # init/import/classify/export 应用编排
  catalog/
    __init__.py
    schema.py                 # SQLite DDL 与迁移版本
    repository.py             # Catalog 事务和查询
  inputs/
    __init__.py
    base.py                   # InputAdapter 协议和 Registry
    neev_playlist.py          # .nvpls 输入
    directory.py              # 图片目录输入
    shortcut.py               # .lnk 解析
  metadata/
    __init__.py
    registry.py               # Reader 选择与 fallback
    readers.py                # Core/Legacy Reader
  views/
    __init__.py
    builder.py                # AssetRecord -> ExportPlan
    coordinator.py            # 多 Exporter 调度与增量状态
    exporters.py              # .nvpls 和可选 .lnk Exporter
tests/publishing/             # Publishing 单元与集成测试
docs/publishing_readme.md     # 中文使用说明和结果结构
```

### Task 1: 领域模型和工作区初始化

**Files:**
- Create: `src/tags_machine_core/publishing/__init__.py`
- Create: `src/tags_machine_core/publishing/models.py`
- Create: `src/tags_machine_core/publishing/config.py`
- Create: `tests/publishing/test_workspace.py`

**Interfaces:**
- Produces: `PublishingWorkspaceConfig`, `WorkspacePaths`, `init_workspace(root)`, `load_workspace(root)`。
- Produces: `ImportedItem`, `SelectionSet`, `ImageNodeRef`, `ImageNodeInfo`, `AssetRecord`, `ViewItem`, `ViewEntry`, `ExportPlan`。

- [ ] **Step 1: 定义 Pydantic 模型及其字段约束**

  `SelectionSet.items` 保留来源顺序；`ImageNodeRef.role` 使用字符串而非枚举；所有路径在模型内保存绝对字符串。

- [ ] **Step 2: 实现工作区初始化**

  `init_workspace(root)` 原子写入 `workspace/workspace.yaml`，创建 `imports/exports/cache/state` 和 `tasks`；重复执行不覆盖用户配置。

- [ ] **Step 3: 验证目录和配置往返**

  Run: `uv run pytest tests/publishing/test_workspace.py -q`
  Expected: 工作区首次创建、重复初始化和无效配置测试全部通过。

- [ ] **Step 4: Commit**

  `git commit -m "feat(publishing): initialize shared workspace"`

### Task 2: 统一输入适配器

**Files:**
- Create: `src/tags_machine_core/publishing/inputs/__init__.py`
- Create: `src/tags_machine_core/publishing/inputs/base.py`
- Create: `src/tags_machine_core/publishing/inputs/neev_playlist.py`
- Create: `src/tags_machine_core/publishing/inputs/directory.py`
- Create: `src/tags_machine_core/publishing/inputs/shortcut.py`
- Create: `tests/publishing/test_inputs.py`

**Interfaces:**
- Consumes: `ImportedItem`, `SelectionSet`。
- Produces: `InputAdapter.load(source, context) -> SelectionSet` 和 `InputAdapterRegistry.load(...)`。

- [ ] **Step 1: 实现 Registry 与输入上下文**

  显式 `input_type` 优先；未指定时按 `.nvpls`、目录和 `.lnk` 探测。

- [ ] **Step 2: 实现 NeeView 和目录输入**

  `.nvpls` 使用 `utf-8-sig` 严格 JSON 解析，校验 `Format` 与 `Items[].Path`；目录支持递归、图片扩展名过滤和 natural sort。

- [ ] **Step 3: 实现 Windows 快捷方式解析**

  Windows 使用 PowerShell COM 解析 `.lnk`；非 Windows 或损坏链接返回明确错误/警告，不静默把链接本身当图片。

- [ ] **Step 4: 用真实 NeeView 文件验证输入顺序**

  Run: `uv run python -m tags_machine_core publish import <workspace> E:/NeeView41.3/Profile/Playlists/readypost.nvpls --input-type neev_playlist`
  Expected: 快照条目数和原播放列表一致，顺序一致，缺失文件记录为 warning。

- [ ] **Step 5: Commit**

  `git commit -m "feat(publishing): add selection input adapters"`

### Task 3: 新旧图片节点 Reader

**Files:**
- Create: `src/tags_machine_core/publishing/metadata/__init__.py`
- Create: `src/tags_machine_core/publishing/metadata/readers.py`
- Create: `src/tags_machine_core/publishing/metadata/registry.py`
- Create: `tests/publishing/test_metadata_readers.py`

**Interfaces:**
- Consumes: Pillow `image.info`。
- Produces: `ImageNodeReader.read(image_path, metadata) -> ImageNodeInfo`。

- [ ] **Step 1: 实现 Core Reader**

  读取 `tags_machine_core` JSON 的 `schema/nodes/source_nodes`，保留重复 role 和节点 index；只接受 `tags-machine-core.png-info/v1`。

- [ ] **Step 2: 实现 Legacy Reader**

  读取顶层 `artist/artist_path/character/action/topic/background`，兼容字符串、JSON 字符串和数组，`topic` 映射为 `action_group`。

- [ ] **Step 3: 实现 Registry fallback**

  合法新版优先；新版损坏且存在旧字段时回退 Legacy 并添加 warning；两者均不支持时返回 `format=unknown`。

- [ ] **Step 4: 用真实新旧 PNG 验证节点**

  从现有生成目录各选择至少一张 core 图和 legacy 图，输出 Reader、角色、动作组、动作和 warnings，与 PNG 参数人工核对。

- [ ] **Step 5: Commit**

  `git commit -m "feat(publishing): read core and legacy image nodes"`

### Task 4: SQLite Catalog 与导入服务

**Files:**
- Create: `src/tags_machine_core/publishing/catalog/__init__.py`
- Create: `src/tags_machine_core/publishing/catalog/schema.py`
- Create: `src/tags_machine_core/publishing/catalog/repository.py`
- Create: `src/tags_machine_core/publishing/service.py`
- Create: `tests/publishing/test_catalog.py`
- Create: `tests/publishing/test_import_service.py`

**Interfaces:**
- Consumes: `SelectionSet`, `ImageNodeReaderRegistry`。
- Produces: `CatalogRepository.import_selection(selection) -> ImportResult`。
- Produces: assets、asset_paths、asset_nodes、imports、import_items、export_states 表。

- [ ] **Step 1: 建立 schema v1 和事务边界**

  使用外键、唯一约束和 WAL；导入批次必须整批事务提交，异常时回滚。

- [ ] **Step 2: 实现图片指纹和内容去重**

  先按绝对路径、size、mtime_ns 复用 sha256；状态变化时重新计算；相同 sha256 合并为一个 asset 并保留路径记录。

- [ ] **Step 3: 实现导入快照**

  保存 `workspace/imports/<import_id>.json`，包含来源、顺序、asset_id、warning 和失败条目；Catalog 同步保存来源关系。

- [ ] **Step 4: 验证重复导入和跨来源复用**

  Run: `uv run pytest tests/publishing/test_catalog.py tests/publishing/test_import_service.py -q`
  Expected: 同图不同路径复用 asset、重复导入不重复节点、顺序保留。

- [ ] **Step 5: Commit**

  `git commit -m "feat(publishing): persist imported image catalog"`

### Task 5: 分类视图和增量 Exporter

**Files:**
- Create: `src/tags_machine_core/publishing/views/__init__.py`
- Create: `src/tags_machine_core/publishing/views/builder.py`
- Create: `src/tags_machine_core/publishing/views/exporters.py`
- Create: `src/tags_machine_core/publishing/views/coordinator.py`
- Create: `tests/publishing/test_views.py`
- Create: `tests/publishing/test_exporters.py`

**Interfaces:**
- Consumes: Catalog asset 查询、`hierarchy: list[str]`。
- Produces: `ClassificationViewBuilder.build(...) -> ExportPlan`。
- Produces: `ViewExportCoordinator.export(plan, exporters) -> ExportSummary`。

- [ ] **Step 1: 实现笛卡尔分类展开**

  默认层级 `artist/character/action_group/action`；多角色产生多个叶子视图；缺失维度按配置写入 `unknown` 或跳过。

- [ ] **Step 2: 实现 NeeView Exporter**

  每个非空叶子写一个 `NeeView.Playlist/2.0.0` JSON，成员按导入顺序和 natural filename 稳定排序。

- [ ] **Step 3: 实现可选 WindowsShortcutExporter**

  文件名采用稳定序号和原文件名，创建记录写入 Exporter 状态；只清理由自身上一轮状态记录且当前失效的 `.lnk`。

- [ ] **Step 4: 实现增量协调器**

  对 view 路径、成员、顺序、Exporter 配置和版本计算哈希；未变化视图跳过写入；状态原子落盘。

- [ ] **Step 5: 验证多角色、增量跳过和失效清理**

  Run: `uv run pytest tests/publishing/test_views.py tests/publishing/test_exporters.py -q`
  Expected: 多角色视图数量正确，第二次导出全部 skipped，移除成员后仅更新相关视图。

- [ ] **Step 6: Commit**

  `git commit -m "feat(publishing): build and export classification views"`

### Task 6: CLI 与中文使用文档

**Files:**
- Create: `src/tags_machine_core/publishing/cli.py`
- Modify: `src/tags_machine_core/cli.py`
- Create: `tests/publishing/test_cli.py`
- Create: `docs/publishing_readme.md`

**Interfaces:**
- Produces: `publish init ROOT`。
- Produces: `publish import ROOT SOURCE [--input-type ...] [--recursive] [--strict]`。
- Produces: `publish classify ROOT [--import-id ID] [--hierarchy ...]`。
- Produces: `publish export ROOT [--import-id ID] [--exporter neev]`。

- [ ] **Step 1: 注册 publish 命令组**

  CLI 输出 JSON 摘要，错误返回非零退出码；日志沿用项目现有 `configure_logging`。

- [ ] **Step 2: 连接应用服务**

  `classify` 把 ExportPlan 保存到 workspace state，`export` 默认读取最近计划；同时支持一次性 `publish export --import-id` 构建后导出。

- [ ] **Step 3: 编写用户文档**

  说明 workspace 结构、输入类型、Reader 选择、分类层级、导出器配置、命令示例、结果 JSON 和常见错误。

- [ ] **Step 4: 验证 CLI 帮助和错误码**

  Run: `uv run pytest tests/publishing/test_cli.py -q`
  Expected: 四个命令、默认配置、无效路径、严格模式均通过。

- [ ] **Step 5: Commit**

  `git commit -m "feat(publishing): expose workspace CLI"`

### Task 7: 真实业务验收

**Files:**
- Create: `docs/acceptance/publishing-workspace-phase-1.md`
- Create: `examples/publishing/workspace.example.yaml`

**Interfaces:**
- Consumes: 真实 `.nvpls`、真实 core PNG、真实 legacy PNG。
- Produces: 可打开的分类 `.nvpls` 树、导入快照、Catalog、验收报告。

- [ ] **Step 1: 导入真实 NeeView 播放列表**

  使用 `E:/NeeView41.3/Profile/Playlists` 下可解析且路径可访问的列表；记录原条目数、成功资产数、缺失数和 warnings。

- [ ] **Step 2: 补充真实新旧图片样本**

  从现有图片目录导入至少一张新版 core 图和一张旧版图，确认两个 Reader 实际命中。

- [ ] **Step 3: 构建并导出完整分类视图**

  打开至少两个生成的 `.nvpls`，确认路径有效、顺序正确、多角色图片按设计进入多个视图。

- [ ] **Step 4: 验证增量行为**

  连续执行第二次 export，报告应显示 unchanged/skipped；不得改写未变化 `.nvpls` 的 mtime。

- [ ] **Step 5: 运行回归门禁**

  Run: `uv run pytest tests -q`
  Expected: 现有 574 项及新增 Publishing 测试全部通过。

- [ ] **Step 6: Commit**

  `git commit -m "docs(publishing): record phase one acceptance"`
