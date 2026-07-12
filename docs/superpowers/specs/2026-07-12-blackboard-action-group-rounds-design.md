# Blackboard 动作组轮次调度设计

## 1. 背景

`blackboard.py:run_tags_machine` 当前使用 `ACTION_NEW`、`特殊_next_select`、固定 artist 和 `nt=3` 持续跑图。旧链路会把每个动作分类文件夹视为独立 topic，优先从运行次数最少的 topic 中随机选择一个，再从该 topic 随机抽取 3 个动作，按原目录顺序执行，随后切换到下一个角色。

当前 batch 配置中的 `action_groups: action_new` 会先把 collection 展开成动作节点，再合并为一个 `ResolvedActionGroup`。因此约 99 个 `pn_*` 文件夹被压成一个包含约 1795 个动作的大组，无法复刻旧 Blackboard 的调度行为。

本次改动只调整 batch 的动作组解析、轮次规划和运行状态记录。Composer、PromptPolicyPipeline、Renderer、NovelAI client 和 AgentComposer 不改变。

## 2. 目标

- `action_groups: action_new` 能保留 collection 匹配到的直接子文件夹边界。
- 每个 `pn_*` 文件夹成为一个独立 `ResolvedActionGroup`。
- `blackboard_rounds` 每轮处理一个角色和一个动作组。
- 支持从组内随机抽取固定数量动作，并恢复原 natural sort 顺序。
- `balanced_random` 根据历史选择次数优先选择次数最少的组。
- 动作组状态自动保存在 batch 工作目录，不要求 YAML 提供路径。
- `plan-batch` 与真实运行使用同一规划逻辑，但预览不得污染持久状态。
- `resume-batch` 不重复累计同一轮次，`--fresh` 重置动作组状态。

## 3. 非目标

- 不复刻旧 Formula 的全部硬编码。
- 不改变 ScriptComposer 或 PromptPolicyPipeline。
- 不为 `ACTION_NEW`、`pn_*` 或某个 artist 编写特殊分支。
- 不提供无限预生成任务；一次 batch 仍是有限任务集。
- 不修改普通 `select.actions` 的扁平展开语义。

## 4. 概念边界

### 4.1 Action Collection

Action collection 表示动作节点池。例如 `action_new` 表示所有 `pn_*` 文件夹下的动作。它作为普通 `select.actions` 使用时仍展开为扁平节点列表。

### 4.2 Action Group

Action group 表示具有独立调度次数的动作分类。使用 collection 作为 `select.action_groups` 输入时，collection 中 folder selector 匹配到的每个直接子文件夹分别形成一个 group。

例如：

```text
action_new
  pn_group_a/
  pn_group_b/
  pn_group_c/
```

解析结果：

```text
ResolvedActionGroup(name="pn_group_a", actions=[...])
ResolvedActionGroup(name="pn_group_b", actions=[...])
ResolvedActionGroup(name="pn_group_c", actions=[...])
```

### 4.3 Round

一个 round 表示：

```text
一个主角色 + 一个选中的动作组 + 本轮抽中的动作集合
```

同一 round 产生的 task 共享稳定的 `round_id`。动作组选择次数按 round 计算，而不是按 task 或图片计算。

## 5. 配置契约

### 5.1 新增字段

`ExpandConfig` 增加：

```yaml
expand:
  actions_per_group: 3
  action_selection: random_preserve_order
```

字段定义：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `actions_per_group` | `null` | 每轮最多从选中组取多少个动作；`null` 表示使用全部动作。 |
| `action_selection` | `all` | 组内选择方式，首版支持 `all` 和 `random_preserve_order`。 |

规则：

- `all`：使用组内全部动作；配置 `actions_per_group` 时取 natural sort 后的前 N 个。
- `random_preserve_order`：随机抽取最多 N 个动作，再按抽样前的 natural sort 索引排序。
- `actions_per_group` 大于组内动作数时使用全部动作。
- `actions_per_group` 必须大于等于 1。
- 随机源使用 `expand.seed`，保证相同输入与状态下可复现。

