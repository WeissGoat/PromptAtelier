# 生成图片 Action 解析工具设计

## 1. 目标

在 `tags_machine_core.tools` 下新增独立工具，用同一条命令解析旧版生成图片目录和新版 core 任务归档目录，并定位其对应的 Action 节点。

无论输入来自旧版还是新版，解析结果都优先指向 `legacy.design_root/动作改2/new` 下的原始节点。只有无法映射到原始节点时，才返回实际存在的分类目录，并明确标记为 fallback。

工具只读取图片、JSON 归档、Action manifest 和节点目录，不修改任何输入文件或 `design` 内容。

## 2. 验收样本

真实业务验收必须覆盖以下目录：

```text
G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961
G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe
```

预期默认输出以 `legacy.design_root` 为根，不输出盘符前缀：

```text
动作改2/new/银发萝莉事后M字开腿
动作改2/new/萝莉躺床撩裙露内
```

第一组用于验证旧版 PNG metadata 解析，第二组用于验证新版任务归档和分类节点反查原始节点。

## 3. 输入范围

单次命令允许混合传入任意数量的路径：

- 旧版 PNG、JPG、JPEG、WEBP 图片。
- 旧版生成图片目录。
- 新版任务目录。
- 新版任务目录内的图片或 JSON 文件。
- 包含多个新版任务目录的 batch 输出根目录。
- 同时包含旧图和新版任务归档的混合目录。

目录默认递归扫描，不额外要求 `--recursive`。扫描器必须去重同一个任务目录，避免一个任务内的多张图片、`png_params.json` 和参数预览图重复产生结果。

支持的图片后缀为：

```text
.png .jpg .jpeg .webp
```

## 4. 输出语义

默认输出去重后的 Action 路径，每行一个，路径始终相对 `legacy.design_root`：

```text
动作改2/new/侧脸回眸
动作改2/pn_human_solo_sfw_portrait/00_start_未迁移动作
```

第一行表示成功映射到原始节点；第二行表示只能返回分类目录。

工具提供三种输出模式：

- 默认 paths：只打印去重后的已解析路径。
- `--table`：打印状态、来源、原始 action、topic、结果路径和原因。
- `--json`：输出完整结构化结果，适合其他工具和 Agent 调用。

`--per-input` 关闭默认聚合，保留每个图片或任务归档对应的解析记录。未指定时，按状态、目标路径和原始 evidence 聚合重复结果。

## 5. 状态模型

每条结果使用以下状态之一：

- `resolved_new`：已映射到 `动作改2/new` 原始节点。
- `category_fallback`：无法映射到 `new`，但找到了实际分类目录。
- `ambiguous`：存在多个可能的原始节点，工具拒绝猜测。
- `unresolved`：没有找到原始节点或分类目录。
- `read_error`：图片或 JSON 无法读取。
- `missing_action`：文件可读取，但没有 Action 证据；默认 paths 模式忽略该记录。

默认模式即使存在 fallback 或 unresolved 也完成输出并返回退出码 0。启用 `--strict` 后，只要存在 `category_fallback`、`ambiguous`、`unresolved` 或 `read_error`，命令返回退出码 1。

无效输入路径、配置缺失或 `design_root` 不可用返回退出码 2。

## 6. 架构

新增模块：

```text
src/tags_machine_core/tools/action_resolver/
  __init__.py
  __main__.py
  models.py
  scanner.py
  readers.py
  index.py
  resolver.py
  cli.py
```

### 6.1 models.py

定义跨组件的数据结构：

- `ActionEvidence`：某个输入中读取到的 action、topic、分类引用和证据来源。
- `ResolvedAction`：解析状态、原始 evidence、相对结果路径、绝对目录和原因。
- `ScanResult`：扫描到的任务归档、独立图片和扫描错误。

数据模型不依赖 CLI，后续右键菜单或其他工具可以直接调用 Python API。

### 6.2 scanner.py

`GeneratedActionInputScanner` 负责把混合输入展开为两类唯一来源：

- 新版任务目录。
- 不属于已发现任务目录的独立图片。

扫描规则：

1. 输入文件位于任务归档目录内时，向上定位任务目录。
2. 输入目录本身包含归档文件时，将其视为单个任务。
3. 否则递归发现 `render_request.json`、`prompt_bundle.json` 或 `generation_result.json` 所在目录。
4. 递归发现图片，但跳过已归属新版任务目录的图片。
5. 使用规范化绝对路径去重任务和图片。

### 6.3 readers.py

读者层只负责提取 evidence，不负责决定最终 Action 目录。

新版任务 evidence 优先级：

1. `render_request.json.meta.node_refs` 中所有 `role=action` 的节点。
2. `prompt_bundle.json.meta.nodes` 中所有 `role=action` 的节点。
3. 同一个 role/index/ref 的 evidence 合并去重。

