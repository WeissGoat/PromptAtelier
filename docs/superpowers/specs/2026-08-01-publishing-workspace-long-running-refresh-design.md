# Publishing Workspace 长期运行与增量刷新设计

## 1. 背景

Publishing Workspace 已经从 `tags_machine_core` 中拆分为独立工具，当前支持：

- NeeView `.nvpls`、普通目录和 Windows 快捷方式输入；
- Core 与 Legacy 两种图片节点 Reader；
- ActionGroupManifestEnricher；
- SQLite 公共 Catalog；
- `artist / character / action_group / action` 分类视图；
- NeeView 与 Windows Shortcut Exporter；
- 基于视图内容 hash 的幂等导出；
- 缺失节点使用 `unknown` 的标准节点投影。

真实输入：

```text
E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls
```

真实测试结果：

```text
NeeView 项目数          10010
成功导入                 9987
失败                       23
Reader legacy            8975
Reader core              1001
Reader unknown             11
分类视图                 4626
包含 unknown 的视图        25
视图成员                10157
首次导入耗时              约 13 分钟
完整分类耗时              约 86 秒
分类计划文件              约 5.5 MB
```

23 个失败文件全部是 0 字节 PNG，属于源文件损坏或未完成同步，不是 Reader 兼容问题。

当前系统已经能完成一次性导入和导出，但“导入一次后长期维护”的能力尚未形成完整设计：

- 导入过程中只有最终汇总，没有阶段进度；
- 整份列表由一个长事务处理，中断后不能从中间恢复；
- 已有路径缓存可以避免部分重复解析，但没有显式导入计划和复用统计；
- 失败项只存在于导入快照，没有持久化问题队列和重试入口；
- 分类每次重新加载整个 Catalog，并重新生成完整计划；
- Exporter 虽然能跳过未变化文件，但仍要先构建和遍历完整分类计划；
- 一次导入运行、一次分类计划和一次 refresh 没有统一的持久化状态。

## 2. 目标

本设计的核心目标是让 `G:\ai_publish` 成为可以每日长期运行的公共 Publishing Workspace。

具体目标：

1. 重复输入相同列表时，未变化图片不重新哈希、不重新打开、不重新执行 Reader。
2. 新列表或变化文件只处理新增、变化和需要重试的项目。
3. 导入过程中按批次提交，中断后可从最后一个未完成项目恢复。
4. 失败项进入持久化问题队列，可以查看、忽略和单独重试。
5. 导入、分类和导出具有清晰的阶段进度、计数和最终报告。
6. 分类只计算新 Asset 或配置变化导致的必要重建。
7. 导出只处理受影响视图，完整一致性检查仍可显式执行。
8. 默认采用追加语义，不因某次列表缺少图片而删除历史 Catalog 资产。
9. 保持现有 Reader、Enricher、Catalog Asset 和 Exporter 边界稳定。
10. 业务验收以真实一万项 NeeView 列表为核心，单元测试只作为状态机和迁移保护。

## 3. 非目标

- 本次不实现后台 daemon、消息队列或多 worker 并发执行。
- 本次不实现 Web UI。
- 本次不实现 Pixiv 自动投稿。
- 本次不实现投稿任务的 `all / post / cover` 二次筛选和图片处理。
- 本次不自动删除、移动、重命名或复制原始图片。
- 本次不默认对全部未变化图片重新计算 SHA-256。
- 本次不实现自动 Catalog prune；删除和同步必须是未来的显式命令。
- 本次不改变 Core 或 Legacy PNG 节点格式。
- 本次不改变 `unknown` 节点投影规则。

## 4. 方案选择

### 4.1 方案 A：在现有导入循环上增量修补

在 `CatalogRepository.import_selection()` 中增加进度回调、批次提交和失败 JSON。

优点：改动小。

缺点：运行状态仍分散在快照、Catalog 和外部文件中，中断恢复和未来 refresh 会继续向 Repository 堆叠业务逻辑。

### 4.2 方案 B：持久化 ImportRun、逐项导入计划和 ProblemQueue

将输入、计划、执行和问题管理拆成独立组件。每个输入项先持久化决策，再按批次执行。

