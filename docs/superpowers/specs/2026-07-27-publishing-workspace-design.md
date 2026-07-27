# 投稿筛选与打包工作区设计

## 1. 背景

当前投稿工作流由 `F:\ThreeState\select_handler.py` 和若干外部工具共同完成：

1. 在 NeeView 浏览图片，并把初选好图加入 `E:\NeeView41.3\Profile\Playlists` 下的收藏列表。
2. 调用旧版 `new_lnk_character_type`，根据图片内嵌节点信息建立 `artist / character / action_group / action / image` 分类快捷方式树。
3. 在分类结果中进行二次筛选。
4. 必要时使用 Adobe Bridge 对图片人工排序，并通过数字前缀重命名固化顺序。
5. 调用旧版 `process_all`：解析快捷方式、复制原图、清除 PNG 参数、自动打码。
6. 生成投稿目录：`all` 保存完整赞助图包，`post` 保存 Pixiv 投稿子集，`cover` 保存可选封面候选。

该流程的业务语义已经稳定，但存在以下问题：

- 输入、节点解析、分类、快捷方式创建、人工筛选和图片处理耦合在脚本中。
- 分类依赖为每张图片创建 Windows `.lnk`，大量小文件创建速度慢。
- 路径和外部工具写死，难以迁移到服务器、前端或其他图片管理工具。
- `all / post / cover` 的关系依赖人工约定，缺少构建前校验和可追溯记录。
- 图片清参数、打码和最终打包没有统一的可扩展处理接口。

本设计在 PromptAtelier/refactor 内新增独立的 Publishing 业务域。它复用已有图片元数据读取、节点解析、Action Resolver、配置和日志能力，但不进入 Composer、Renderer、Batch 或生图主链路。

## 2. 目标

- 支持 NeeView `.nvpls`、普通目录、快捷方式目录等多种输入。
- 所有输入适配器向下游输出相同的数据结构。
- 通过统一 Reader 接口读取新版和旧版图片节点信息，并向 classify 输出相同结构。
- 建立长期存在的公共 workspace，可持续导入图片并创建多个投稿任务。
- 使用 SQLite 管理大规模图片索引，不依赖文件夹作为业务事实来源。
- 按 `artist / character / action_group / action` 建立可配置分类视图。
- 分类完成后自动导出所有非空叶子视图。
- 通过可扩展 Exporter 支持 `.nvpls`、`.lnk`、符号链接及未来其他输出格式。
- 保留 NeeView 初选、文件夹二筛和 Adobe Bridge 人工排序。
- 一个公共 workspace 支持创建任意多个投稿任务，同一图片允许跨任务复用。
- `post` 必须是 `all` 的子集，`cover` 最多一张且必须属于 `post`。
- `all` 和 `post` 第一阶段共用相同图片预处理结果，仅选图范围不同。
- 图片处理步骤可配置、可缓存、可扩展。
- 最终对外目录只包含处理后的图片，不泄露 prompt、seed、本地路径或节点信息。
- 业务验收优先使用真实 NeeView 列表、真实图片和旧版流程对比。

## 3. 非目标

- 第一阶段不实现 Pixiv 自动登录和自动投稿。
- 不替代 NeeView 和 Adobe Bridge 的人工审美判断。
- 不把 Publishing 逻辑塞入现有 `task_tools` 通用 Windows 操作层。
- 不修改 AgentComposer、ScriptComposer、PromptPolicyPipeline、Renderer 或生图 Client。
- 不要求迁移现有提示词库。
- 不默认把 `.lnk` 作为新流程的主要分类表现形式。
- 不在公共 workspace 中复制全部原始图片。
- 不允许构建流程修改、移动或删除原始生图。

## 4. 核心设计原则

### 4.1 输入和表现形式分离

Input Adapter 负责把外部数据读成统一的 `SelectionSet`；View Exporter 负责把逻辑视图输出为外部工具可使用的格式。下游业务不判断输入来自 NeeView、目录还是快捷方式。

### 4.2 Catalog 是公共事实来源

公共 workspace 中的 `catalog.sqlite` 保存图片、节点、导入来源、任务使用关系和导出状态。分类目录、播放列表和快捷方式都是可重建视图，不是唯一事实来源。

