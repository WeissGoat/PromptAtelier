# 可恢复导入真实验收

本文档用于验收 `publishing_workspace` 对 NeeView 播放列表的持久化导入、重复导入、
中断恢复和问题保持行为。验收使用真实图片清单，但不会修改、复制或移动原始图片。

## 验收输入

```text
播放列表：E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls
验收工作区：G:\ai_publish_acceptance\recoverable-import-20260801
```

验收工作区必须是独立目录，不要使用长期公共工作区 `G:\ai_publish`，避免验收过程
污染日常数据。

基准清单：

```text
总项目：10010
成功项目：9987
问题项目：23
```

## 执行命令

在 `tools/publishing_workspace` 目录执行：

```powershell
uv run python scripts/accept_recoverable_import.py `
  --workspace G:\ai_publish_acceptance\recoverable-import-20260801 `
  --playlist E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls `
  --mode first
```

重复导入使用同一个工作区：

```powershell
uv run python scripts/accept_recoverable_import.py `
  --workspace G:\ai_publish_acceptance\recoverable-import-20260801 `
  --playlist E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls `
  --mode repeat
```

中断恢复使用另一个全新的工作区。脚本会在至少提交 200 个项目后中止导入，等待租约
过期，再使用原来的 `run_id` 执行 `resume`：

```powershell
uv run python scripts/accept_recoverable_import.py `
  --workspace G:\ai_publish_acceptance\recoverable-import-20260801-interrupt `
  --playlist E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls `
  --mode interrupt-resume
```

查看已有验收结果：

```powershell
uv run python scripts/accept_recoverable_import.py `
  --workspace G:\ai_publish_acceptance\recoverable-import-20260801 `
  --playlist E:\NeeView41.3\Profile\Playlists\合_20260728.nvpls `
  --mode report
```

## 判定标准

### 首次导入

最终 JSON 必须满足：

```text
total_items = 10010
成功项目 = reused_path_items + reused_content_items + parsed_new_items = 9987
问题项目 = missing_items + failed_items + held_problem_items = 23
status = completed 或 completed_with_errors
```

同时 stderr 应能看到 `planning_progress` 和 `execution_progress`，至少每 200 项输出
一次，并在阶段开始和结束时输出日志。每个导入项目必须能在 SQLite 的 `import_items`
中找到，不允许只依赖最终快照。

### 重复导入

同一播放列表、同一工作区再次执行时，预期：

```text
reused_path_items = 9987
parsed_new_items = 0
held_problem_items = 23
```

重复导入不得重新计算未变化文件的 SHA-256、PNG 尺寸、Reader 或 Enricher；原有 23
个问题必须保持为 `held_problem`，不能在未显式 retry 的情况下反复执行失败解析。

### 中断恢复

中断时必须已经持久化至少 200 个已处理项目。恢复时必须使用相同的 `run_id`，不重新
读取 NeeView 播放列表；最终结果仍应为 10010 项、9987 个成功项目和 23 个问题项目。
`import_items` 的主键为 `(import_id, source_order)`，因此恢复后不能产生重复项目。

### 分类和导出回归

导入验收通过后执行：

```powershell
uv run publishing-workspace classify G:\ai_publish_acceptance\recoverable-import-20260801
uv run publishing-workspace export G:\ai_publish_acceptance\recoverable-import-20260801
```

分类视图和导出结果应保持已有基准：

```text
分类视图：4626
unknown 视图：25
```

导出器只生成图片引用或播放列表，不复制、重命名或移动原始图片。

## 结果留存

每个 ImportRun 的快照保存在：

```text
<workspace>\workspace\imports\<run_id>.json
```

脚本的 `report` 输出、终端日志和快照一起作为本次业务验收记录。验收完成后再决定
是否将工作区纳入长期运行环境。