优点：

- 支持明确的复用、解析和失败统计；
- 支持中断续跑；
- 支持失败项单独重试；
- 可自然扩展为每日 refresh；
- Reader、Catalog 和 Exporter 无需感知运行状态。

缺点：需要 Catalog schema 升级和新的运行状态组件。

### 4.3 方案 C：后台任务队列与常驻 worker

CLI 只创建 Job，由后台进程执行导入、分类和导出。

优点：适合未来服务器和 Web UI。

缺点：引入 worker 生命周期、并发、部署和监控复杂度，当前阶段过重。

### 4.4 决策

采用方案 B。

方案 B 解决当前真实测试暴露的问题，同时为未来方案 C 提供稳定的运行模型。当前仍使用同步 CLI 进程执行，不引入后台 worker。

## 5. 核心原则

### 5.1 Catalog 与运行状态分离

`assets / asset_paths / asset_nodes` 表示长期资产事实；`imports / import_items / import_problems` 表示一次运行的来源、决策和处理结果。

一次 Run 失败或重试不能污染已成功存在的 Asset。

### 5.2 先计划，再执行

ImportPlanner 只做轻量路径检查和缓存判断，不打开图片。ImportExecutor 只执行计划中需要处理的项目。

### 5.3 配置相关缓存可失效

分类成员缓存由分类配置和 Builder 版本共同标识。配置变化后完整重建新 profile，不修改历史原始节点。

### 5.4 默认追加，删除显式化

某次 NeeView 列表缺少旧图片，不表示用户要求从 Catalog 删除旧资产。默认 refresh 只追加或更新路径状态。

### 5.5 业务结果优先

真实列表的成功数量、问题数量、分类视图、导出结果、运行时间和中断恢复结果是主要验收依据。

## 6. 总体架构

```text
外部输入
  NeeView / Directory / Shortcut
            |
            v
       InputAdapter
            |
            v
    SelectionSnapshot
            |
            v
       ImportPlanner
            |
            v
 ImportRun + ImportRunItems
            |
            v
       ImportExecutor
       /      |       \
      v       v        v
 AssetCatalog ProblemQueue ProgressReporter
      |
      v
 ClassificationProfileRepository
      |
      v
 ClassificationDelta
      |
      v
 ViewExportCoordinator
```

## 7. 组件职责

### 7.1 InputAdapter

保持现有职责：把不同输入转换成统一 `SelectionSet`。

第一版继续整体读取 NeeView JSON。10010 项不构成明显内存瓶颈，不为此引入流式 JSON 依赖。若未来列表规模显著扩大，再通过性能数据决定是否引入流式解析。

### 7.2 SelectionSnapshot

保存：

- 输入类型；
- 输入来源；
- 输入原始顺序；
- 路径解析结果；
- 输入级 warning；
- 来源文件指纹。

Snapshot 创建后不可变。运行中的决策和状态写入数据库，不反复重写大 JSON。

来源指纹只用于审计和识别输入版本：

- NeeView：规范化播放列表路径、文件大小、修改时间和播放列表内容 SHA-256；
- Directory：规范化目录路径、recursive 选项和允许的图片扩展名；
- Shortcut：规范化快捷方式路径、文件大小和修改时间。

来源指纹不能直接跳过逐项文件状态检查。即使 NeeView 播放列表本身没有变化，其中引用的图片仍可能被修复、替换或删除。

### 7.3 ImportPlanner

逐项生成以下决策之一：

```text
reuse_path
parse
missing_path
empty_file
hold_problem
```

Planner 不计算图片 SHA，不调用 Pillow，不调用 Reader。

### 7.4 ImportExecutor

按 `source_order` 执行计划：

- `reuse_path`：直接关联已有 Asset；
- `parse`：计算 SHA，复用已有内容或创建新 Asset；
- `missing_path / empty_file / hold_problem`：记录状态，不进入图片解析；
- 每批完成后提交数据库并更新 Run 计数。

### 7.5 ProblemQueue

持久化失败原因、文件状态、尝试次数和解决状态。问题记录不替代日志，日志也不替代问题记录。

