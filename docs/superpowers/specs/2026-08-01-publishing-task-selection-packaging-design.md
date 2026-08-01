# Publishing 投稿任务、选择集合与打包设计

## 1. 文档状态

状态：已确认设计，等待进入实现计划。

已经确认的决策：

- `refresh` 和增量分类暂不纳入本阶段。
- 公共 workspace 与具体投稿任务分离。
- 图片复制进投稿任务后，任务目录成为独立快照。
- `candidates`、`all`、`post`、`cover` 使用统一的选择集合模型。
- `all`、`post`、`cover` 都支持 `.nvpls`、普通目录和快捷方式目录。
- candidates 导入后默认自动物化到 `selection/all/`。
- `selection/all/`、`selection/post/`、`selection/cover/` 只存放图片，不放会因人工修改而失真的 manifest。
- 导入历史写入 `selection/history/`；每次 build 根据当前图片目录生成不可变的选择快照。
- 文件名处理使用通用策略，不由具体 Exporter 重复实现。
- `strip_metadata` 默认开启。
- `mosaic` 是可选 Operation，没有插件时仍可完成构建。
- 集合关系默认只产生 warning，不阻止构建。
- build 始终生成目录输出，ZIP 作为可选附加输出。
- cover 不会自动移动到 post 第一张。

## 2. 背景

旧工作流由 NeeView、分类快捷方式、文件夹筛选、Adobe Bridge、`process_all` 和手工打包共同组成：

1. 在 NeeView 中收藏初选图片。
2. 按图片内嵌节点建立 artist、character、action_group、action 分类。
3. 对分类结果进行二次筛选。
4. 必要时用 Adobe Bridge 排序，并通过文件名固化顺序。
5. 复制图片、清除 PNG 参数、可选自动打码。
6. 生成 `all`、`post` 和 `cover` 投稿目录。

本阶段建立清晰的业务边界：公共 workspace 负责素材索引和分类，投稿任务负责一次具体投稿的人工选择、处理和交付。

## 3. 目标

- 在一个公共 workspace 下创建多个独立投稿任务。
- 从 NeeView 播放列表、目录或快捷方式目录导入 candidates。
- candidates 创建后自动复制为 `selection/all/`。
- 通过相同接口替换或追加 `all`、`post`、`cover`。
- 保留人工删除、重命名和 Adobe Bridge 排序结果。
- 统一生成处理后的 `all`、`post`、`cover` 输出。
- 清除最终图片中的 prompt、seed、本地路径等内部参数。
- 通过可选 Operation 接入自动打码。
- 支持处理缓存，避免相同图片重复处理。
- 每次构建生成独立 build，不覆盖历史成功构建。
- 记录候选快照、选择清单、处理配置和构建结果。
- 不修改、移动或删除公共 workspace 中的原始图片。

## 4. 非目标

- 不实现 Pixiv 自动登录或自动投稿。
- 不实现 `refresh` 和增量分类。
- 不替代 NeeView、文件夹筛选或 Adobe Bridge 的人工判断。
- 不把 Publishing 逻辑放回生图主链路。
- 不要求用户手工维护 Catalog 中的任务关系。
- 不强制要求 `post` 是 `all` 的子集。
- 不强制要求 `cover` 属于 `post`。
- 第一版不实现 resize、watermark、upscale 等 Operation。

## 5. 核心边界

### 5.1 公共 workspace

公共 workspace 是长期素材池，包含 Catalog、导入记录、分类视图和公共导出。

Catalog 用于找图、读取节点、分类和避免反复扫描大量图片。它不是投稿任务的构建事实来源。

### 5.2 投稿任务

投稿任务位于：

```text
<workspace>/tasks/<task_id>/
```

图片复制到任务的 `selection/` 后，后续构建只读取任务目录。原图移动、公共分类变化或原 NeeView 列表变化都不会影响已经创建的任务。

### 5.3 两者关系

```text
Catalog
  -> 找图、分类、导入 candidates
  -> 保存可选来源信息

PublishTask
  -> 保存任务自己的图片副本和顺序
  -> 处理和打包只使用任务目录
```

任务可以保存 `asset_id` 作为来源记录，但构建不要求 Catalog 在线，也不通过 `asset_id` 强制校验集合关系。

## 6. 总体架构

