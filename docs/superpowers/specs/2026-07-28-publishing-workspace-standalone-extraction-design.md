# Publishing Workspace 独立项目迁移设计

## 1. 背景

Publishing Workspace 第一阶段当前位于：

```text
src/tags_machine_core/publishing/
tests/publishing/
```

并通过以下命令进入：

```powershell
uv run python -m tags_machine_core publish ...
```

Publishing 的业务职责是素材导入、图片节点读取、Catalog、分类视图和外部视图导出。它不参与提示词生成、AgentComposer、Renderer、Batch 或生图 Client，因此继续放在 `tags_machine_core` 内会让两个业务域形成不必要的生命周期和依赖耦合。

本次迁移把 Publishing 提取为 `refactor/tools` 下的独立 Python 项目。项目拥有自己的依赖、CLI、测试、文档、锁文件和 examples，不再 import `tags_machine_core`。

## 2. 目标

- 在 `tools/publishing_workspace/` 建立可独立安装和运行的 Python 项目。
- Publishing 源码不 import `tags_machine_core`。
- 删除 `tags_machine_core publish` CLI 入口和 Core 内 Publishing 包。
- 保留对新版 Core PNG 元数据协议和旧版图片字段的读取支持。
- 保留当前 Catalog、输入适配器、Reader、Action Group Enricher、分类和 Exporter 行为。
- 在独立项目的 `examples/workspace/` 初始化一个可直接使用的公共工作区。
- 示例运行状态不污染 Git。
- 根项目现有 AgentComposer、Batch、生图和 Web 行为不变。

## 3. 非目标

- 不保留 `tags_machine_core publish` 转发或兼容入口。
- 不把 Publishing 改造成独立 Git 仓库或 submodule。
- 不在本次迁移中实现投稿任务、图片处理和 `all/post/cover` 打包。
- 不改变 PNG 中已经发布的 `tags_machine_core` 输入协议。
- 不迁移或复制真实图片到 examples。
- 不创建新的开发分支；直接在当前 `refactor/main` 上实施。

## 4. 方案选择

采用完整独立迁移：

```text
refactor/tools/publishing_workspace/
```

不采用以下方案：

- Core 兼容包装：会保留双入口和长期兼容负担。
- Root workspace 共享包：仍会依赖根项目环境，不是真正独立项目。
- 独立仓库/submodule：当前功能规模不需要额外仓库管理成本。

## 5. 最终目录结构

```text
tools/publishing_workspace/
  pyproject.toml
  uv.lock
  README.md
  .gitignore

  src/
    publishing_workspace/
      __init__.py
      __main__.py
      cli.py
      config.py
      logging.py
      models.py
      png_metadata.py
      service.py

      catalog/
        __init__.py
        repository.py
        schema.py

      inputs/
        __init__.py
        base.py
        directory.py
        neev_playlist.py
        shortcut.py

      metadata/
        __init__.py
        enrichers.py
        readers.py
        registry.py

      views/
        __init__.py
        builder.py
        coordinator.py
        exporters.py

  tests/
    test_cli.py
    test_pipeline.py

  docs/
    acceptance-phase-1.md

  examples/
    README.md
    workspace/
      .gitignore
      workspace/
        workspace.yaml
        imports/.gitkeep
        exports/.gitkeep
        state/.gitkeep
        cache/.gitkeep
      tasks/.gitkeep
```

`catalog.sqlite` 会在本机实际初始化，但被 `examples/workspace/.gitignore` 忽略，不作为版本化示例文件。

## 6. 独立项目元数据

`tools/publishing_workspace/pyproject.toml`：

```toml
[project]
name = "publishing-workspace"
version = "0.1.0"
description = "Image catalog, classification, and publishing workspace tools."
requires-python = ">=3.11"
dependencies = [
  "Pillow>=10.0",
  "pydantic>=2.6",
  "PyYAML>=6.0",
]

[project.scripts]
publishing-workspace = "publishing_workspace.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = true

[dependency-groups]
dev = ["pytest>=9.1.1"]
```

该项目不声明 root `tags-machine-core`，也不通过相对路径把 Core 安装为依赖。

## 7. 依赖拆除

当前 Publishing 对 Core 的直接依赖只有：

```text
tags_machine_core.logging_config.get_logger
tags_machine_core.verification.read_png_text_chunks
```

迁移方式：

### 7.1 logging.py

使用 Python 标准库 `logging` 实现独立日志配置：

```text
configure_logging(level)
get_logger(name)
```

支持现有 CLI 级别：

```text
trace / info / warning / error
```

`trace` 映射为自定义低于 DEBUG 的级别，或者在第一版中映射为 DEBUG；具体实现必须在 README 中明确。

### 7.2 png_metadata.py

迁移最小 PNG 文本解析能力：

```text
read_png_text_chunks(path)
```

支持：

- `tEXt`
- `zTXt`
- `iTXt`
- UTF-8 和 Latin-1 fallback

该模块只负责图片元数据输入协议，不包含 Core Verification、参数 diff 或生图验收功能。

## 8. 数据协议边界

### 8.1 外部 Core PNG 协议

以下名称保持不变：

```text
PNG key: tags_machine_core
schema: tags-machine-core.png-info/v1
```

这是图片生产方与 Publishing Reader 之间的稳定数据协议。保留该字符串不代表 Python 代码依赖 Core。

