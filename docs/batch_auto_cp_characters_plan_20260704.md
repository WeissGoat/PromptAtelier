# Batch 自动 CP 多角色开发计划 2026-07-04

## 目标

batch 配置仍然只选择普通 `characters`，不新增 `character_groups` 配置。

当 action 明确需要多人图时，planner 自动根据主角色 `meta.yaml` 的 `relations.cp` 补齐副角色：

```yaml
relations:
  cp:
    - kaname_madoka
```

如果 action 需要多人但主角色没有可解析的 cp，则跳过该 task。

## 范围

本阶段只处理 `Ngirls`：

- `2girls` -> 需要 2 个 character node。
- `3girls` -> 需要 3 个 character node。
- `multiple girls` -> 暂按 2 个 character node。
- 未检测到多人数量 -> 保持单角色。

暂不处理：

- `1girl, 1boy` / `1boy` / `2boys` 等男女混合或男性角色自动补齐。
- 角色位置关系，例如 left/right/front/back。
- 从旧 `tags.txt` 运行时读取 `type,cp|...`。
- 修改 AgentComposer 的 cache 规则。

## 数据准备

旧 `tags.txt` 的 `type,cp|...` 通过一次性脚本转写到 `meta.yaml`：

```powershell
uv run python scripts\sync_character_cp_relations.py ..\design\角色 --write --backup
```

运行时只读取结构化 `meta.yaml`。

## 组件设计

新增模块：

```text
src/tags_machine_core/batch/character_relations.py
```

职责：

- `detect_required_girl_count(action_node)`：
  从 action node 的正向素材中解析 `2girls`、`3girls`、`multiple girls`。

- `resolve_cp_character_refs(main_character_node, candidate_characters, reader)`：
  使用主角色 `relations.cp` 在当前 batch 的候选角色集合中解析副角色 ref。

匹配顺序：

1. cp 值等于候选 ref 路径。
2. cp 值等于候选节点 `id`。
3. cp 值等于候选节点 `character_id`。
4. cp 值命中候选节点 `tags.character`。
5. cp 值等于候选目录名。

## Planner 接入

接入位置：

- `BatchPlanner._plan_character_action_group`
- `BatchPlanner._plan_blackboard_rounds`
- 可选补齐 `_plan_product`，但本阶段主验收以前两个 batch 主链路为准。

生成 task 前：

```text
main character + action
-> detect required girl count
-> count <= 1: 原单角色 task
-> count > 1:
     resolve cp refs from selected characters
     enough: task.nodes = main + cp refs + action + artist + background
     not enough: skip task and log warning
```

## 输出与追踪

多人 task 的 `source` 增加：

```json
{
  "characters": ["main_ref", "cp_ref"],
  "auto_cp": true,
  "required_character_count": 2
}
```

单人 task 保留现有 `source.character`。

跳过 task 先通过 warning 日志记录：

```text
skip multi-character task character=... action=... required=2 reason=missing_cp
```

后续如果需要统计 skipped task，再扩展 manifest/report。

## 验收

配置里只选择单个主角色和其 CP 候选角色：

```yaml
select:
  characters:
    - selector: explicit
      refs:
        - homura
        - madoka
```

action 为 `2girls, sitting` 时：

- task 包含两个 `role=character` 节点。
- 第二个角色来自主角色 `relations.cp`。
- `source.auto_cp == true`。

如果主角色没有 cp：

- 对应多人 action 不生成 task。
- 日志记录跳过原因。

真实出图验收：

- 使用 NovelAI 跑一组 `2girls` action。
- 检查 PNG 参数里 prompt / character prompts 是否包含两个角色。
