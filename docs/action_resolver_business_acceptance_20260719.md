# Action 解析工具业务验收

## 验收时间

2026-07-19

## 验收输入

旧版图片目录：

```text
G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961
```

新版 core 任务目录：

```text
G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe
```

## 旧版目录验收

命令：

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961"
```

实际输出：

```text
动作改2\new\银发萝莉事后M字开腿
```

解析依据：旧 PNG 顶层 metadata 中的：

```text
action = 04_post_银发萝莉事后M字开腿
topic  = pn_human_1boy1girl_foot_barefoot
```

通过 manifest 的 `topic/action -> source` 映射到 `new/银发萝莉事后M字开腿`。目录中的三张生成 PNG 被正确去重；`metadata_0.jpg` 没有 action metadata，不进入默认输出。

## 新版目录验收

命令：

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

实际输出：

```text
动作改2\new\萝莉躺床撩裙露内
```

解析依据：`render_request.json.meta.node_refs`：

```text
role   = action
action = 00_start_萝莉躺床撩裙露内
ref    = 动作改2/pn_human_solo_crotch_crotch_focus/00_start_萝莉躺床撩裙露内
```

通过 manifest 的 `dest -> source` 映射到 `new/萝莉躺床撩裙露内`。

## 混合 JSON 验收

命令：

```powershell
uv run python -m tags_machine_core.tools.action_resolver `
  --json `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

结果包含两条 `resolved_new`：

```text
动作改2/new/银发萝莉事后M字开腿
动作改2/new/萝莉躺床撩裙露内
```

## 代码验证

```text
12 passed
Ruff: All checks passed
```

## 验收结论

通过。旧版 PNG 和新版 core 任务归档使用不同 evidence reader，但最终都映射到 `design_root` 下的 `动作改2/new` 原始 Action 节点；分类目录仅保留为 fallback 能力。
