# Publishing Workspace

Publishing 工作区用于把 NeeView 收藏、普通图片目录或旧 `.lnk` 分类目录统一导入 Catalog，再按图片内嵌节点生成可重建的分类视图。

这是一个独立 Python 项目，不依赖 `tags_machine_core`。它不参与提示词拼接和生图，也不会移动、改名、删除或复制原始图片。

进入项目并安装依赖：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv sync
```

仓库内提供了已初始化的空示例工作区：

```powershell
uv run publishing-workspace import examples/workspace <图片目录或 NeeView.nvpls>
uv run publishing-workspace export examples/workspace --log-level info
```

示例只提交 `workspace.yaml` 和目录骨架，Catalog、导入快照和导出结果不会进入 Git。

如果根目录由旧 `tags_machine_core publish` 初始化，独立工具首次加载时会自动把 `workspace.yaml` 和 `catalog.sqlite` 升级到 `publishing-workspace.*` 内部 schema。配置升级前会保留 `workspace.yaml.tags-machine-core-v1.bak`，Catalog 升级在事务内执行并保留现有数据。该过程属于单向迁移，处理重要工作区前仍建议先备份整个 `workspace/`。

## 1. 初始化

```powershell
uv run publishing-workspace init G:\ai_publish
```

目录结构：

```text
G:/ai_publish/
  workspace/
    workspace.yaml
    catalog.sqlite
    backups/
    imports/
    exports/
      neev/
      shortcuts/
    cache/
    state/
  tasks/
```

`workspace` 是长期公共素材池，不属于某一个投稿任务。后续可以在同一个根目录下建立多个 `tasks/<task_id>`。

完整 NeeView 收藏列表应先导入公共 `workspace`，不要直接作为一次投稿任务的 `candidates`。投稿任务只接收本次人工筛选后的子集；如果需要从公共 Catalog 选图，先通过分类视图、NeeView 播放列表或目录整理出一个较小输入，再导入 `tasks/<task_id>/selection/`。

## 2. workspace.yaml

初始化后的默认配置：

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

image_extensions:
  - .png
  - .jpg
  - .jpeg
  - .webp
```

字段含义：

- `schema`：工作区配置版本，当前固定为 `publishing-workspace.workspace/v1`。
- `classification.hierarchy`：分类层级，可使用图片中存在的任意节点 role。
- `classification.missing_value`：图片缺少某一层节点时使用的目录名。
- `classification.skip_missing`：为 `true` 时，只要缺少任一层就不生成该图片的分类视图。

`classification.missing_value` 默认是 `unknown`。分类层级中的任意节点缺失时，Publishing Workspace 会在运行时投影该值；原始 Reader 和 Catalog 不会被修改。

默认 `skip_missing: false`，所以没有节点信息的图片也会导出到：

```text
unknown/unknown/unknown/unknown
```

只有显式设置 `skip_missing: true`，缺少任意分类节点的图片才会被排除。Reader 结果中的 `unknown` 表示没有 Reader 成功解析元数据；分类路径中的 `unknown` 表示某个分类 role 缺失，两者含义不同。

- `exporters.neev.enabled`：默认自动导出 NeeView `.nvpls`。
- `exporters.windows_shortcut.enabled`：是否同时导出旧式 Windows `.lnk` 分类树。
- `exporters.*.root`：绝对路径，或相对于 Publishing 根目录的路径。
- `image_extensions`：目录输入允许导入的图片扩展名。

## 3. 导入

### NeeView 收藏列表

```powershell
uv run publishing-workspace import `
  G:\ai_publish `
  E:\NeeView41.3\Profile\Playlists\select.nvpls
```

`.nvpls` 会自动识别，也可以显式添加：

```powershell
--input-type neev_playlist
```

导入保留 `Items` 原始顺序，并在 `workspace/imports/<import_id>.json` 保存快照。后续修改 NeeView 原列表不会悄悄改变这次导入。

### 普通图片目录

```powershell
uv run publishing-workspace import `
  G:\ai_publish `
  G:\ai_auto\20260727 `
  --input-type directory `
  --recursive
```

目录按自然文件名排序。目录内的 `.lnk` 会先解析到原图，再进入相同的导入链路。

### 单个快捷方式

```powershell
uv run publishing-workspace import `
  G:\ai_publish `
  G:\old_select\0001_example.png.lnk `
  --input-type shortcut