### 4.3 投稿任务保存选择，不拥有原图

任务只保存候选快照、人工选择来源、排序和构建记录。原图由 `asset_id` 和 Catalog 定位，同一图片可以属于多个任务。

### 4.4 人工操作有明确边界

NeeView 用于浏览和初选；文件夹用于二次筛选；Bridge 通过重命名固化顺序。系统负责把这些操作结果重新标准化并校验，不尝试自动替代人工审美。

### 4.5 构建不可破坏原始素材

预处理和打包只写入缓存、临时构建目录和正式 build。任何失败都不能污染原图或留下看似成功的半成品。

### 4.6 可插拔 Strategy/Adapter

Reader 和 Exporter 都采用可插拔 Strategy/Adapter 结构：调用方依赖稳定接口，Registry 管理具体实现。增加新的图片节点格式或视图输出格式时，只新增实现并注册，不修改 classify、Catalog 和投稿任务代码。

## 5. 总体架构

```text
外部输入
  NeeViewPlaylistInput
  DirectoryInput
  ShortcutInput
  FutureInput
        |
        v
    ImportService
        |
        v
    SelectionSet
        |
        v
 ImageNodeReaderRegistry
        |
        v
   ImageNodeInfo
        |
        v
    AssetCatalog <---- ActionResolver
        |
        v
 ClassificationViewBuilder
        |
        v
      ExportPlan
        |
        v
  ViewExportCoordinator
    |       |        |
  nvpls    .lnk    symlink / future

AssetCatalog
    |
    v
PublishTask + Selection Sources
    |
    v
TaskSelectionResolver
    |
    v
ValidatedSelectionSet
    |
    v
ImageProcessingPipeline
    |
    v
PackageBuilder
    |
    v
all / post / cover / optional ZIP
```

建议代码边界：

```text
src/tags_machine_core/publishing/
  __init__.py
  cli.py
  config.py
  models.py
  catalog/
    repository.py
    schema.py
  inputs/
    base.py
    neev_playlist.py
    directory.py
    shortcut.py
  metadata/
    models.py
    registry.py
    readers/
      base.py
      core.py
      legacy.py
  views/
    builder.py
    models.py
    coordinator.py
    exporters/
      base.py
      neev_playlist.py
      windows_shortcut.py
      symbolic_link.py
      copy_directory.py
  tasks/
    repository.py
    candidates.py
    selection.py
    validator.py
  processing/
    pipeline.py
    registry.py
    cache.py
    operations/
      strip_metadata.py
      mosaic.py
  packaging/
    builder.py
    archive.py
```

Publishing 可以调用通用图片读取和 Action Resolver，但其他模块不反向依赖 Publishing。

## 6. 目录结构

```text
<publish_root>/
  workspace/
    workspace.yaml
    catalog.sqlite
    imports/
      <import_id>.json
    exports/
      neev/
      shortcuts/
      symlinks/
    cache/
      processed/
    state/
      exports/

  tasks/
    <task_id>/
      task.yaml
      selection/
        candidates.snapshot.json
        candidates.nvpls
        all/
        post/
        cover/
      builds/
        <build_id>/
          build_manifest.json
          output/
            all/
            post/
            cover/
          archives/
            all.zip
            post.zip
```

`workspace` 是公共、长期存在的素材工作区。`tasks` 中的每个目录只代表一次投稿工作，不复制整个公共分类树。

## 7. 统一数据契约

### 7.1 ImportedItem

所有 Input Adapter 输出：

```yaml
source_path: G:/ai_auto/example.png
resolved_path: G:/ai_auto/example.png
source_type: neev_playlist
source_ref: E:/NeeView41.3/Profile/Playlists/select.nvpls
source_order: 12
display_name: example.png
warnings: []
```

字段语义：

- `source_path`：输入中原始记录的路径，可能是图片或快捷方式。
- `resolved_path`：解析后的真实图片路径。
- `source_type`：输入适配器类型。
- `source_ref`：播放列表、目录或其他输入来源。
- `source_order`：输入中的顺序。
- `display_name`：用于视图导出的建议名称。
- `warnings`：可恢复问题，不用于静默吞掉错误。

### 7.2 SelectionSet