### 7.6 ProgressReporter

消费统一进度事件并输出 CLI 日志。业务组件只上报事件，不负责格式化日志。

### 7.7 ClassificationProfileRepository

保存某一套分类配置下 Asset 到 View 的成员关系。重复 Asset 不重新运行 ClassificationViewBuilder。

### 7.8 RefreshService

编排：

```text
ImportRun
  -> ImportPlanner
  -> ImportExecutor
  -> ClassificationDelta
  -> ViewExportCoordinator
```

RefreshService 不实现 Reader、Catalog 或 Exporter 细节。

## 8. 数据模型

Catalog schema 从 v1 升级到 v2。

### 8.1 imports

现有 `imports` 表升级为持久化 ImportRun：

```text
import_id              TEXT PRIMARY KEY
source_type            TEXT NOT NULL
source_ref             TEXT NOT NULL
source_fingerprint     TEXT
mode                   TEXT NOT NULL
status                 TEXT NOT NULL
pipeline_stage         TEXT NOT NULL
total_items            INTEGER NOT NULL DEFAULT 0
planned_items          INTEGER NOT NULL DEFAULT 0
processed_items        INTEGER NOT NULL DEFAULT 0
reused_path_items      INTEGER NOT NULL DEFAULT 0
reused_content_items   INTEGER NOT NULL DEFAULT 0
parsed_new_items       INTEGER NOT NULL DEFAULT 0
missing_items          INTEGER NOT NULL DEFAULT 0
failed_items           INTEGER NOT NULL DEFAULT 0
held_problem_items     INTEGER NOT NULL DEFAULT 0
warnings_json          TEXT NOT NULL
error_json             TEXT
created_at             TEXT NOT NULL
started_at             TEXT
updated_at             TEXT NOT NULL
completed_at           TEXT
```

`mode` 第一版支持：

```text
import
refresh
retry_problems
legacy
```

### 8.2 import_items

```text
import_id              TEXT NOT NULL
source_order           INTEGER NOT NULL
source_path            TEXT NOT NULL
resolved_path          TEXT
display_name           TEXT NOT NULL
observed_size          INTEGER
observed_modified_ns   INTEGER
decision               TEXT NOT NULL
status                 TEXT NOT NULL
attempts               INTEGER NOT NULL DEFAULT 0
asset_id               TEXT
problem_id             TEXT
warnings_json          TEXT NOT NULL
created_at             TEXT NOT NULL
updated_at             TEXT NOT NULL
PRIMARY KEY (import_id, source_order)
```

`decision`：

```text
pending
reuse_path
parse
missing_path
empty_file
hold_problem
legacy
```

`status`：

```text
pending
planned
processing
reused_path
reused_content
parsed_new
missing
failed
held_problem
```

### 8.3 import_problems

```text
problem_id             TEXT PRIMARY KEY
import_id              TEXT NOT NULL
source_order           INTEGER NOT NULL
path_key               TEXT
source_path            TEXT NOT NULL
error_code             TEXT NOT NULL
message                TEXT NOT NULL
observed_size          INTEGER
observed_modified_ns   INTEGER
status                 TEXT NOT NULL
attempts               INTEGER NOT NULL DEFAULT 1
created_at             TEXT NOT NULL
updated_at             TEXT NOT NULL
resolved_at            TEXT
```

问题状态：

```text
open
resolved
ignored
```

错误类型：

```text
missing_path
empty_file
unreadable_image
unsupported_format
metadata_read_error
shortcut_resolve_error
legacy_failure
```

Reader 无法识别节点但图片本身有效，不创建问题，仍以 `reader=unknown` 进入 Catalog。

### 8.4 workspace_locks

```text
lock_name              TEXT PRIMARY KEY
owner_run_id           TEXT NOT NULL
owner_token            TEXT NOT NULL
lease_expires_at       TEXT NOT NULL
updated_at             TEXT NOT NULL
```

第一版只使用写入锁：

```text
publishing_import
```

### 8.5 classification_profiles

