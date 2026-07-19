# 生成图片 Action 解析工具

这个工具把旧版生成图片和新版 core 任务归档映射到对应的 Action 节点。无论输入格式如何，都会优先返回 `design/动作改2/new` 下的原始节点；只有原始节点无法定位时才返回分类目录，并标记为 `category_fallback`。

## 使用前提

配置文件需要指向旧提示词库：

```yaml
legacy:
  design_root: F:/my_project/new/tags_machine/design
```

工具读取 `legacy.design_root/动作改2/category_view_manifest.json`、`new/` 和分类目录，不会修改它们。

## 命令入口

独立入口：

```powershell
uv run python -m tags_machine_core.tools.action_resolver `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

主 CLI 入口：

```powershell
uv run python -m tags_machine_core resolve-actions `
  "G:\ai_auto\20260702\blackboard_tags_machine_1782927346_3_1782935961" `
  "G:\ai_auto\20260717\27e6515d_57_29_0_554d15fe"
```

默认输出是相对 `design_root` 的去重路径：

```text
动作改2\new\银发萝莉事后M字开腿
动作改2\new\萝莉躺床撩裙露内
```

## 参数

```text
--config PATH       从配置读取 legacy.design_root
--design-root PATH  直接覆盖 legacy.design_root
--table             输出状态表
--json              输出结构化 JSON
--per-input         保留每张图片/每个任务的独立记录
--strict            fallback、歧义、未解析或读取错误时返回 1
```

不传 `--config` 或 `--design-root` 时，工具使用项目 `configs/local.example.yaml`，如果同目录存在 `configs/local.yaml` 则优先使用私有配置。

目录输入默认递归扫描。新版任务目录中的多张生成图片和参数详情图会归并为一个任务；旧版目录中的多张相同 action 图片会在默认模式去重。

## 解析来源

新版任务读取：

1. `render_request.json.meta.node_refs` 的 `role=action`。
2. `prompt_bundle.json.meta.nodes` 的 `role=action`。

旧版图片读取：

1. PNG/JPEG/WebP 顶层 `action`、`topic` metadata。
2. `Comment` JSON 中的 `action`、`topic`。

没有 action 的辅助图只在 `--per-input` 中显示，默认聚合输出会忽略它。

## 映射优先级

1. action ref 已直接指向 `new/` 原始节点。
2. 分类 ref 通过 manifest `dest -> source` 映射。
3. `topic + action` 通过 manifest 映射。
4. 唯一 Action 名称通过 manifest 映射。
5. 去掉 `00_start_`、`01_pre_`、`02_core_`、`03_cum_`、`04_post_` 后匹配 `new`。
6. 分类目录数字前缀匹配，例如 `20240720_...` 对应 `2_20240720_...`。
7. 返回分类目录 fallback。

工具不会根据完整 prompt 的相似度猜测 action。多个候选会返回 `ambiguous`。

## JSON 结果

```json
{
  "status": "resolved_new",
  "input": "G:\\ai_auto\\20260717\\27e6515d_57_29_0_554d15fe",
  "source_kind": "core_task",
  "source_detail": "render_request.meta.node_refs",
  "action": "00_start_萝莉躺床撩裙露内",
  "topic": "pn_human_solo_crotch_crotch_focus",
  "relative_path": "动作改2/new/萝莉躺床撩裙露内",
  "absolute_path": "F:\\my_project\\new\\tags_machine\\design\\动作改2\\new\\萝莉躺床撩裙露内",
  "reason": "通过分类 ref 和 manifest.dest 映射到原始节点"
}
```

## Python API

```python
from tags_machine_core.tools.action_resolver import resolve_generated_actions

results = resolve_generated_actions(
    [old_image_dir, new_task_dir],
    design_root=design_root,
)
```

Python API 返回 `list[ResolvedAction]`，不打印、不退出进程，适合后续 Windows 工具、Agent 或前端调用。