```text
SelectionSet
  id: str
  source: InputSource
  items: list[ImportedItem]
  created_at: datetime
  warnings: list[str]
```

约束：

- 保留输入顺序。
- 以最终 `asset_id` 去重时保留第一次出现的位置。
- 输入适配器不读取角色和动作业务规则。

### 7.3 AssetRecord

```yaml
asset_id: sha256:...
path: G:/ai_auto/example.png

fingerprint:
  size: 1234567
  modified_ns: 1780000000000000000
  sha256: "..."

image:
  width: 832
  height: 1216
  format: PNG

nodes:
  artist:
    - "20260412"
  character:
    - "akemi_homura"
  action_group:
    - "st_foot"
  action:
    - "foot_detail_001"

imports:
  - source_type: neev_playlist
    source_ref: select.nvpls
    source_order: 12

used_by:
  - "20260727_homura_foot"

warnings: []
```

`artist`、`character`、`action_group`、`action` 均使用列表，不能假设一张图只有一个角色或一个分类来源。

### 7.4 ImageNodeInfo

所有图片节点 Reader 输出相同结构：

```yaml
format: core
reader: core

nodes:
  - role: artist
    id: "20260412"
    ref: "F:/design/画风/20260412"
    index: 0

  - role: character
    id: akemi_homura
    ref: "F:/design/角色/akemi_homura"
    index: 0

  - role: action
    id: foot_detail_001
    ref: "F:/design/动作改2/new/foot_detail_001"
    index: 0

warnings: []
```

统一模型：

```text
ImageNodeInfo
  format: core | legacy | unknown
  reader: str
  nodes: list[ImageNodeRef]
  warnings: list[str]

ImageNodeRef
  role: str
  id: str | null
  ref: str | null
  index: int
```

`role` 第一阶段支持 `artist`、`character`、`action_group`、`action` 和 `background`，模型本身不使用枚举封死未来角色。

### 7.5 asset_id 与哈希缓存

- `asset_id` 使用图片内容 SHA-256，保证图片移动后仍可识别。
- Catalog 按绝对路径、文件大小和修改时间缓存哈希。
- 文件状态未变化时不重新读取完整图片计算哈希。
- 同内容不同路径合并为同一 Asset，但保留可用路径列表和来源记录。

### 7.6 ViewEntry 与 ExportPlan

```yaml
hierarchy:
  - artist
  - character
  - action_group
  - action

views:
  - path:
      - "20260412"
      - "akemi_homura"
      - "st_foot"
      - "foot_detail_001"
    items:
      - asset_id: sha256:...
        source_path: G:/ai_auto/example.png
        display_name: example.png
        order: 1
```

ClassificationViewBuilder 只产出 ExportPlan，不直接操作文件系统输出格式。

## 8. 输入适配层

### 8.1 InputAdapter 接口

```text
InputAdapter
  type
  probe(source) -> bool
  validate(source, context)
  load(source, context) -> SelectionSet
```

输入类型优先由显式 `type` 决定；未指定时才通过扩展名和路径类型探测。

### 8.2 NeeViewPlaylistInput

支持 NeeView `NeeView.Playlist/2.0.0` 格式：

```json
{
  "Format": "NeeView.Playlist/2.0.0",
  "Items": [
    {"Path": "G:\\ai_auto\\example.png"}
  ]
}
```

规则：

- 保留 `Items` 顺序。
- Item 可以指向真实图片或 `.lnk`。
- 使用 UTF-8/UTF-8 BOM 读取。
- 严格解析失败时报告文件、偏移和原因。
- 可以提供显式 `legacy_tolerant` 模式处理旧列表中的异常转义，但不得静默修改路径；每个恢复项必须记录 warning。
- 不在构建时实时读取候选播放列表。导入后生成任务候选快照，避免播放列表后续修改导致任务悄悄变化。

### 8.3 DirectoryInput

- 支持非递归和递归扫描。
- 支持可配置图片扩展名。
- 使用 natural sort。
- 普通文件夹、Bridge 排序目录和 `all/post/cover` 都通过该适配器进入统一 SelectionSet。

### 8.4 ShortcutInput

- 解析 Windows `.lnk` 到真实目标。
- 目标不存在时记录 broken item；是否阻止导入由 strict 配置决定。
- 该适配器用于读取旧数据，不意味着新系统默认输出 `.lnk`。