```text
profile_hash           TEXT PRIMARY KEY
hierarchy_json         TEXT NOT NULL
missing_value          TEXT NOT NULL
skip_missing           INTEGER NOT NULL
builder_version        TEXT NOT NULL
created_at             TEXT NOT NULL
last_used_at           TEXT NOT NULL
```

### 8.6 asset_view_memberships

```text
profile_hash           TEXT NOT NULL
asset_id               TEXT NOT NULL
view_key               TEXT NOT NULL
view_path_json         TEXT NOT NULL
created_at             TEXT NOT NULL
PRIMARY KEY (profile_hash, asset_id, view_key)
```

## 9. ImportRun 状态机

CLI 在调用 InputAdapter 前先创建最小 ImportRun，记录 source_type、source_ref 和 mode。这样输入 JSON 损坏或 InputAdapter 失败时仍有可查询的 failed Run。SelectionSnapshot 成功创建后再补充来源指纹和 total_items。

InputAdapter 成功后，在一个短事务中把 SelectionSnapshot 的全部项目写入 import_items，初始 `decision=pending`、`status=pending`。之后 Planner 分批读取 pending 项并写入正式决策。这样 planning 阶段中断后可以直接从数据库继续，不重新调用 InputAdapter，也不需要在运行中反复写大 JSON。

```text
created
  -> scanning
  -> planned
  -> running
  -> completed
  -> completed_with_errors

created/scanning/planned/running
  -> interrupted
  -> failed
```

`pipeline_stage` 独立记录：

```text
input
planning
execution
classification
export
completed
```

这样 `refresh` 在导入完成后、分类或导出中断时，可以继续后续阶段而不重新导入。

状态规则：

- 单项图片失败不会将 Run 标记为 `failed`；
- 存在 open problem 但其他项目完成时为 `completed_with_errors`；
- 数据库不可写、输入 JSON 无法解析、配置非法等致命错误使 Run 进入 `failed`；
- 捕获 Ctrl+C 后进入 `interrupted`；
- 进程崩溃时状态可能保留为 `running`，租约过期后允许 `resume` 接管。

## 10. 运行锁

- 同一 workspace 同时只允许一个写入型 ImportRun。
- Run 获取锁后生成随机 `owner_token`。
- 每完成一个批次刷新租约。
- 正常完成或受控中断时释放锁。
- 租约未过期时，其他写入命令拒绝执行并显示活动 run_id。
- 租约过期后，只允许 `resume` 或显式接管命令重新获得锁。
- `status`、`problems` 等只读命令不获取写入锁。

## 11. 增量判定

### 11.1 来源指纹与项目指纹

`source_fingerprint` 用于运行历史和输入版本识别；真正决定图片是否复用的是项目级指纹：

```text
normalized path_key
+ observed_size
+ observed_modified_ns
```

重复 refresh 仍会对列表中每个项目执行路径存在性检查和 `stat`。这一步是轻量扫描，也是自动发现图片被修复或替换的必要条件。

### 11.2 项目决策

每个输入项按以下顺序规划：

```text
1. 解析路径
2. 路径不存在
      -> missing_path
3. 读取 size / modified_ns
4. size == 0
      -> empty_file
5. asset_paths 命中 path_key + size + modified_ns
      -> reuse_path
6. 相同路径指纹存在 open problem 且未要求强制重试
      -> hold_problem
7. 其他情况
      -> parse
```

Planner 完成一个批次后把对应 import_items 从 `pending` 更新为 `planned`，并保存正式 decision、observed_size 和 observed_modified_ns。

`parse` 执行：

```text
计算 SHA-256
  |
  +-- assets 已存在 -> reuse_content，补充或更新 asset_paths
  |
  +-- assets 不存在 -> Pillow + PNG metadata + Reader + Enricher -> parsed_new
```

未变化文件不重新计算 SHA。未来通过显式 `verify-assets` 做内容级完整校验。

## 12. 批次事务与恢复

默认批次大小：`200`。

每批流程：

1. 读取下一批 `planned` 项；
2. 将单项标记为 `processing`；
3. 执行复用或解析；
4. 写入 Asset、路径、问题和单项结果；
5. 更新 imports 计数和 `updated_at`；
6. 刷新运行租约；
7. 提交事务。