```

常用选项：

- `--strict`：图片缺失、损坏或格式不支持时立即终止整次导入。
- `--legacy-tolerant`：显式使用 JSON 宽松控制字符模式读取旧 NeeView 列表；恢复行为会写入 warning。
- `--log-level info`：显示导入数量、Reader 命中和导出过程。
- `--retry-failed`：强制重试本次输入中与 open problem 指纹相同的项目；默认保持为 `held_problem`。

导入结果示例：

```json
{
  "import_id": "aeafeec697fa467b897fd3eeb24771e3",
  "total_items": 10,
  "imported_items": 10,
  "missing_items": 0,
  "failed_items": 0,
  "unique_assets": 9,
  "reader_counts": {
    "core": 6,
    "legacy": 3,
    "unknown": 1
  },
  "snapshot_path": "G:\\ai_publish\\workspace\\imports\\aeafeec697fa467b897fd3eeb24771e3.json"
}
```

`unique_assets` 按图片内容 SHA-256 去重。同一图片来自多个路径或多个播放列表时，只建立一个 Asset，但保留全部来源记录。

## 4. 可恢复导入与问题队列

默认每批提交 200 项。`info` 日志每 200 项或 5 秒输出一次，运行状态和每个输入项都保存在 SQLite 中；进程中断后不需要重新读取 NeeView 列表。

查看最近 Run：

```powershell
uv run publishing-workspace status G:\ai_publish --log-level info
uv run publishing-workspace status G:\ai_publish <run_id>
```

恢复中断或租约过期的 Run：

```powershell
uv run publishing-workspace resume G:\ai_publish <run_id> --log-level info
```

查询问题：

```powershell
uv run publishing-workspace problems G:\ai_publish --status open
uv run publishing-workspace problems G:\ai_publish --code empty_file
uv run publishing-workspace problems G:\ai_publish --run-id <run_id>
```

修复原始图片后，按问题类型创建新的重试 Run：

```powershell
uv run publishing-workspace retry-problems G:\ai_publish --code empty_file --log-level info
uv run publishing-workspace retry-problems G:\ai_publish --run-id <run_id>
```

问题状态包括 `open`、`resolved`、`ignored`。相同路径、大小和修改时间的问题默认不重复解析；文件变化或显式重试后才重新进入解析。有效但没有节点信息的图片不是问题，会以 `reader=unknown` 进入 Catalog。

导入结果的核心字段：

```json
{
  "run_id": "...",
  "status": "completed_with_errors",
  "total_items": 10010,
  "processed_items": 10010,
  "reused_path_items": 9780,
  "reused_content_items": 12,
  "parsed_new_items": 195,
  "missing_items": 0,
  "failed_items": 23,
  "held_problem_items": 0,
  "open_problems": 23,
  "snapshot_path": "G:\\ai_publish\\workspace\\imports\\<run_id>.json"
}
```

同一 workspace 同时只允许一个写入型 ImportRun。`status`、`problems` 等查询命令不获取写锁；活动 Run 的租约未过期时，另一个写入命令会直接拒绝。

## 5. 图片节点 Reader

Reader Registry 按以下顺序工作：

1. `CoreImageNodeReader` 读取新版 PNG 的 `tags_machine_core` JSON。
2. 新版字段不存在或损坏时，`LegacyImageNodeReader` 读取顶层 `artist/artist_path/character/action/topic/background`。
3. 两者都无法读取时，图片仍进入 Catalog，Reader 为 `unknown`，分类维度使用 `missing_value`。

Reader 之后会运行 `ActionGroupManifestEnricher`。如果新版图片只有 `action`、没有 `action_group`，它会从 action ref 向上查找 `category_view_manifest.json`，按 `source/dest` 反查全部动作组。一项动作属于多个组时，会生成多个分类视图。该逻辑不写入 Reader，也不修改图片元数据。

旧字段映射：

| 旧 PNG 字段 | 统一 role |
| --- | --- |
| `artist` / `artist_path` | `artist` |
| `character` | `character` |
| `topic` | `action_group` |
| `action` | `action` |
| `background` | `background` |

新版优先，不会把新版和旧版节点混合投票。新版损坏后回退旧版时，导入快照会记录 warning。

## 6. 分类与导出

只构建分类计划：

```powershell
uv run publishing-workspace classify G:\ai_publish
```

默认分类整个公共 Catalog，持续导入不会让上一批素材从公共视图消失。只检查指定导入快照：

```powershell
uv run publishing-workspace classify `
  G:\ai_publish `
  --import-id aeafeec697fa467b897fd3eeb24771e3