## 9. 公共 Catalog 与图片节点 Reader

### 9.1 Catalog 职责

`catalog.sqlite` 至少维护：

- Asset 基础信息和内容哈希。
- 图片路径及路径有效状态。
- 导入批次和来源顺序。
- artist、character、action_group、action 节点关联。
- 分类视图成员关系。
- 投稿任务使用关系。
- Exporter 导出状态和输出清单。
- 图片处理缓存状态。

### 9.2 ImageNodeReader 接口

```text
ImageNodeReader
  id
  priority
  supports(image_metadata) -> bool
  read(image_path, image_metadata) -> ImageNodeInfo
```

Reader 只负责把一种图片节点格式转换成统一 `ImageNodeInfo`，不创建分类目录，不执行 Exporter，也不包含投稿任务规则。

### 9.3 CoreImageNodeReader

读取新版图片内嵌的结构化字段：

```text
tags_machine_core
  schema
  nodes
  source_nodes
```

规则：

- 第一阶段支持 `tags-machine-core.png-info/v1`。
- `nodes` 中的 role、id、ref、index 原样标准化为 `ImageNodeRef`。
- 保留多个 character 和其他重复 role，不压缩成单值。
- 未识别 schema 时返回 warning，不按已知新版结构强行解析。
- 新版图片同时存在旧兼容字段时，以合法的结构化字段为准。

### 9.4 LegacyImageNodeReader

读取旧 tags_machine 图片顶层字段：

```text
artist
artist_path
character
action
topic
background
```

映射规则：

- `artist` 和 `artist_path` 合并为 artist 的 id/ref。
- `character` 映射为 character。
- `action` 映射为 action。
- `topic` 映射为 action_group。
- `background` 映射为 background。
- 字段兼容普通字符串和 JSON 数组字符串。
- 缺少某个字段时只省略对应节点，不阻止读取其他字段。

### 9.5 ImageNodeReaderRegistry

```text
ImageNodeReaderRegistry
  |- CoreImageNodeReader
  `- LegacyImageNodeReader
```

选择规则：

1. 存在合法 `tags_machine_core` 时使用 Core Reader。
2. 否则，存在任意旧版节点字段时使用 Legacy Reader。
3. 新版结构存在但损坏时，可以 fallback 到 Legacy Reader，并在结果中记录 warning。
4. 两个 Reader 都不支持时返回 `format: unknown`、空 nodes 和明确 warning。

第一阶段不同时运行两个 Reader，也不引入 Evidence 合并、置信度或冲突投票系统。未来支持新图片格式时，实现并注册新的 Reader 即可。

### 9.6 节点解析与 classify

Reader 输出后，可以通过现有 Action Resolver 将旧 action/action_group 引用定位到原始 Action。该解析属于 Reader 下游，不写进 Core 或 Legacy Reader。

节点缺失不阻止素材进入 Catalog；classify 使用统一 `ImageNodeInfo.nodes`，缺失维度进入 `unknown` 或按配置跳过。classify 不判断 `format` 和具体 Reader 类型。

## 10. 分类视图

默认分类层级：

```yaml
classification:
  hierarchy:
    - artist
    - character
    - action_group
    - action
```

规则：

- 层级来自配置，不为指定角色、动作组或 artist 写特殊分支。
- 一张多角色图片可以出现在多个 character 分支中。
- 一张图片存在多个 action 映射时可以出现在多个叶子视图中。
- 同一叶子视图内按配置排序，默认使用导入顺序，再以 natural filename 作为稳定次序。
- 所有非空叶子分类都产生 ViewEntry。
- 上级目录只组织叶子视图，第一阶段不额外生成聚合父级播放列表；Exporter 后续可支持 `scope: all_levels`。

## 11. View Export System

### 11.1 边界

逻辑视图存在于 Catalog 和 ExportPlan 中。只有 View Exporter 会创建 `.nvpls`、`.lnk`、符号链接或真实图片目录。

### 11.2 ViewExporter 接口

```text
ViewExporter
  type
  version
  validate(config, environment)
  export(export_plan, target_root, previous_state) -> ExportResult
  clean_stale(previous_state, current_state) -> CleanupResult
