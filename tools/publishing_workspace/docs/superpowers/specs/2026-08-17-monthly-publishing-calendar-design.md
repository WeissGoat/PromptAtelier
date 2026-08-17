# 月度投稿日历设计

日期：2026-08-17
状态：设计已确认，等待实施计划

## 1. 背景

Publishing Workspace 已经支持：

- 将 NeeView 播放列表、图片目录和快捷方式统一导入公共 Catalog。
- 从新版、旧版 PNG 元数据读取 artist、character、action_group、action 等节点。
- 按节点生成可重建的分类视图。
- 创建独立投稿任务，并维护 `all`、`post`、`cover` 三个选择集合。
- 通过 Processing Pipeline 和 PackageBuilder 生成目录包与 ZIP。

目前缺少的是位于投稿任务上方的“月度编排层”。用户需要提前安排一个月的投稿：工作日可能是少量散图，周末可能引用一套已经整理好的投稿任务；同一天允许多条投稿，每条投稿有明确时间。

本设计只负责手工月历编排、按时构建和提醒。当前不实现自动排期，也不直接调用 Pixiv 发布接口。

## 2. 目标

1. 提供月历 UI，默认每天为空，由用户手工安排投稿。
2. 支持同一天创建多条具有独立时间的投稿。
3. 支持两种内容来源：从 Catalog 选图创建散图投稿，以及引用已有 `tasks/<task_id>` 图集。
4. 支持从某个 workspace import 限定素材范围，并按节点信息及 `classify.yaml` 字段搜索。
5. 支持分别维护 `all`、`post`、`cover` 的成员和顺序。
6. 支持拖拽投稿卡片到其他日期，并通过表单精确修改日期和时间。
7. 执行时复用现有 Task、Processing Pipeline 和 PackageBuilder，生成投稿包并记录当次 build。
8. 单条投稿失败不阻塞其他时间槽；失败项可独立重试。
9. 为后续提醒渠道和 Pixiv 自动发布保留稳定接口。

## 3. 非目标

- 不实现工作日、周末规则或自动排期。
- 不实现投稿复制。
- 不自动上传到 Pixiv。
- 不把完整公共 Catalog 复制进月度计划。
- 不改变现有图片 Reader、Catalog、任务选择集合和投稿包格式的核心职责。
- 不强制校验 `post` 是 `all` 的子集，也不强制 `cover` 属于 `post`。

## 4. 方案选择

### 4.1 采用：独立 MonthlyPlan 编排层

```text
Workspace / Catalog
  -> 素材检索

Tasks
  -> 已整理图集
  -> all / post / cover

MonthlyPlan
  -> ScheduleEntry
  -> SubmissionExecutor
  -> TaskService / PackageBuilder
  -> Notifier
  -> 未来 Publisher
```

`MonthlyPlan` 只保存日历和投稿引用。它不接管 Catalog，不把日期写入 `task.yaml`，也不重新实现图片处理和打包。

优点：

- 公共素材、投稿内容、发布时间三个生命周期互不污染。
- 同一个 task 可以在计划执行时读取最新内容。
- 将来增加其他平台或发布器时，不需要修改 Catalog 和 Task。

### 4.2 不采用：把日期直接写入 PublishTask

这种方式文件更少，但会把内容整理和发布编排耦合。同一个 task 改期、取消或重复使用时，状态含义会变得模糊。

### 4.3 不采用：通用工作流引擎

通用 DAG 或作业编排器可以覆盖更多场景，但当前只有“到期构建、提醒、未来发布”这一条线性流程，引入工作流引擎会增加配置和维护成本。

## 5. 目录结构

月度计划与公共 `workspace/`、投稿 `tasks/` 同级：

```text
G:/ai_publish/
  workspace/
    catalog.sqlite
    imports/
    exports/
    cache/
    state/
  tasks/
    20260801_homura_foot/
  plans/
    2026-09/
      plan.yaml
      executions/
        <entry_id>/
          <execution_id>.json
```

