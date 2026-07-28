# Publishing Workspace Standalone Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Core 内的 Publishing Workspace 完整迁移到 `tools/publishing_workspace`，形成零 `tags_machine_core` 运行时依赖的独立 Python 项目，并初始化可直接使用的示例工作区。

**Architecture:** 新项目保留现有 Input Adapter、Reader Registry、Catalog、Enricher、Classification 和 Exporter 边界，只把日志与 PNG 文本读取替换为项目内部模块。迁移完成后删除 Core 包和 CLI 注册，Core 与 Publishing 仅通过 PNG 元数据协议通信。

**Tech Stack:** Python 3.11、uv、Pydantic 2、Pillow、PyYAML、SQLite、pytest、Windows PowerShell COM。

## Global Constraints

- 直接在 `refactor/main` 实施，不创建新分支。
- 不提交现有工作区中与 Publishing 无关的修改。
- 独立项目源码不得 import `tags_machine_core`。
- 保留 `tags_machine_core` PNG key 和 `tags-machine-core.png-info/v1` 输入协议。
- 删除 `tags_machine_core publish` 入口，不保留兼容转发。
- 示例 `catalog.sqlite*` 和运行产物不进入 Git。
- 注释和用户可见错误继续使用中文。
- 验收优先执行真实 NeeView、真实旧图和当前 Core PNG 业务链路。

---

### Task 1: 建立独立项目骨架和基础设施

**Files:**
- Create: `tools/publishing_workspace/pyproject.toml`
- Create: `tools/publishing_workspace/src/publishing_workspace/__init__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/__main__.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/logging.py`
- Create: `tools/publishing_workspace/src/publishing_workspace/png_metadata.py`
- Create: `tools/publishing_workspace/tests/test_png_metadata.py`

**Interfaces:**
- Produces: `configure_logging(level)`, `get_logger(name)`。
- Produces: `read_png_text_chunks(path) -> dict[str, str]`。
- Produces: `publishing-workspace` console script 和 `python -m publishing_workspace`。

- [ ] 创建独立 `pyproject.toml`，只依赖 Pillow、Pydantic 和 PyYAML，开发依赖 pytest。
- [ ] 把 PNG `tEXt/zTXt/iTXt` 解析迁入 `png_metadata.py`，测试 UTF-8 JSON 文本块。
- [ ] 使用标准库 logging 实现 `trace/info/warning/error` 配置。
- [ ] 执行 `uv sync` 生成并提交独立 `uv.lock`。
- [ ] 运行 `uv run pytest tests/test_png_metadata.py -q`，预期通过。
- [ ] 精确暂存并提交：`feat(publishing-tool): scaffold standalone project`。

### Task 2: 迁移 Publishing 领域代码并解除 Core 依赖

**Files:**
- Move: `src/tags_machine_core/publishing/models.py` -> `tools/publishing_workspace/src/publishing_workspace/models.py`
- Move: `src/tags_machine_core/publishing/config.py` -> `tools/publishing_workspace/src/publishing_workspace/config.py`
- Move: `src/tags_machine_core/publishing/service.py` -> `tools/publishing_workspace/src/publishing_workspace/service.py`
- Move: `src/tags_machine_core/publishing/catalog/` -> `tools/publishing_workspace/src/publishing_workspace/catalog/`
- Move: `src/tags_machine_core/publishing/inputs/` -> `tools/publishing_workspace/src/publishing_workspace/inputs/`
- Move: `src/tags_machine_core/publishing/metadata/` -> `tools/publishing_workspace/src/publishing_workspace/metadata/`
- Move: `src/tags_machine_core/publishing/views/` -> `tools/publishing_workspace/src/publishing_workspace/views/`
- Create: `tools/publishing_workspace/tests/test_pipeline.py`

**Interfaces:**
- Consumes: 独立 `logging.py` 和 `png_metadata.py`。
- Produces: 原有 `PublishingService.initialize/import_source/classify/export` 行为。