```

Exporter 接收整个 ExportPlan，以便批量优化、增量更新和清理失效视图。

### 11.3 首批 Exporter

#### NeeViewPlaylistExporter

输出：

```text
workspace/exports/neev/
  20260412/
    akemi_homura/
      st_foot/
        foot_detail_001.nvpls
```

一个叶子分类只生成一个播放列表，不为每张图片创建文件。

#### WindowsShortcutExporter

输出：

```text
workspace/exports/shortcuts/
  20260412/
    akemi_homura/
      st_foot/
        foot_detail_001/
          example.png.lnk
```

作为正式可选 Exporter 保留，用于旧工具和旧习惯，不作为默认输出。

#### SymbolicLinkExporter

输出具有图片扩展名的文件符号链接。启用前必须检查 Windows 权限或开发者模式；环境不支持时给出明确错误，不自动降级为其他格式。

#### CopyDirectoryExporter

复制真实图片到目标目录，主要用于 Adobe Bridge 工作目录。它不应用于整个公共分类树的默认自动导出。

### 11.4 配置

```yaml
classification:
  hierarchy:
    - artist
    - character
    - action_group
    - action

  auto_export: true

  exporters:
    - id: neev
      type: neev_playlist
      enabled: true
      output: workspace/exports/neev
      scope: leaf
      required: true

    - id: legacy_shortcuts
      type: windows_shortcut
      enabled: false
      output: workspace/exports/shortcuts
      scope: leaf
      required: false

    - id: symlinks
      type: symbolic_link
      enabled: false
      output: workspace/exports/symlinks
      scope: leaf
      required: false
```

每次导入和分类成功后，自动执行全部已启用 Exporter，覆盖所有非空叶子视图。

### 11.5 增量导出

每个 Exporter 状态记录：

- 视图成员哈希。
- 成员顺序哈希。
- Exporter 配置哈希。
- Exporter 版本。
- 已生成文件清单。

只有成员、顺序、配置、版本或输出存在状态变化时才重新导出。未变化视图直接跳过。

### 11.6 安全清理

- 每个 Exporter 使用独立根目录。
- 根目录包含 Publishing 托管标识和 exporter id。
- 只能删除上次状态明确记录为本 Exporter 生成的文件。
- 不删除未知文件，不遍历其他 Exporter 根目录。
- 输出先写临时文件，再原子替换。
- 单个非 required Exporter 失败只记录错误和不完整状态，不回滚 Catalog 导入。
- required Exporter 失败时命令返回失败，但 Catalog 数据仍保持完整。

## 12. 投稿任务与候选快照

### 12.1 创建任务

创建空任务：

```powershell
uv run python -m tags_machine_core publish create-task `
  20260727_homura_foot
```

创建任务时只执行：

- 创建任务目录和 `task.yaml`。
- 创建 `selection/all`、`selection/post`、`selection/cover`。
- 初始化空候选快照。
- 不处理图片，不创建 build，不假设二次筛选已经完成。

### 12.2 从 NeeView 创建候选

```powershell
uv run python -m tags_machine_core publish create-task `
  20260727_homura_foot `
  --candidates E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls
```

或追加：

```powershell
uv run python -m tags_machine_core publish add-candidates `
  20260727_homura_foot `
  E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls
```

规则：

- 任意 Input Adapter 都可以作为 candidates 来源。
- 新图片自动导入公共 Catalog 并补全节点信息。
- 按 asset_id 去重，保留第一次出现顺序。
- 写入不可变候选导入记录和当前 `candidates.snapshot.json`。
- 自动通过 View Export System 生成 `candidates.nvpls`。
- 播放列表后续变化不会自动改变任务。

### 12.3 候选更新

```text
add-candidates      追加候选，不移除现有候选
replace-candidates  使用新输入替换 candidates，但不修改 all/post/cover
```

### 12.4 人工二次筛选

默认人工工作目录：

```text
selection/
  candidates.snapshot.json
  candidates.nvpls
  all/
  post/
  cover/
```

流程：