`plan.yaml` 保存用户可编辑的计划；`executions/` 保存不可变的执行记录。实际图片输出仍然位于对应 task 的 `builds/<build_id>/`，月历不复制 build 内容。

## 6. 核心模型

### 6.1 MonthlyPlan

```yaml
schema: publishing-workspace.monthly-plan/v1
plan_id: 2026-09
month: 2026-09
timezone: Asia/Shanghai
status: draft
default_import_id: aeafeec697fa467b897fd3eeb24771e3
revision: 7
entries:
  - entry_id: 20260905-2000-homura-foot
    scheduled_at: 2026-09-05T20:00:00+08:00
    title: homura foot
    content:
      kind: task
      task_id: 20260801_homura_foot
    execution:
      build_on_due: true
      notify_on_complete: true
      publish: false
```

字段：

- `plan_id`：月度计划 ID，默认使用 `YYYY-MM`。
- `month`：月历显示月份。
- `timezone`：所有计划时间的解释时区。
- `status`：`draft` 或 `locked`。
- `default_import_id`：素材搜索默认限定的 import；为空时搜索整个 Catalog。
- `revision`：每次保存递增，用于防止两个页面覆盖彼此修改。
- `entries`：本月投稿列表，按 `scheduled_at` 排序保存。

### 6.2 ScheduleEntry

每条投稿拥有独立 ID、时间、内容来源和执行策略。同一天多条投稿只是拥有相同日期、不同时间的多条 `ScheduleEntry`。

支持两种内容来源。

#### 引用已有 task

```yaml
content:
  kind: task
  task_id: 20260801_homura_foot
```

计划只保存 `task_id`。执行时读取 task 当前的 `all`、`post`、`cover`，并记录实际使用的 `build_id` 和 selection snapshot。这样用户在执行前仍可继续整理 task。

#### 月历内创建散图投稿

```yaml
content:
  kind: inline_selection
  source_import_id: aeafeec697fa467b897fd3eeb24771e3
  sets:
    all:
      - asset_id: sha256:aaa
      - asset_id: sha256:bbb
    post:
      - asset_id: sha256:aaa
      - asset_id: sha256:bbb
    cover: []
```

散图默认 `all = post`、`cover = []`，用户仍可在右侧编辑器中分别调整三个集合。计划只保存有序 `asset_id`，原始路径由 Catalog 在执行时解析。

### 6.3 ExecutionRecord

```json
{
  "execution_id": "20260905T200001-8f37c2",
  "entry_id": "20260905-2000-homura-foot",
  "plan_revision": 7,
  "scheduled_at": "2026-09-05T20:00:00+08:00",
  "started_at": "2026-09-05T20:00:01+08:00",
  "finished_at": "2026-09-05T20:02:10+08:00",
  "status": "completed",
  "task_id": "20260801_homura_foot",
  "build_id": "20260905T200002-28b311",
  "notification_status": "sent",
  "publish_status": "disabled",
  "error": null
}
```

执行记录不可修改。重试会创建新的 `execution_id`，不会覆盖旧失败记录。

## 7. 组件职责

### 7.1 PlanRepository

- 读取和保存 `plans/<YYYY-MM>/plan.yaml`。
- 校验月份、时区、投稿时间和 entry ID 唯一性。
- 使用临时文件加原子替换保存。
- 通过 `revision` 做乐观并发检查。

### 7.2 ScheduleService

- 创建、编辑、删除投稿。
- 拖拽时只修改 `scheduled_at` 的日期部分，保留原时间。
- “移动时间”同时修改日期和时间。
- 对同一时间存在多条投稿只给 warning，不禁止保存。
- 锁定计划时执行完整引用校验并保存锁定时间。

### 7.3 AssetSearchService