```text
输入
  NeeView .nvpls / 目录 / .lnk 目录
        |
        v
InputAdapter Registry
        |
        v
SelectionSet
        |
        +--> candidates.snapshot.json + candidates.nvpls
        |
        v
SelectionMaterializer
  复制真实图片
  使用 OutputNamePolicy
        |
        v
selection/all | post | cover
        |
        v
CurrentSelectionScanner
        |
        v
BuildSelectionSnapshot
        |
        v
ImageProcessingPipeline
  strip_metadata
  optional mosaic
        |
        v
PackageBuilder
        |
        v
builds/<build_id>/output
```

组件职责：

| 组件 | 职责 | 不负责 |
| --- | --- | --- |
| `InputAdapter` | 读取 `.nvpls`、目录、快捷方式并输出统一 `SelectionSet` | 投稿处理规则 |
| `TaskRepository` | 创建任务、保存配置和候选快照 | 图片处理 |
| `SelectionMaterializer` | 把选择集合复制到任务目录 | 最终打包 |
| `OutputNamePolicy` | 清理文件名、加顺序前缀、处理重名 | 图片筛选 |
| `CurrentSelectionScanner` | 扫描任务选择目录当前的图片文件并形成构建输入 | 读取公共 Catalog |
| `BuildSelectionSnapshot` | 固化本次 build 的选择顺序、文件名和来源记录 | 修改人工选择目录 |
| `ImageProcessingPipeline` | 执行清参数和可选打码 | 人工选图 |
| `PackageBuilder` | 生成独立 build、目录和 ZIP | 修改原图 |
| `Catalog` | 公共素材索引和分类 | 任务构建的唯一事实来源 |

## 7. 任务目录

```text
<workspace>/
  workspace/
    workspace.yaml
    catalog.sqlite
    imports/
    exports/
    cache/
    state/

  tasks/
    <task_id>/
      task.yaml
      selection/
        candidates.snapshot.json
        candidates.nvpls
        history/
          20260801T223000Z-all-import.json
          20260801T223500Z-post-import.json
        all/
          0001_original_a.png
          0002_original_b.png
        post/
          0001_original_a.png
        cover/
          0001_original_a.png
      builds/
        <build_id>/
          selection_snapshot.json
          build_manifest.json
          output/
            all/
            post/
            cover/
          archives/
            all.zip
            post.zip
            cover.zip
```

`selection/` 是人工筛选工作区；三个选择目录中的图片文件是当前事实来源。`history/` 只记录导入动作和导入时的来源，不参与后续构建输入。
`builds/` 是系统生成的交付结果；每次构建先从当前选择目录生成不可变的 `selection_snapshot.json`，再处理该快照。构建不会覆盖已有 build。

## 8. 统一输入和选择集合

### 8.1 输入格式

`candidates`、`all`、`post`、`cover` 都使用已有 InputAdapter Registry：

- `neev_playlist`
- `directory`
- `shortcut`

输入适配器统一输出 `SelectionSet`，保留输入顺序和源路径信息：

```yaml
source_type: neev_playlist
source_ref: E:/NeeView41.3/Profile/Playlists/select.nvpls
items:
  - source_path: G:/ai_auto/a.png
    resolved_path: G:/ai_auto/a.png
    source_order: 0
    display_name: a.png
    warnings: []
```

### 8.2 candidates

创建任务时可以不提供 candidates，也可以直接提供任意支持的输入。

提供 candidates 时：

1. 读取输入并去除同一内容的重复项。
2. 保存不可变 `candidates.snapshot.json`。
3. 生成保留顺序的 `candidates.nvpls`。
4. 自动把 candidates 物化到 `selection/all/`。
5. 把本次导入记录写入 `selection/history/`。

原始播放列表后续变化不会自动改变任务。

### 8.3 all、post、cover

三个集合都支持相同输入：

```text
all   <- nvpls / directory / shortcut directory
post  <- nvpls / directory / shortcut directory
cover <- nvpls / directory / shortcut directory
```

操作模式：

- `replace`：替换目标集合，不修改其他集合。
- `append`：追加到目标集合，跳过同一内容的重复图片。

导入时会把输入解析为 `SelectionSet`，再使用统一的 `OutputNamePolicy` 物化到目标目录。
目标目录只保留图片文件；导入来源、解析警告和当时的顺序写入 `selection/history/`。
导入集合不会修改公共原图。

人工筛选规则：