1. 使用 NeeView 打开 `candidates.nvpls`。
2. 需要 Bridge 时，通过 CopyDirectoryExporter 把 candidates 物化为真实图片目录。
3. 在文件夹中删除不保留图片，并通过 Bridge 数字前缀重命名排序。
4. `all` 保存二筛后的全部图片。
5. `post` 保存 `all` 的 Pixiv 投稿子集。
6. `cover` 最多保存一张封面候选。

Bridge 排序只以最终文件名 natural sort 为准，不读取 Bridge 私有排序状态或 XMP 排序字段。

### 12.5 集合关系

- `post` 必须是 `all` 的子集，按 asset_id 判断，不按文件名判断。
- `cover` 必须为空或只有一张图片。
- `cover` 必须属于 `post`。
- cover 不会被自动移动到 post 第一张；投稿时由用户手工处理。
- 同一选择集合不能重复引用相同 asset_id。
- 同一图片可以属于多个任务，Catalog 记录 `used_by` 并给出提示，不阻止构建。

## 13. 图片复制与物化规则

### 13.1 不复制图片的环节

- 导入 NeeView、目录或快捷方式。
- 计算和更新 Catalog。
- 节点元数据补全。
- 分类逻辑视图构建。
- `.nvpls` 导出。
- `.lnk` 或符号链接导出。

### 13.2 会生成新图片数据的环节

1. 使用 CopyDirectoryExporter 为 Bridge 创建真实图片工作目录。
2. 清参数和打码产生处理后缓存图片。
3. PackageBuilder 创建最终 `all/post/cover` 对外文件。
4. ZIP 将最终图片写入压缩包。

### 13.3 硬链接

后续可以新增 HardlinkExporter：

- 仅支持同一文件系统。
- 创建速度快且不额外占用图片数据空间。
- 修改硬链接会修改原图，因此不作为默认 Bridge 物化方式。
- 必须由用户显式启用，并在导出报告中标记风险。

## 14. 图片处理配置

处理配置与分类、选图分离：

```yaml
image_processing:
  default_profile: pixiv_default

  profiles:
    pixiv_default:
      operations:
        - type: strip_metadata
        - type: mosaic
          options:
            provider: anr_plugin_auto_mosaics
```

任务默认使用 `default_profile`，只有需要不同处理方式时才在 `task.yaml` 覆盖。

`ImageOperation` 接口：

```text
ImageOperation
  type
  version
  validate(input, options, context)
  process(input, output, options, context)
```

第一阶段 Operation：

- `strip_metadata`：重编码图片并清除 PNG 参数。
- `mosaic`：通过适配器调用现有自动打码实现。

未来可以增加：

- `resize`
- `convert_jpeg`
- `watermark`
- `upscale`

## 15. 处理缓存

`all`、`post` 和 `cover` 使用相同处理配置时，每个 asset 只处理一次。

缓存键：

```text
asset 内容哈希
+ processing profile 配置哈希
+ Operation 类型、版本和参数
```

相同图片跨任务复用时可以直接命中缓存。缓存只保存私有处理中间产物，不作为最终对外目录。

## 16. PackageBuilder

任务配置示例：

```yaml
version: 1
task_id: 20260727_homura_foot
title: homura_foot

packages:
  directories: true
  zip:
    enabled: true
    targets:
      - all
```

输出：

```text
builds/<build_id>/
  build_manifest.json
  output/
    all/
    post/
    cover/
  archives/
    all.zip
```

规则：

- `all/post/cover` 中只包含处理后的真实图片。
- 不包含 prompt、seed、本地路径、节点 YAML 或 build manifest。
- 每个集合保留人工文件名 natural sort。
- cover 只独立复制，不改变 post 顺序。
- ZIP 为可选输出，目录始终生成。
- 每次构建使用独立 build id，不覆盖旧成功构建。

## 17. 构建前校验

开始任何图片处理前检查：

- 所有输入图片可读取。
- 快捷方式和符号链接目标存在。
- `post` 是 `all` 子集。
- `cover` 数量和归属合法。
- 单集合没有重复 asset。
- 输出文件名没有冲突。
- processing profile 存在。
- 所需 Operation 和外部插件可用。
- 输出路径可写。

节点信息缺失只产生 warning；文件损坏、集合关系错误、处理插件不可用和输出冲突阻止构建。

## 18. 任务状态

任务状态从当前数据推导，不在 `task.yaml` 手工维护：