- 默认查询 `default_import_id` 对应快照，也可切换其他 import 或整个 Catalog。
- 支持 artist、character、action_group、action 的精确或模糊匹配。
- 支持按 `classify.yaml` 字段筛选：`phase`、`species`、`cast`、`domain`、`subtype`、`pose`、`environment`、`tone`、`flags`、`clothing`。
- 搜索返回统一 `AssetSearchResult`，UI 不直接读取 PNG 或设计目录。
- 返回图片是否已被其他投稿或 execution 使用，以及需要展示的提醒标记。

`classify.yaml` 信息通过 asset 的 action node ref 解析，并投影为可查询 facet。该逻辑属于检索增强，不修改 Reader 输出和 PNG 元数据。

### 7.4 InlineTaskMaterializer

现有 PackageBuilder 以 task 为输入。执行散图投稿时，`InlineTaskMaterializer` 根据 `asset_id` 创建一次性的内部 task snapshot，再进入完全相同的处理和打包链路。

该组件只负责协议转换，不实现图片处理规则。

### 7.5 SubmissionExecutor

```text
读取已锁定 MonthlyPlan
  -> 查找到期且尚未成功执行的 ScheduleEntry
  -> 解析 task 或 inline_selection
  -> 调用 TaskService / PackageBuilder
  -> 写入 ExecutionRecord
  -> 调用 Notifier
  -> 未来可调用 Publisher
```

- 每条 entry 独立执行。
- 一条失败后继续处理其他到期 entry。
- 默认最多尝试一次；用户可对失败 execution 显式重试。
- 使用 `entry_id + scheduled_at + plan_revision` 生成幂等键，避免同一版本重复构建。
- 已成功执行的 entry 不会因周期性扫描再次执行。

### 7.6 Notifier

当前只定义接口：

```python
class Notifier(Protocol):
    def notify(self, event: SubmissionEvent) -> NotificationResult: ...
```

首个实现可以是控制台和结构化日志。未来可增加桌面通知、Webhook、Discord 等实现，不修改 SubmissionExecutor。

### 7.7 Publisher

当前不启用，只保留接口和 `publish: false`：

```python
class Publisher(Protocol):
    def publish(self, request: PublishRequest) -> PublishResult: ...
```

未来 Pixiv 接入只消费已完成的 build，不直接读取 Catalog 或修改 task。

## 8. 月历 UI

### 8.1 顶部

- 上月、下月、跳转月份。
- 当前状态：未锁定或已锁定。
- “锁定计划”按钮。
- 不显示自动排期入口。

### 8.2 左侧素材库

- 选择 workspace import。
- “图片搜索”“角色池”“已有投稿”三个视图。
- 按节点字段和 `classify.yaml` facet 搜索。
- 空筛选表示全部，文本筛选支持模糊匹配。
- 已用于其他投稿或存在风险标记的图片显示角标提醒。
- 点击缩略图打开大图预览。
- 图片可多选后加入当前投稿或创建新的散图投稿。

### 8.3 中间月历

- 默认日期为空。
- 每个日期可以添加多条投稿。
- 卡片显示时间、标题、散图/图集和图片数量。
- 拖拽卡片到其他日期时保留原时间。
- 点击卡片在右侧打开编辑器。
- 不提供“复制投稿”。

### 8.4 右侧投稿编辑器

- 修改日期和时间。
- 删除投稿。
- 选择内容类型：散图或已有 task 图集。
- 显示来源和当前 `all/post/cover` 数量。
- 使用标签分别切换三个集合；每个集合维护独立成员和顺序。
- 支持拖拽排序、移除图片、从左侧加入图片和查看大图。
- 显示风险或重复使用提醒，但提醒不阻止保存。

## 9. 锁定语义

`draft` 状态允许编辑。`locked` 表示该 revision 可以被执行器消费。

锁定时校验：

- 所有 entry 的时间位于计划月份内。
- task 引用存在。
- inline selection 的 asset 均能在 Catalog 中解析。
- 至少存在一个 `post` 项；为空时阻止锁定。
- 缺少 `all` 或 `cover` 仅 warning。
- 重复图片、重复时间和图片已用于历史投稿仅 warning。

锁定后如需修改，用户先解锁。再次锁定会生成新的 revision；已经成功执行的旧 entry 不会自动重复执行。