```

临时覆盖层级：

```powershell
--hierarchy artist character action
```

构建计划并导出：

```powershell
uv run publishing-workspace export G:\ai_publish --log-level info
```

显式使用 `--import-id` 时，局部结果写入 `workspace/exports/<exporter>/_imports/<import_id>`，不会覆盖公共 Catalog 视图。

只导出指定格式：

```powershell
uv run publishing-workspace export `
  G:\ai_publish `
  --exporter neev `
  --exporter windows_shortcut
```

NeeView 输出示例：

```text
workspace/exports/neev/
  20260412/
    akemi_homura/
      st_foot/
        foot_detail_001.nvpls
```

多角色图片会进入多个 `character` 叶子视图。每个 `.nvpls` 内仍引用原图，不复制图片。

Exporter 对“视图路径、成员、顺序、Exporter 版本”计算哈希。重复执行且内容未变时返回 `skipped`，不改写文件时间。过时文件只会在对应 Exporter 自己的输出根目录内，依据 Catalog 中的生成记录清理。

Windows 快捷方式 Reader 和 Exporter 会通过同卷短临时路径调用 `WScript.Shell`，因此分类目录中包含中文、日文或较长节点名称时也可以正常往返。

## 7. 当前边界

当前已支持公共工作区、持久化 ImportRun、分批恢复导入、ProblemQueue、新旧 Reader、Catalog、分类视图、任务选择集合、图片清参数和 `all/post/cover` 投稿包构建。

## 7. 投稿任务

公共 `workspace/` 是长期素材池；投稿任务位于同一根目录下的 `tasks/<task_id>/`，任务创建后复制进去的图片成为该任务自己的快照。

创建空任务：

```powershell
uv run publishing-workspace task create G:\ai_publish 20260801_homura_foot
```

从 NeeView 收藏创建任务，并自动复制到 `selection/all/`：

```powershell
uv run publishing-workspace task create G:\ai_publish 20260801_homura_foot --candidates E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls --log-level info
```

替换或追加 `post`、`cover`：

```powershell
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot --set post --source E:\NeeView41.3\Profile\Playlists\post.nvpls --mode replace
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot --set cover --source E:\NeeView41.3\Profile\Playlists\cover.nvpls --mode replace
```

三个选择集合也可以从普通目录或快捷方式目录导入：

```powershell
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot --set all --source G:\ai_select\homura --input-type directory
```

任务目录结构：

```text
tasks/<task_id>/
  task.yaml
  selection/
    candidates.snapshot.json
    candidates.nvpls
    history/
      <time>-all-<history_id>.json
    all/
    post/
    cover/
  builds/<build_id>/
    selection_snapshot.json
    build_manifest.json
    output/all/
    output/post/
    output/cover/
    archives/
```

`selection/all`、`selection/post`、`selection/cover` 只放图片。可以直接删除、重命名或用 Adobe Bridge 调整文件名；构建时当前目录内容和自然文件名顺序优先，历史导入记录不会把删除的图片恢复回来。

一次投稿任务建议只包含本次要处理的图片。公共 workspace 可以长期保存数千或更多图片，但它和单次投稿任务的生命周期、选择范围不同。

查看任务状态：

```powershell
uv run publishing-workspace task status G:\ai_publish 20260801_homura_foot
```

构建投稿包：

```powershell
uv run publishing-workspace task build G:\ai_publish 20260801_homura_foot
```

构建始终生成 `output/all`、`output/post`、`output/cover`。任务配置中的 ZIP 开关打开后，`archives/` 下按集合生成 ZIP。`post` 不要求是 `all` 的子集，`cover` 不要求属于 `post`，这些关系只记录 warning。

默认 `strip_metadata` 开启，输出图片会清除 prompt、negative prompt、seed 等 PNG 内部参数；公共 workspace 原图和任务 selection 图片都不会被修改。构建期间会生成 `selection_snapshot.json`，该文件和 `build_manifest.json` 不会进入对外目录或 ZIP。

### 7.1 task.yaml

```yaml
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
```

`mosaic` 默认关闭；开启时必须提供已注册的适配器，否则 build 会失败且不会生成正式 build。