```text
empty       candidates 为空
selecting   candidates 有图，但 all 为空
ready       all/post/cover 校验通过
building    正在构建
built       至少存在一个成功 build
invalid     输入损坏或集合关系错误
```

`build` 在 `all` 为空时拒绝执行并明确提示任务尚未完成二次筛选。

## 19. 构建失败与原子性

- 构建先写入临时目录。
- 全部成功后再原子形成正式 build 目录。
- 失败 build 写入状态和错误记录，但不生成正式 `output`。
- 已成功的处理缓存可以在重试时复用。
- 不修改原始图片。
- 不移动或删除 `selection` 中的人工排序结果。
- 不覆盖旧成功 build。

## 20. build_manifest

```yaml
build_id: "20260727_223000"
task_id: "20260727_homura_foot"
status: success
processing_profile: pixiv_default

selection:
  candidates: 120
  all: 46
  post: 18
  cover: 1

outputs:
  all: 46
  post: 18
  cover: 1

cache:
  hit: 12
  processed: 34

warnings:
  - asset sha256:... was also used by task 20260720_homura
```

manifest 位于 build 外层私有记录中，不复制进对外输出目录和 ZIP。

## 21. CLI 设计

```powershell
# 初始化公共 workspace
uv run python -m tags_machine_core publish init `
  --root G:\AI\publish

# 导入 NeeView 或其他输入，并自动分类、自动导出全部启用视图
uv run python -m tags_machine_core publish import `
  E:\NeeView41.3\Profile\Playlists\select_20260311.nvpls

# 手工重建分类及所有启用 Exporter
uv run python -m tags_machine_core publish classify
uv run python -m tags_machine_core publish export --all

# 创建投稿任务并导入候选
uv run python -m tags_machine_core publish create-task `
  20260727_homura_foot `
  --candidates E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls

# 追加或替换候选
uv run python -m tags_machine_core publish add-candidates TASK SOURCE
uv run python -m tags_machine_core publish replace-candidates TASK SOURCE

# 为 Bridge 生成真实图片工作目录
uv run python -m tags_machine_core publish materialize TASK `
  --set candidates `
  --exporter copy_directory `
  --output tasks/TASK/selection/all