## 10. 执行方式

服务器可周期性调用：

```powershell
uv run publishing-workspace schedule run-due G:\ai_publish
```

该命令只执行：

- 状态为 `locked` 的计划。
- `scheduled_at <= now` 的 entry。
- 当前幂等键尚未成功执行的 entry。

提供辅助命令：

```powershell
uv run publishing-workspace schedule status G:\ai_publish 2026-09
uv run publishing-workspace schedule retry G:\ai_publish 2026-09 <entry_id>
uv run publishing-workspace schedule build-now G:\ai_publish 2026-09 <entry_id>
```

`build-now` 用于人工提前验证投稿包，不改变计划时间，也不标记计划中的到期执行已经完成；它的 execution reason 记录为 `manual_preview`。

## 11. 错误处理

- 计划 YAML 损坏：整个月计划拒绝加载，记录 error，不尝试部分执行。
- task 不存在：该 entry 失败，其他 entry 继续。
- asset 路径失效：该 entry 失败，并列出缺失 asset ID。
- Processing 或 PackageBuilder 失败：保留失败 execution，不生成成功状态。
- 通知失败：build 保持成功，记录 `notification_status: failed`，允许只重试通知。
- UI revision 冲突：拒绝后提交，并要求重新载入最新计划。
- 进程中断：没有 completed execution 的 entry 在下次扫描时重新判断；幂等键防止重复成功构建。

## 12. 日志

日志沿用 Publishing Workspace 的 `trace`、`info`、`warning`、`error` 分级：

- `trace`：搜索条件、asset ID 解析、幂等键、集合排序变化。
- `info`：计划保存/锁定、到期扫描、构建开始/完成、通知结果。
- `warning`：重复时间、历史已使用图片、缺少非必要集合、通知失败。
- `error`：计划无法加载、引用失效、构建失败。

非开发环境默认 `error`；常规人工运行推荐 `--log-level info`。

## 13. 验收标准

### 13.1 业务验收

创建一个小型 2026-09 月度计划：

- 至少 3 个日期。
- 其中一天包含 2 个不同时间槽。
- 至少 1 条散图投稿和 1 条已有 task 图集。
- 散图从指定 import 中按 character、action_group 和至少一个 `classify.yaml` 字段筛选。
- 分别调整 `all`、`post`、`cover` 顺序，重新打开页面后顺序保持。
- 将一条投稿拖到其他日期，时间保持不变。
- 锁定计划后执行 `run-due`，成功生成对应 build 和 execution 记录。
- 人为制造一条失效 task，确认该条失败但其他条继续完成。
- 再次执行 `run-due`，确认成功项不会重复构建。

### 13.2 UI 验收

- 月历默认空白且支持同日多投稿。
- 不出现自动排期和复制投稿入口。
- 所有筛选器空值表示全部。
- 搜索结果支持 `classify.yaml` facet。
- 风险或历史使用图片显示角标提醒。
- 点击素材和投稿缩略图都可查看大图。
- `all/post/cover` 切换后展示和调整各自顺序。
- 小屏幕不发生文字重叠，日历可以横向滚动或切换紧凑视图。

### 13.3 回归验收

- 现有 import、export、task create、task build 命令行为不变。
- 月历执行产生的 task build 与手工执行同一 task 的 PackageBuilder 结果结构一致。
- inline selection 不修改公共 Catalog、原图和已有 task。

## 14. 实施边界

首期实现包括：

- MonthlyPlan、ScheduleEntry、ExecutionRecord 模型。
- PlanRepository、ScheduleService、AssetSearchService。
- inline selection 到现有 task/build 链路的转换。
- `schedule status/run-due/retry/build-now` CLI。
- 月历 Web UI 和大图预览。
- 控制台/结构化日志 Notifier。

后续独立迭代：

- Pixiv Publisher。
- 更多通知渠道。
- 自动排期或推荐排期。
- 多平台差异化标题、正文和标签。