### 5.2 `auto_num` 最终语义

保留现有语义：

```text
每个角色运行一个 round，全部角色轮换一次后结束。
```

`auto_num` 只决定外层生成多少轮，不决定组内选择方式。

```yaml
auto_num: true
actions_per_group: 3
action_selection: random_preserve_order
```

表示每个角色选择一个动作组，每组抽 3 个动作，所有角色跑一遍后结束。

当 `auto_num: false` 时，`blackboard_rounds` 必须设置 `max_tasks`。Planner 循环角色和动作组，直到生成的 task 数达到上限。

用于替代旧 `run_tags_machine` 的配置使用 `max_tasks`，不使用 `auto_num`。

### 5.3 目标配置

```yaml
batch:
  characters: special_next_select
  action_groups: action_new
  artist: "104994507_01_flat_color_artist_stack_vibe_86b3d31d_619_cfg07_strength04_v45_latest_stable"
  composer: script
  nt: 3

expand:
  mode: blackboard_rounds
  max_tasks: 300
  action_group_strategy: balanced_random
  actions_per_group: 3
  action_selection: random_preserve_order
```

`action_group_record` 不再要求出现在业务 YAML 中。

## 6. 动作组解析

### 6.1 普通 selector

显式定义的 action group 保持现状：一个 selector 对应一个 group。

```yaml
select:
  action_groups:
    - name: st_rp
      selector: folder
      root: F:/.../动作改2/st_rp
```

### 6.2 Collection selector

当 action group 使用 collection selector 时，解析器读取 collection 的原始 item，不先调用扁平化的 `expand_selector()`。

对于 folder item：

1. 在 `root` 下应用 `include.names` 和 `exclude.names`。
2. 每个匹配到的直接子目录形成一个 group。
3. 在该子目录内按原 selector 的 `recursive`、`node_files`、过滤和 natural sort 规则发现动作节点。
4. group 名称默认使用子目录名。
5. 多个 collection item 产生的 group 合并，并检查重名。

对于 collection 引用：递归展开被引用 collection，同时保留其 folder group 边界。

对于直接节点路径或无法形成子目录分组的 selector：保持为 collection 名称对应的单一 group，避免破坏显式 action group 用法。

普通 `select.actions` 继续使用现有 `expand_selector()`，不会因本次改动改变。

## 7. 组内动作选择

新增独立的 `ActionSelector`，职责是从一个 `ResolvedActionGroup` 选择本轮动作，不让抽样逻辑继续堆积在 `BatchPlanner`。

接口概念：

```python
select_actions(
    group,
    strategy,
    limit,
    rng,
) -> list[str]
```

`random_preserve_order` 算法：

1. group actions 已按 natural sort 排序。
2. 随机抽取动作索引。
3. 对抽中的索引升序排序。
4. 按排序后的索引返回动作。

这样既保留随机性，也与旧 `input_random_story` 的执行顺序一致。

## 8. 运行状态

### 8.1 默认位置

动作组状态自动保存在：

```text
<run_dir>/state/action_groups.json
```

例如：

```text
refactor/examples/batches/blackboard-action-new-manga-monochrome/state/action_groups.json
```

### 8.2 状态结构

```json
{
  "schema": "tags-machine-core.action-group-state/v1",
  "updated_at": "...",
  "groups": {
    "pn_group_a": {
      "selected_count": 2,
      "completed_count": 1,
      "failed_count": 0,
      "last_selected_at": "..."
    }
  },
  "recorded_rounds": {
    "round-id": {
      "group": "pn_group_a",
      "status": "started"
    }
  }
}
```

`recorded_rounds` 用于保证 resume 和重试不会重复累计同一个 round。

### 8.3 写入时机