# 校验和构建
uv run python -m tags_machine_core publish validate TASK
uv run python -m tags_machine_core publish build TASK
```

所有路径来自 workspace 配置、任务配置或命令参数，不写死 NeeView、设计库和投稿根目录。

## 22. 日志

日志分为 `trace / info / warning / error`。

业务级 info 示例：

```text
Imported 120 candidates: 112 new, 8 existing, 0 broken
Classified 120 assets into 37 leaf views
Export neev complete: updated=4 unchanged=33 removed=0
Task ready: all=46 post=18 cover=1
Build complete: processed=34 cache_hit=12
Output: G:\AI\publish\tasks\...\builds\...\output
```

默认非开发环境可以只显示 error，但命令最终摘要必须显示任务结果和输出路径。

## 23. 旧版功能映射

| 旧版能力 | 新模块 |
| --- | --- |
| NeeView 收藏列表 | `NeeViewPlaylistInput` |
| `new_lnk_character_type` | `ImportService + ImageNodeReaderRegistry + ClassificationViewBuilder` |
| 分类快捷方式树 | `ExportPlan + 可配置 ViewExporter` |
| 旧 `.lnk` 输出 | `WindowsShortcutExporter` |
| 人工二次筛选 | PublishTask `selection/all/post/cover` |
| Adobe Bridge 排序 | CopyDirectoryExporter + 文件名 natural sort |
| `process_files_lnk_to_origin` | InputAdapter / TaskSelectionResolver |
| `clear_png_info` | `StripMetadataOperation` |
| `process_mosaic` | `MosaicOperation` |
| `process_all` | `ImageProcessingPipeline + PackageBuilder` |

## 24. 业务验收

业务验收优先于接口单元测试。

### 24.1 NeeView 真实导入

使用真实 `.nvpls`：

- 导入项数量与 NeeView 列表一致。
- 保留列表顺序。
- 图片和 `.lnk` 项都能解析。
- 非法项显示明确路径和原因。
- 重复导入不会重复创建 Asset。

### 24.2 图片节点 Reader 验收

使用真实旧版图片和新版 core 图片：

- Core Reader 从 `tags_machine_core.nodes` 读取 artist、character、action 和 background。
- Core Reader 保留多个 character 及其 index。
- Legacy Reader 正确读取 artist、artist_path、character、action、topic 和 background。
- Legacy Reader 将 topic 输出为 action_group。
- 旧字段为字符串和 JSON 数组字符串时均能读取。
- 新版图片同时包含兼容字段时只使用 Core Reader 主结果。
- 新版结构损坏但旧兼容字段存在时 fallback 成功并记录 warning。
- 无节点信息图片进入 Catalog，但输出 unknown warning。
- 两种 Reader 的结果都能直接交给同一 ClassificationViewBuilder。

### 24.3 分类对比

选择固定真实图片样本，同时运行旧 `new_lnk_character_type` 与新分类链路：

- artist 一致。
- character 集合一致。
- action_group 一致或有明确 Resolver 差异说明。
- action 定位到相同原始节点。
- 多角色图片进入全部对应角色视图。

不要求目录命名细节与旧版完全相同，但业务分类必须一致。

### 24.4 Exporter 验收

- 自动导出全部非空叶子 `.nvpls`。
- 每个播放列表成员数量、路径和顺序与逻辑 ViewEntry 一致。
- 第二次无变更执行全部命中增量跳过。
- 修改一个分类后只更新相关视图。
- 显式启用 `.lnk` Exporter 后，固定样本可被 NeeView 正常打开。
- 支持环境下符号链接目标正确；不支持环境下给出明确错误。
- Exporter 清理不会删除人工未知文件。

### 24.5 投稿任务验收

- 从真实 NeeView 列表创建 candidates 快照。
- 修改原播放列表后任务 candidates 不自动变化。
- `add-candidates` 追加并去重。
- `replace-candidates` 不修改已有 all/post/cover。
- 同一图片可进入两个任务，并产生复用提示。
- Bridge 数字前缀重命名后，系统按 natural sort 读取正确顺序。

### 24.6 图片处理真实验收

使用同一组真实图片运行旧 `process_all` 与新处理链路：

- 原图均未修改。
- PNG 生成参数均已清除。
- 自动打码区域与旧版业务效果一致，细节像素不要求完全相同。
- `all/post/cover` 图片数量正确。
- `post` 和 `cover` 集合关系正确。
- 输出顺序与人工文件名一致。
- 对外目录和 ZIP 不包含私有 manifest 和生成参数。

### 24.7 缓存与失败验收

- 同任务重复构建命中处理缓存。
- 跨任务复用相同图片时命中处理缓存。
- 损坏图片、断开的快捷方式、非法播放列表和插件异常不会产生正式半成品。
- 修复问题后重新构建可以复用已成功缓存项。

## 25. 分阶段实现

### 阶段 1：Catalog、输入与自动视图导出

- Workspace 初始化与配置。
- SQLite Catalog。
- NeeView、目录、快捷方式 Input Adapter。
- ImageNodeReader 接口与 Registry。
- CoreImageNodeReader。
- LegacyImageNodeReader。
- ClassificationViewBuilder。
- ExportCoordinator。
- NeeViewPlaylistExporter。
- WindowsShortcutExporter。

### 阶段 2：投稿任务与人工选择

- 创建任务。
- candidates 快照。
- add/replace candidates。
- CopyDirectoryExporter。
- all/post/cover 扫描、顺序和关系校验。

### 阶段 3：图片处理与打包

- OperationRegistry。
- strip metadata。
- mosaic 适配器。
- 处理缓存。
- PackageBuilder 与可选 ZIP。

### 阶段 4：业务对比与稳定化

- 真实 NeeView 大列表导入。
- 与旧 `new_lnk_character_type` 分类对比。
- 与旧 `process_all` 图片处理对比。
- 大规模增量导出和缓存验证。

### 阶段 5：后续扩展

- SymbolicLinkExporter 和 HardlinkExporter。
- 前端素材筛选和任务管理。
- Bridge/XMP Input Adapter。
- Pixiv 投稿信息模板。
- 在平台规则和登录方案明确后评估辅助上传能力。