- 用户可以直接删除、重命名图片，也可以使用 Adobe Bridge 调整文件名顺序。
- 构建时扫描目标目录当前存在的受支持图片文件。
- 当前文件名和自然排序结果优先于历史导入记录。
- 已删除的图片不会因为 history 或候选快照而重新出现。
- 已重命名的图片按新文件名参与构建，不恢复导入时文件名。
- `selection/history/` 不放入 `all`、`post`、`cover` 的对外输出。

### 8.4 构建时选择快照

`CurrentSelectionScanner` 在每次 build 开始时分别扫描 `all/`、`post/`、`cover/`，生成：

```json
{
  "schema": "publishing-workspace.selection-snapshot/v1",
  "set": "post",
  "items": [
    {
      "index": 1,
      "filename": "0001_original_a.png",
      "path": "selection/post/0001_original_a.png",
      "asset_id": null
    }
  ]
}
```

快照至少记录集合名、文件名、相对路径和构建顺序；如果任务文件保留了来源 `asset_id`，可以同时记录，但不依赖它进行集合关系强校验。
快照写入 `builds/<build_id>/selection_snapshot.json`，只服务于本次 build 的复现和审计。构建过程不再次扫描 selection 目录，也不读取 Catalog。

## 9. 通用文件名策略

### 9.1 默认规则

物化真实图片时使用共享 `OutputNamePolicy`：

```text
<顺序前缀>_<清理后的原文件名>
```

示例：

```text
0001_original_a.png
0002_original_b.png
0003_original_b_2.png
```

规则：

- `.nvpls` 使用 Items 顺序。
- 目录输入使用自然排序。
- 保留原始扩展名。
- 替换 Windows 非法字符。
- 清理尾部空格和句点。
- 文件名过长时截断主体并保留扩展名。
- 清理后重名时添加确定性数字后缀。
- 不覆盖已有文件。

### 9.2 Exporter 使用方式

- 图片物化阶段使用 `OutputNamePolicy` 生成初始真实文件名；人工之后的重命名属于用户选择结果，PackageBuilder 不再次编号或覆盖。
- Windows Shortcut Exporter 使用同一策略生成 `.lnk` 名称。
- NeeView Playlist Exporter 不修改原图文件名，只保存路径和顺序。
- PackageBuilder 保留 selection 中已经确定的文件名，不再次编号。

因此，文件名策略是导出/物化基础设施的一部分，但不是每个输出阶段都强制重新执行。需要生成新文件名的 Exporter 调用它；需要保留人工顺序和命名的 PackageBuilder 直接使用构建快照中的文件名。

## 10. 任务配置

```yaml
version: 1
task_id: 20260801_homura_foot
title: homura foot

processing:
  profile: pixiv_default

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

任务状态从当前文件和构建记录推导：

```text
empty       candidates 和 all 都为空
selecting   all 为空或仍在人工筛选
ready       至少 all 有可读取图片
building    存在进行中的 build
built       存在成功 build
invalid     任务文件或处理配置不可用
```

## 11. 图片处理

### 11.1 Operation 接口

```text
ImageOperation
  type
  version
  validate(input, options, context)
  process(input, output, options, context)
```

### 11.2 默认 Operation

`strip_metadata` 默认开启：

- 读取图片像素并重新写出。
- 清除 prompt、negative prompt、seed、本地路径等内部参数。
- 不修改任务 selection 或公共原图。

`mosaic` 默认关闭：

- 配置 `anr_plugin_auto_mosaics` 后才执行。
- 通过 Adapter 调用插件。
- profile 显式要求打码但插件不可用时，构建失败并说明原因。
- Operation 为 disabled 时直接跳过。

### 11.3 处理缓存

缓存键：

```text
输入图片内容哈希
+ processing profile 哈希
+ Operation 类型、版本和参数
```

相同输入和配置只处理一次。`all`、`post`、`cover` 包含同一图片时共享处理结果。

## 12. PackageBuilder

### 12.1 输出

```text
builds/<build_id>/
  selection_snapshot.json
  build_manifest.json
  output/
    all/
    post/
    cover/
  archives/
    all.zip
    post.zip
    cover.zip
```

目录输出始终生成；`packages.directories.enabled` 仅用于未来允许关闭目录输出时的配置兼容，第一版固定要求为 `true`。
ZIP 是可选输出。对外目录和 ZIP 只包含处理后的真实图片，不包含 prompt、seed、本地路径、节点信息、Catalog 数据、history 或 manifest。

### 12.2 原子性

1. 创建临时 build 目录。
2. 校验选择集合和处理配置。
3. 处理图片并生成输出。
4. 生成选择快照、manifest 和可选 ZIP。
5. 全部成功后形成正式 build。

失败时不生成半成品正式输出，不覆盖历史成功 build，也不修改 selection 和原图。

### 12.3 Manifest

```yaml
schema: publishing-workspace.build/v1
build_id: 20260801_223000
task_id: 20260801_homura_foot
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