新版读取复用现有 `TaskArchiveResolver` 对任务归档的定位和 JSON 读取能力，避免维护第二套归档格式。

旧版图片 evidence 优先级：

1. PNG/JPEG/WebP metadata 的大小写不敏感 `action`、`topic` 字段。
2. `Comment` JSON 中的 `action`、`topic` 字段。
3. 读取失败产生 `read_error`，无 action 产生 `missing_action`。

`metadata_*.jpg`、参数详情图等无 Action metadata 的文件不会污染默认 paths 输出。

### 6.4 index.py

`ActionNodeIndex` 以 `legacy.design_root/动作改2` 为 Action 根目录，建立以下只读索引：

- `category_view_manifest.json` 的 `source`、`dest`、`root + view_name`、`view_name`、`name`。
- `动作改2/new` 下一级原始节点名称。
- 实际存在的分类目录相对路径。

manifest 是分类节点映射回原始节点的主要依据。索引加载时必须验证 `source` 指向的 `new` 目录实际存在；不存在的 source 不算成功映射。

manifest 缺失或单条数据无匹配时，仍允许使用 `new` 名称唯一匹配和分类目录 fallback。manifest 文件存在但 JSON 无法读取时，表格和 JSON 模式必须暴露清晰错误，不能静默退化。

### 6.5 resolver.py

`GeneratedActionResolver` 对旧版和新版 evidence 使用完全相同的映射顺序：

1. evidence 已直接指向 `动作改2/new/<node>` 且目录存在，返回 `resolved_new`。
2. 将绝对分类 ref 转成相对 `动作改2` 的分类路径，通过 manifest 的 `dest` 查找 `source`。
3. 使用 `topic/root + action/view_name` 通过 manifest 查找 `source`。
4. 使用完整 action 值匹配 manifest 的 `view_name` 或 `name`；只有唯一结果才接受。
5. 去除 `00_start_`、`01_pre_`、`02_core_`、`03_cum_`、`04_post_` 阶段前缀后，唯一匹配 `new` 节点名称。
6. 处理旧分类目录数字前缀，例如 metadata action `20240720_1721464255` 可以匹配分类目录 `2_20240720_1721464255`。
7. 若分类目录可通过 `topic + action` 唯一定位，返回 `category_fallback`。
8. 多个候选返回 `ambiguous`，没有候选返回 `unresolved`。

任何阶段都不得通过 prompt 文本相似度猜测 Action。

## 7. 配置

工具通过 core 配置中的以下字段定位提示词库：

```yaml
legacy:
  design_root: F:/my_project/new/tags_machine/design
```

CLI 提供：

- `--config`：core 配置文件，默认使用项目的 `configs/local.example.yaml` 解析规则，并优先采用同目录私有 `local.yaml`。
- `--design-root`：显式覆盖 `legacy.design_root`，适合独立调用和临时提示词库。

输出路径始终以最终生效的 design root 为根。

## 8. CLI

独立入口：

```powershell
uv run python -m tags_machine_core.tools.action_resolver `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

主 CLI 快捷入口：

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

可选参数：

```text
--config PATH
--design-root PATH
--table
--json
--per-input
--strict
```

`--table` 与 `--json` 互斥；未指定时为 paths 模式。

## 9. 公共 Python API

模块公开以下稳定入口：

```python
from tags_machine_core.tools.action_resolver import resolve_generated_actions

results = resolve_generated_actions(
    inputs=[old_directory, new_task_directory],
    design_root=design_root,
)
```

返回 `list[ResolvedAction]`。Python API 不打印内容、不退出进程，由调用方决定展示和严格模式。

## 10. 测试与验收

自动测试覆盖：

- 旧图片顶层 metadata。
- 旧图片 `Comment` JSON fallback。
- 新版 `render_request.meta.node_refs`。
- 新版 `prompt_bundle.meta.nodes` fallback。
- 分类 `dest` 到 `new/source` 映射。
- 阶段前缀和数字前缀处理。
- 分类目录 fallback、ambiguous、unresolved。
- 混合目录递归扫描和任务图片去重。
- paths、table、JSON 和 strict 退出码。
- 主 CLI 与独立 CLI 输出一致。

业务验收必须直接运行第 2 节两个真实目录，并确认输出包含且只包含：

```text
动作改2/new/银发萝莉事后M字开腿
动作改2/new/萝莉躺床撩裙露内
```

业务验收优先于额外单元测试；单元测试用于保护解析规则，不替代真实目录验证。

## 11. 非目标

- 不修改或迁移 Action 节点。
- 不根据 prompt 内容推测动作。
- 不解析 character、artist 或 background。
- 不创建新的 `category_view_manifest.json`。
- 不把旧版和新版结果写回图片 metadata。
- 本阶段不接入 Windows SendTo 菜单；公共 Python API 可供后续操作类型复用。