### 8.2 Publishing 内部协议

内部 schema 改名为：

```text
publishing-workspace.workspace/v1
publishing-workspace.catalog/v1
publishing-workspace.import/v1
publishing-workspace.export-plan/v1
```

第一阶段 Catalog 尚未在其他环境形成稳定数据，因此迁移不提供旧 Catalog schema 自动升级。旧测试工作区应重新执行 `init/import`。

## 9. CLI

项目支持两个等价入口：

```powershell
uv run publishing-workspace --help
uv run python -m publishing_workspace --help
```

命令保持：

```text
publishing-workspace init ROOT
publishing-workspace import ROOT SOURCE
publishing-workspace classify ROOT
publishing-workspace export ROOT
```

参数保持：

- `--input-type neev_playlist|directory|shortcut`
- `--recursive`
- `--strict`
- `--legacy-tolerant`
- `--import-id`
- `--hierarchy`
- `--exporter neev|windows_shortcut`
- `--log-level trace|info|warning|error`

默认语义保持：

- 不指定 `--import-id` 时处理整个公共 Catalog。
- 指定 `--import-id` 时导出到 `_imports/<import_id>` 隔离目录。
- `.nvpls` 默认开启。
- `.lnk` 默认关闭。

## 10. 示例工作区

实施阶段实际执行：

```powershell
cd tools/publishing_workspace
uv run publishing-workspace init examples/workspace
```

生成的 `workspace.yaml` 使用相对路径：

```yaml
schema: publishing-workspace.workspace/v1

classification:
  hierarchy:
    - artist
    - character
    - action_group
    - action
  missing_value: unknown
  skip_missing: false

exporters:
  neev:
    enabled: true
    root: workspace/exports/neev
  windows_shortcut:
    enabled: false
    root: workspace/exports/shortcuts
```

示例工作区 `.gitignore`：

```gitignore
workspace/catalog.sqlite*
workspace/imports/*
workspace/exports/*
workspace/state/*
workspace/cache/*
!workspace/imports/.gitkeep
!workspace/exports/.gitkeep
!workspace/state/.gitkeep
!workspace/cache/.gitkeep
```

这样当前机器上存在有效空 Catalog，Git 中只保存可复制的配置和目录骨架。

## 11. 文档迁移

- `docs/publishing_readme.md` 内容迁入 `tools/publishing_workspace/README.md`，命令全部改为独立 CLI。
- `docs/acceptance/publishing-workspace-phase-1.md` 迁入独立项目 `docs/`。
- 根目录历史架构 spec 和实施计划保留，作为重构过程记录。
- 根目录新增一段简短迁移说明，明确 Publishing 已迁到 `tools/publishing_workspace`，不保留旧入口。

## 12. Core 清理

删除：

```text
src/tags_machine_core/publishing/
tests/publishing/
```

从 `src/tags_machine_core/cli.py` 删除：

```python
from tags_machine_core.publishing.cli import add_publishing_subparser
```

以及：

```python
add_publishing_subparser(...)
```

根 `pyproject.toml` 不增加 Publishing 相关依赖或脚本。

## 13. 测试迁移

独立项目测试覆盖：

- Workspace 初始化和重复初始化。
- NeeView 输入顺序和缺失项。
- Core Reader、Legacy fallback 和 unknown。
- Action Group manifest 补全。
- 内容 SHA-256 去重。
- 多角色视图。
- Catalog 聚合导出。
- `--import-id` 隔离导出。
- `.nvpls` 增量跳过。
- Windows `.lnk` 真实往返业务验收。
- 独立 CLI。

独立测试命令：

```powershell
cd tools/publishing_workspace
uv run pytest -q
```

根项目回归：

```powershell
cd ../..
uv run pytest tests -q
```

Publishing 测试迁出后，根项目测试数量会相应减少，这不视为覆盖下降；对应测试由独立项目继续执行。

## 14. 业务验收

迁移完成必须重新执行：

1. 导入真实 NeeView 播放列表。
2. 导入真实旧版 PNG，确认 Legacy Reader。
3. 导入当前 Core PNG，确认 `tags_machine_core` Reader。
4. 使用真实 action ref 和 `category_view_manifest.json` 补全 action_group。
5. 连续两次导出 `.nvpls`，第二次必须 `skipped`。
6. 导出 `.lnk` 后重新导入，必须定位到原 Asset。
7. 初始化 `examples/workspace`，确认配置、SQLite schema 和目录均有效。

## 15. 静态边界检查

以下检查必须通过：

```powershell
rg "from tags_machine_core|import tags_machine_core" tools/publishing_workspace/src
```

结果必须为空。

允许出现的字符串仅限输入协议，例如：

```text
tags_machine_core
tags-machine-core.png-info/v1
```

根 CLI 检查：

```powershell
uv run python -m tags_machine_core publish --help
```

必须返回未知命令，而不是继续暴露旧 Publishing 入口。

## 16. Git 与迁移约束

- 在当前 `refactor/main` 上实施，不创建新分支。
- 不提交现有工作区中与 Publishing 无关的修改。
- 使用精确路径暂存，不使用 `git add -A`。
- 代码迁移、Core 清理、独立测试与文档可以分成独立提交。
- `examples/workspace/workspace/catalog.sqlite*` 不进入 Git。

