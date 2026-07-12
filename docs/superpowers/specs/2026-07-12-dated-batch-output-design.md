# Batch 每日输出目录设计

## 目标

Batch 配置允许在 `output_dir` 中使用 `{date}`，使服务器每天通过
`run-batch --fresh` 启动任务时，将图片写入当天的日期目录。

```yaml
output_dir: "G:/ai_auto/{date}"
```

假设 Batch 于 2026-07-12 启动，实际输出目录为：

```text
G:\ai_auto\20260712
```

## 配置语义

- `{date}` 固定展开为本地日期的 `YYYYMMDD` 格式。
- YAML 的 `output_dir` 和命令行 `--output-dir` 使用同一套展开规则。
- 不引入 `daily_output` 等专用开关；没有 `{date}` 的现有路径保持原样。
- 仅识别完整占位符 `{date}`，其他花括号内容不做隐式处理。

## 运行语义

### 新运行

`run-batch` 在规划任务前解析一次输出目录。该次运行的全部任务共享同一个
已解析路径，即使运行跨过午夜也不会切换目录。

### Fresh 运行

`run-batch --fresh` 每次创建新 `run_id`，并在启动时重新计算 `{date}`。
因此每天由调度器启动一次时，会自然写入新的日期目录。

同一天多次执行 `--fresh` 会共享同一个日期根目录，但任务目录包含新的
`task_id`，不会覆盖之前的图片。

### Resume 运行

首次运行会把已经解析的绝对 `output_dir` 写入 `batch_source.json`。
`resume-batch` 必须继续使用该路径，不重新展开 `{date}`。即使第二天恢复，
也仍写回原运行所属日期的目录。

## 组件设计

新增一个通用 Batch 路径模板解析函数，负责接收原始路径和本次运行的时间：

```python
resolve_batch_output_path(value: str | Path, *, now: datetime | None = None) -> Path
```

函数只负责模板展开，不负责决定路径优先级。CLI 和 Web Batch 工作区仍按以下
顺序选择原始输出路径：

1. 本次调用提供的 `output_dir` 覆盖值。
2. Batch YAML 的 `output_dir`。
3. 当前运行工作区下的 `outputs`。

选择完成后，两条入口统一调用模板解析函数，避免 CLI 与 Web 行为不一致。

## 时区

日期使用服务器操作系统的本地时区，与旧 `blackboard.py` 的
`datetime.now()` 行为一致。部署服务器应将系统时区设置为 `Asia/Shanghai`。
本次不新增项目级时区配置。

## 错误处理

- 普通路径完全保持向后兼容。
- `{date}` 可在路径任意层级出现，但推荐作为最后一级目录。
- 路径解析失败时，在规划和请求 NovelAI 之前直接报错。
- 不允许恢复时根据当前日期改写已归档的输出路径。

## 验收标准

1. `output_dir: "G:/ai_auto/{date}"` 能解析为当天 `G:/ai_auto/YYYYMMDD`。
2. 命令行 `--output-dir` 使用相同规则。
3. 同一次任务规划中所有 `BatchTask.output.output_dir` 完全一致。
4. `batch_source.json` 保存解析后的路径，不保存 `{date}` 模板。
5. 次日执行 `resume-batch` 仍使用首次运行的日期目录。
6. 次日执行新的 `run-batch --fresh` 使用新的日期目录。
7. 不含 `{date}` 的现有 Batch 配置结果不变。
8. Mock Batch 验证输出目录和归档结构，不触发真实 NovelAI 生图。