- Planner 加载状态快照，并在内存中模拟后续 round 的选择次数。
- `plan-batch` 不写动作组状态。
- `run-batch` 在某个 round 的第一个 task 真正开始执行时，原子记录该 round，并增加一次 `selected_count`。
- round 内全部 task 成功后增加 `completed_count`。
- round 内存在最终失败 task 时增加 `failed_count`。
- resume 遇到已登记 round 时不重复增加 `selected_count`。

状态写入采用临时文件加原子替换，避免进程中断留下半个 JSON。

### 8.4 `--fresh`

`--fresh` 清理整个 run directory，因此同时重置动作组状态。普通重新运行和 `resume-batch` 保留状态。

## 9. 任务元数据

每个 `BatchTask.source` 增加或统一以下字段：

```json
{
  "round_id": "...",
  "round_index": 0,
  "character": "...",
  "action_group": "pn_group_a",
  "action_group_strategy": "balanced_random",
  "action_group_selected_count": 1,
  "action_index_in_group": 0,
  "action_count_in_group": 3,
  "action_group_total_actions": 17,
  "action_selection": "random_preserve_order",
  "actions_per_group": 3
}
```

不再把 record 文件路径作为业务 source 的必要字段。报告只关心组名、轮次和选择结果。

## 10. 日志与报告

Planner 的 info 日志记录：

```text
round=12 character=homura group=pn_group_a previous_count=2 selected=3 total=17
```

Runner 的 info 日志记录：

```text
round started round_id=... group=pn_group_a state_count=3
round completed round_id=... succeeded=3 failed=0
```

Batch 报告增加：

- 总 round 数。
- 每个角色的 round 数。
- 每个动作组的 selected/completed/failed 次数。
- 每个 round 实际抽中的动作数量。

## 11. 错误处理

- collection 展开后没有 action group：规划失败并指出 collection 名称。
- group 内没有动作：跳过该 group，并在 summary 中记录原因；所有 group 都为空时规划失败。
- `actions_per_group < 1`：配置校验失败。
- 不支持的 `action_selection`：配置校验失败。
- 状态 JSON 损坏：直接失败，不静默重置。
- 状态文件写入失败：停止当前 batch，避免调度次数与实际执行脱节。

## 12. 验收标准

### 12.1 Mock 业务验收

使用 `blackboard_action_new_manga_monochrome.yaml` 规划和 mock 执行至少 300 个 task：

- 约 99 个 `pn_*` 文件夹分别成为独立 group。
- 每个 round 最多产生 3 个 action task。
- 同一角色连续执行同一 group 的本轮动作。
- 一个 round 完成后切换到下一个角色。
- 抽中的动作是随机子集，但执行顺序与原目录 natural sort 一致。
- `balanced_random` 下各可用 group 的选择次数最大差值不超过 1。
- 多角色 action 仍通过现有 `relations.cp` 和候选角色补全逻辑处理。

### 12.2 状态验收

- `plan-batch` 前后 `state/action_groups.json` 内容不变。
- `run-batch --limit 1` 只记录实际开始的 round。
- 同一 round 的多个 task 只增加一次 selected count。
- `resume-batch` 不重复累计已记录 round。
- `--fresh` 后状态从零开始。

### 12.3 真实出图验收

选择 2 至 3 个 round 真实调用 NovelAI：

- artist、model、resolution、`nt=3` 与配置一致。
- 每轮角色、动作组和动作节点与 task source 一致。
- ScriptComposer、PromptPolicyPipeline、NovelAI Renderer 链路完整经过。
- 人工检查角色、动作和画风与旧 `run_tags_machine` 的业务效果相似。

## 13. 兼容边界

- `product`、`zip`、`prompt_list`、`manual` 不改变。
- 普通 `select.actions` collection 不改变。
- 显式 action group 默认继续使用组内全部动作。
- 既有 `action_group_record` 字段不再要求业务配置使用；实现阶段可以保留模型读取能力，但默认状态始终落到 run directory。
- AgentComposer 不经过 PromptPolicyPipeline 的行为不改变。