恢复规则：

- planning 阶段从最小 `decision=pending` 的 source_order 继续；
- `reused_path / reused_content / parsed_new / missing / failed / held_problem` 不重复执行；
- 残留 `processing` 项在恢复时重置为 `planned`；
- 从最小未完成 `source_order` 继续；
- 同一个 ImportRun 不重新调用 InputAdapter，不重新创建 SelectionSnapshot；
- 最终顺序与不中断运行一致。

`--strict` 的语义：单项失败后停止当前 Run，但保留已提交批次，并将 Run 标记为 `interrupted`。修复问题后可继续 `resume`。

## 13. 问题队列与重试

默认规则：

- 文件大小或修改时间改变：自动重试；
- 缺失路径重新出现：自动重试；
- 文件状态未变化：保持 open problem，并在新 Run 中生成 `hold_problem`；
- `--retry-failed`：强制重试本次输入关联的 open problem；
- `retry-problems`：按 run_id、error_code 或全部 open problem 创建新的 retry Run；
- 重试成功后旧 problem 标记为 `resolved`，保留历史；
- `ignored` problem 不自动重试，除非显式包含 ignored。

零字节文件在 Planner 阶段直接归类为 `empty_file`，不交给 Pillow 或 Reader。

## 14. 进度事件与日志

统一事件：

```text
input_started
input_completed
planning_started
planning_progress
planning_completed
execution_started
execution_progress
execution_completed
classification_started
classification_progress
classification_completed
export_started
export_progress
export_completed
snapshot_written
run_completed
run_failed
```

日志级别：

- `trace`：单项路径、决策、缓存、Reader 和异常详情；
- `info`：阶段开始、阶段进度、速率、耗时和最终统计；
- `warning`：新问题、自动恢复、旧问题保持；
- `error`：Run 无法继续的致命错误。

`info` 进度按以下条件触发：

```text
每处理 200 项
或距离上一条进度超过 5 秒
```

示例：

```text
Import planning 2400/10010 reused=2180 parse=197 missing=0 held=23 elapsed=8.2s
Import execution 600/197 new=140 content_reuse=54 failed=3 rate=18.4/s
```

无论日志级别如何，CLI 最终向 stdout 输出结构化结果。

运行状态只保存在 SQLite。完成后原子写入一次 `workspace/imports/<run_id>.json`，不在运行中反复重写一万项 JSON。

## 15. CLI

### 15.1 import

```powershell
uv run publishing-workspace import `
  G:\ai_publish `
  E:\NeeView41.3\Profile\Playlists\合_20260801.nvpls `
  --log-level info
```

只完成导入，不自动分类和导出。

### 15.2 refresh

```powershell
uv run publishing-workspace refresh `
  G:\ai_publish `
  E:\NeeView41.3\Profile\Playlists\合_20260801.nvpls `
  --exporter neev `
  --log-level info