processing_result:
  cache_hit: 12
  processed: 34
  skipped_mosaic: 34

warnings: []
errors: []
```

## 13. 校验策略

默认只记录 warning：

- `post` 中有图片不在 `all`。
- `cover` 中有图片不在 `post`。
- 同一图片在集合中重复出现。
- 文件名清理后发生重名并被自动调整。

以下问题阻止构建：

- 图片不存在或无法读取。
- 输出目录不可写。
- profile 要求的 Operation 不可用。
- 无法生成唯一输出文件名。
- 构建过程出现未处理错误。

## 14. CLI

```powershell
# 创建空任务
uv run publishing-workspace task create G:\ai_publish 20260801_homura_foot

# 创建任务并导入 candidates，自动复制到 all
uv run publishing-workspace task create G:\ai_publish 20260801_homura_foot `
  --candidates E:\NeeView41.3\Profile\Playlists\homura_foot.nvpls

# 替换 all
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot `
  --set all --source E:\NeeView41.3\Profile\Playlists\all.nvpls --mode replace

# 导入 post 或 cover
uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot `
  --set post --source E:\NeeView41.3\Profile\Playlists\post.nvpls --mode replace

uv run publishing-workspace task import-selection G:\ai_publish 20260801_homura_foot `
  --set cover --source E:\NeeView41.3\Profile\Playlists\cover.nvpls --mode replace

# 查看任务
uv run publishing-workspace task status G:\ai_publish 20260801_homura_foot

# 构建投稿包
uv run publishing-workspace task build G:\ai_publish 20260801_homura_foot
```

以上命令名作为第一版 CLI 固定，不在实现阶段重新发明入口。实现可以增加别名，但不能让 `candidates`、`all`、`post`、`cover` 走不同的导入协议。

## 15. 验收标准

### 15.1 任务和 candidates

- 可以创建空任务。
- 可以从真实 `.nvpls` 创建任务。
- 保存 candidates 快照和 `candidates.nvpls`。
- 保存 candidates 导入 history，且 history 不参与构建输入。
- candidates 自动复制到 `selection/all/`。
- 原播放列表后续变化不会改变任务。
- 重复导入不会覆盖已有文件。

### 15.2 选择集合

- `all`、`post`、`cover` 都支持 `.nvpls`、目录和快捷方式目录。
- replace 不影响其他集合。
- append 不产生同内容重复副本。
- 人工重命名后按文件名自然排序。
- 人工删除后不会被 history 或候选快照恢复。
- 构建前生成不可变 `selection_snapshot.json`，构建期间只使用该快照。
- 目录和 NeeView 输入经过同一 SelectionSet 链路。

### 15.3 构建和处理

- 默认清除图片 PNG 参数。
- 未配置 mosaic 插件时可以成功构建。
- 配置并启用 mosaic 时通过插件处理。
- `all/post/cover` 输出数量与选择集合一致。
- 相同图片和相同 profile 只处理一次。
- 构建失败不修改原图，不覆盖历史成功 build。
- ZIP 不包含 prompt、seed、本地路径或 manifest。
- `selection/all/`、`selection/post/`、`selection/cover/` 中不出现 `selection.json` 等内部 manifest。
- 目录输出始终生成，ZIP 关闭时仍能取得完整 `all/post/cover` 目录。

### 15.4 真实业务验收

使用真实 NeeView 收藏列表：

1. 创建任务并导入 candidates。
2. 确认 candidates 物化到 `selection/all/`。
3. 人工删除图片并重命名数字前缀。
4. 使用目录和 `.nvpls` 分别导入 `post`、`cover`。
5. 在 mosaic 关闭和开启两种配置下构建。
6. 检查图片参数、图片数量、顺序、ZIP 内容和 manifest。
7. 确认原图和公共 workspace 没有被修改。

## 16. 后续扩展

- `refresh` 和增量同步。
- Pixiv 投稿信息和标签记录。
- resize、watermark、upscale Operation。
- 符号链接、硬链接等任务物化方式。
- 前端任务管理和构建历史。
- 可配置的 warning/strict 校验模式。