- [ ] 改写所有包导入为 `publishing_workspace.*` 或相对导入。
- [ ] Catalog 使用独立 `read_png_text_chunks` 和 `get_logger`。
- [ ] 把内部 schema 改为 `publishing-workspace.*`，外部 Core PNG schema 保持不变。
- [ ] 迁移现有 Pipeline 测试，测试不 import Core 的执行模块；自行生成带文本块 PNG fixture。
- [ ] 运行 `rg "from tags_machine_core|import tags_machine_core" tools/publishing_workspace/src`，预期无结果。
- [ ] 运行 `uv run pytest -q`，预期独立项目测试通过。
- [ ] 精确暂存并提交：`feat(publishing-tool): migrate workspace domain`。

### Task 3: 迁移 CLI、文档和示例工作区

**Files:**
- Move/Rewrite: `src/tags_machine_core/publishing/cli.py` -> `tools/publishing_workspace/src/publishing_workspace/cli.py`
- Move/Rewrite: `docs/publishing_readme.md` -> `tools/publishing_workspace/README.md`
- Move: `docs/acceptance/publishing-workspace-phase-1.md` -> `tools/publishing_workspace/docs/acceptance-phase-1.md`
- Create: `tools/publishing_workspace/examples/README.md`
- Create: `tools/publishing_workspace/examples/workspace/.gitignore`
- Create: `tools/publishing_workspace/examples/workspace/workspace/workspace.yaml`
- Create: `.gitkeep` files for example runtime directories。
- Create: `tools/publishing_workspace/tests/test_cli.py`

**Interfaces:**
- Produces: `publishing-workspace init/import/classify/export`。
- Produces: 已初始化的 `examples/workspace`。

- [ ] 把嵌套 argparse 子命令改为独立顶层 CLI，不依赖 Core parser。
- [ ] 更新 README 中所有命令和路径。
- [ ] 配置 examples `.gitignore` 忽略 SQLite、imports、exports、state、cache 运行数据。
- [ ] 运行 `uv run publishing-workspace init examples/workspace`，确认本机生成有效 `catalog.sqlite`。
- [ ] 运行 `uv run publishing-workspace --help` 和 `uv run python -m publishing_workspace --help`。
- [ ] 精确暂存并提交：`feat(publishing-tool): expose standalone cli and example`。

### Task 4: 清理 Core 集成

**Files:**
- Delete: `src/tags_machine_core/publishing/`
- Delete: `tests/publishing/`
- Modify: `src/tags_machine_core/cli.py`
- Create/Modify: `docs/` 中 Publishing 迁移说明。

**Interfaces:**
- Removes: `python -m tags_machine_core publish`。
- Preserves: 其他 Core CLI、AgentComposer、Batch、Renderer 和 Web 行为。

- [ ] 删除 Core CLI 的 Publishing import 和 parser 注册。
- [ ] 删除原包与原测试，确认独立项目已有等价覆盖。
- [ ] 运行 `uv run python -m tags_machine_core publish --help`，预期 argparse 返回未知命令。
- [ ] 运行 `uv run pytest tests -q`，预期根项目回归通过。
- [ ] 精确暂存并提交：`refactor: extract publishing workspace from core`。

### Task 5: 真实业务验收和最终边界检查

**Files:**
- Update: `tools/publishing_workspace/docs/acceptance-phase-1.md`
- Update: `docs/superpowers/plans/2026-07-28-publishing-workspace-standalone-extraction-implementation.md`

**Interfaces:**
- Consumes: 真实 NeeView、Legacy PNG、Core PNG、Action manifest 和 Windows `.lnk`。
- Produces: 独立项目业务验收记录。

- [ ] 导入 `E:/NeeView41.3/Profile/Playlists/post_20251210.nvpls`，核对条目数和顺序。
- [ ] 导入真实 Legacy PNG，确认 `reader_counts.legacy`。
- [ ] 使用当前 Core RenderRequest 写入协议生成验收 PNG，确认 `reader_counts.core`。
- [ ] 确认真实 `category_view_manifest.json` 补出 action_group。
- [ ] 连续导出两次 `.nvpls`，第二次为 skipped。
- [ ] 执行 `.lnk` 导出和重新导入往返。
- [ ] 运行独立项目 `uv run pytest -q`。
- [ ] 运行根项目 `uv run pytest tests -q`。
- [ ] 确认 `git status` 只保留用户原有未提交修改。
- [ ] 精确暂存并提交：`test(publishing-tool): verify standalone business workflow`。