```

依次完成导入、增量分类和增量导出。未来每日定时任务使用该命令。

### 15.3 status

```powershell
publishing-workspace status G:\ai_publish
publishing-workspace status G:\ai_publish <run_id>
```

无 run_id 时显示活动 Run 或最近 Run。

### 15.4 resume

```powershell
publishing-workspace resume G:\ai_publish <run_id>
```

根据 `pipeline_stage` 继续导入、分类或导出。

### 15.5 problems

```powershell
publishing-workspace problems G:\ai_publish --status open
publishing-workspace problems G:\ai_publish --run-id <run_id>
publishing-workspace problems G:\ai_publish --code empty_file
```

### 15.6 retry-problems

```powershell
publishing-workspace retry-problems G:\ai_publish --run-id <run_id>
publishing-workspace retry-problems G:\ai_publish --code unreadable_image
```

### 15.7 full consistency

```powershell
publishing-workspace classify G:\ai_publish --full
publishing-workspace export G:\ai_publish --full
```

完整模式忽略分类 Delta，重新检查全部资产和视图。

## 16. 增量分类

`profile_hash` 组成：

```text
classification.hierarchy
+ classification.missing_value
+ classification.skip_missing
+ ClassificationViewBuilder.builder_version
```

分类流程：

1. 计算当前 profile_hash；
2. profile 不存在时完整构建；
3. profile 存在时只查询没有 membership 的新 Asset；
4. 为新 Asset 运行现有 `node_projection + ClassificationViewBuilder` 规则；
5. 持久化 Asset 到 View 的成员关系；
6. 生成 `ClassificationDelta`。

`ClassificationDelta`：

```text
profile_hash
full_rebuild
new_asset_ids
affected_view_keys
```

完全相同列表再次 refresh：

```text
new_asset_ids = []
affected_view_keys = []
classification = unchanged
```

此时不重新加载全部 Asset，不重写完整分类计划文件。

`asset_view_memberships` 只保存分类关系，不复制图片路径、显示名称或来源顺序。构建公共 Catalog 视图时：

- 图片路径继续使用 Catalog 当前可用的 preferred path；
- 成员顺序继续使用该 Asset 在历史 import_items 中首次出现的稳定顺序；
- import_id scoped 视图使用对应 import_items 的 source_order 和 display_name；
- 路径或显示名称变化不会要求重建分类 membership，只会影响最终 ViewItem 投影和相关视图 hash。

配置或 builder_version 变化时，创建新 profile 并完整构建一次。旧 profile 可在后续维护命令中清理，不在运行中删除。

## 17. 增量导出

当前 `export_states` 继续保存每个视图的内容 hash 和输出路径。

增量 refresh 只把 `affected_view_keys` 交给 ViewExportCoordinator：

- 新视图：写入；
- 已存在但成员变化：重写；
- 未受影响视图：不读取、不计算 hash；
- 默认追加模式没有 removed 视图；
- 未来显式 prune/sync 才产生 removed。

`--full` 仍遍历所有当前视图，并使用现有 export state 做完整一致性校验。

## 18. 运行结果

示例：

```json
{
  "run_id": "20260801_001",
  "status": "completed_with_errors",
  "import": {
    "total": 10010,
    "reused_path": 9780,
    "reused_content": 12,
    "parsed_new": 175,
    "missing": 0,
    "failed": 0,
    "held_problem": 23
  },
  "classification": {
    "mode": "incremental",
    "new_assets": 175,
    "affected_views": 84
  },
  "export": {
    "written": 84,
    "skipped": 0,
    "removed": 0
  },
  "open_problems": 23,
  "duration_seconds": 42.8
}
```

## 19. 代码模块调整

建议结构：

```text
src/publishing_workspace/
  service.py
  models.py
  catalog/
    repository.py
    schema.py
    migrations.py
  importing/
    __init__.py
    models.py
    repository.py
    planner.py
    executor.py
    progress.py
  problems/
    __init__.py
    repository.py
    service.py
  classification/
    __init__.py
    profile.py
    repository.py
    delta.py
  refresh/
    __init__.py
    service.py
