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
    imports/
    exports/
      neev/
      shortcuts/
    cache/
    state/
  tasks/
```

`workspace` 是长期公共素材池，不属于某一个投稿任务。后续可以在同一个根目录下建立多个 `tasks/<task_id>`。

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

## 4. 图片节点 Reader

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

## 5. 分类与导出

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

## 6. 当前边界

第一阶段已经支持公共工作区、输入快照、新旧 Reader、Catalog、分类视图、增量 `.nvpls` 和可选 `.lnk`。

投稿任务、二次筛选、Bridge 排序回读、图片清参数、自动打码以及 `all/post/cover` 打包属于后续阶段。