```

调整原则：

- `CatalogRepository` 只负责 Asset、路径和节点事实；
- 现有 `import_selection()` 的编排职责迁入 importing；
- `PublishingService` 作为 CLI 使用的薄 Facade；
- Reader、Enricher、ViewBuilder、Exporter 接口保持不变；
- 不在 CLI 中实现业务状态机。

## 20. Schema 迁移

迁移前使用 SQLite Backup API 创建：

```text
workspace/backups/catalog-v1-<timestamp>.sqlite
```

不直接复制正在使用的 WAL 数据库文件。

迁移步骤：

1. 检查 schema_id 和 version；
2. 创建一致性备份；
3. 开启事务；
4. 升级 imports 和 import_items；
5. 创建 import_problems、workspace_locks、classification_profiles 和 asset_view_memberships；
6. 转换历史状态；
7. 更新 schema version；
8. 提交事务。

历史转换：

- 旧 imports：`mode=legacy`、`status=completed`、`pipeline_stage=completed`；
- 旧 imported item：`decision=legacy`，保留 asset_id；
- 旧 failed item：创建 `legacy_failure` open problem；
- 旧 missing item：创建 `missing_path` open problem；
- 现有 asset_paths 缓存立即可用；
- 分类 profile 初始为空，首次 refresh 完整构建；
- 旧 `workspace/imports/*.json` 不删除、不重写。

迁移失败时回滚数据库事务，并保留 v1 备份。

## 21. 错误处理

单项错误：

- 写入 problem；
- 更新 import_item；
- 更新 Run 计数；
- 继续下一项，除非启用 `--strict`。

致命错误：

- 输入 JSON 无法解析；
- Catalog schema 不支持；
- SQLite 不可写或事务失败；
- Workspace 配置非法；
- 输出目录不可写；
- 分类 profile 数据损坏。

致命错误将 Run 标记为 `failed` 并保留结构化 error。

## 22. 开发阶段

### 阶段 1：可恢复导入

- schema v2 迁移；
- ImportRunRepository；
- ImportPlanner；
- ImportExecutor；
- 批次事务；
- 运行锁；
- ProblemQueue；
- ProgressReporter；
- `status / resume / problems / retry-problems`。

阶段 1 完成后，分类和导出仍可继续使用全量方式。

### 阶段 2：增量分类与 refresh

- classification profile；
- asset view membership；
- ClassificationDelta；
- `refresh`；
- 受影响视图导出；
- `--full` 一致性模式。

### 阶段 3：长期维护

- `verify-assets`；
- Run 历史保留和清理；
- 问题 ignore/resolved 管理；
- 每日定时运行文档；
- 耗时和命中率趋势报告。

## 23. 真实业务验收

验收输入：

```text
E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls
```

基准：

```text
total             10010
successful assets  9987
problems              23
views                4626
unknown views          25
```

### 23.1 全新导入

- 成功资产仍为 9987；
- 23 个零字节文件全部为 `empty_file`；
- 每 5 秒内至少产生一条 info 进度；
- 单项失败不终止其他图片；
- 原图没有被修改、复制、移动或删除。

### 23.2 相同列表再次 refresh

- 9987 项为 `reuse_path`；
- 23 项为 `hold_problem`；
- 不调用 SHA、Pillow、Reader 和 Enricher；
- Asset 数量不增加；
- 同一机器暖缓存耗时不超过首次导入的 20%。

### 23.3 中断恢复

- 约处理 2000 项后终止；
- 已提交批次保留；
- `resume` 从未完成项继续；
- 最终 Asset、问题和来源顺序与不中断运行一致；
- 不重复创建 Asset 或问题。

### 23.4 问题修复

- 在验收副本中修复一个零字节文件；
- 下一次 refresh 自动识别状态变化；
- 原 problem 变为 resolved；
- 新 Asset 进入 Catalog 和分类。

### 23.5 增量分类

- 首次 profile 仍生成 4626 个视图和 25 个 unknown 视图；
- 相同列表 refresh 返回 `classification=unchanged`；
- 不重新加载全部 Asset；
- 不重写 5.5 MB 完整计划；
- 新增一张图片只计算该 Asset 和受影响视图；
- 配置变化触发一次完整重建。

### 23.6 增量导出

- 未变化 refresh 不遍历或重写全部 4626 个播放列表；
- 新图片只更新相关 `.nvpls`；
- `--full` 与增量结果一致；
- 第二次 `--full` 对未变化视图全部幂等跳过；
- 不清理 Exporter 根目录中的未知人工文件。

### 23.7 最终报告

必须包含：

```text
run_id
status
pipeline_stage
total / planned / processed
reuse_path / reuse_content / parsed_new
missing / failed / held_problem
classification mode / affected views
export written / skipped / removed
open problem count
duration
snapshot path
```

## 24. 完成标准

本设计完成的判断不是“接口存在”或“单元测试通过”，而是：

1. 真实 10010 项列表能显示持续进度并完成导入；
2. 完全相同列表再次运行时不重新解析 9987 张图片；
3. 23 个损坏文件可被稳定保留、查看和重试；
4. 中断运行能够继续；
5. 未变化 refresh 不重新完整分类和导出；
6. 完整模式与增量模式业务结果一致；
7. 所有原始图片保持不变。
