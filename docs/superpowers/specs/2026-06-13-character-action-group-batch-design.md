# Character Action Group Batch 设计文档

## 背景

当前 batch 已经支持 `prompt_list`、`prompt_file`、`product`、`zip`、`manual` 等展开方式。它适合完整 prompt 批量跑图，也适合角色、动作、画风做全量组合。

新的需求来自旧 `blackboard.py` 的常用工作流：给定一个画风、多个角色、多个动作分类文件夹，每个角色只选择一组动作分类，然后把该分类下的动作全部跑完，再切换到下一个角色。

目标伪代码：

```python
for character in characters:
    action_group = strategy.choose(action_groups)
    for action in action_group.actions:
        run(character + action)
```

这不是旧项目兼容层，也不应该在 runner / composer / renderer 中做特殊处理。它应当作为 batch 的一种通用任务展开模式，最终仍然产出普通 `BatchTask`，下游 Composer、Renderer、Executor 不需要知道它来自 action group 调度。

## 目标

- 增加一个通用 batch 展开模式：`character_action_group`。
- 支持多个角色、多个动作分类文件夹。
- 每个角色选择一个动作分类，跑完该分类下所有动作后，再处理下一个角色。
- 支持三种动作分类选择策略：
  - `random`：随机选择，允许重复。
  - `ordered`：按顺序分配，组不够时循环。
  - `balanced_random`：优先选择历史使用次数最少的组，再在候选组中随机，参考旧 tags_machine action_record 的均衡思想。
- 选择结果、动作组、策略、record 路径进入 `BatchTask.source`，方便报告、续跑和问题排查。
- 完善 batch 运行日志，能看清当前角色、动作组、动作、进度、重试和产物路径。

## 非目标

- 不迁移旧提示词库。
- 不 import 旧 `blackboard.py`、`formula.py` 或旧运行时代码。
- 不把 action group 逻辑放进 AgentComposer、ScriptComposer、NovelAI renderer 或 execution 层。
- 不实现复杂条件调度，例如按角色标签过滤动作组、按动作难度加权、按生成质量反馈自动重排。
- 不要求 `character/action/background` 的 `explicit` 短名自动解析到旧 `design`。本功能优先使用绝对路径或相对 YAML 文件的路径。

## 推荐 YAML

```yaml
schema: tags-machine-core.batch/v1
name: blackboard-style-character-action-group
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: agent
  artist: 20260412
  nt: 1
  resolution: random_standard
  model: nai-diffusion-4-5-full
  cache_dir: cache/prompt

select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/.../character_a
        - F:/my_project/new/tags_machine/design/角色/.../character_b
        - F:/my_project/new/tags_machine/design/角色/.../character_c

  action_groups:
    - name: st_rp
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_rp
      recursive: true

    - name: st_sfw
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_sfw
      recursive: true

    - name: st_foot
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_foot
      recursive: true

expand:
  mode: character_action_group
  action_group_strategy: balanced_random
  action_group_record: cache/batch/action_group_record.json
  seed: 20260613

run:
  resume: true
  stop_on_error: false
  retry:
    max_attempts: 3
```

展开结果示例：

```text
character_a -> st_rp  -> st_rp/01_xxx, st_rp/02_xxx, st_rp/03_xxx ...
character_b -> st_sfw -> st_sfw/01_xxx, st_sfw/02_xxx, st_sfw/03_xxx ...
character_c -> st_foot -> st_foot/01_xxx, st_foot/02_xxx, st_foot/03_xxx ...
```

## BatchSpec 契约变化

### `select.actions` 与 `select.action_groups` 的关系

`select.actions` 保留原语义，不被 `ActionGroupSelector` 替代。两者按 `expand.mode` 分流：

```text
expand.mode = product / zip
  -> 解析 select.characters
  -> 解析 select.actions
  -> 解析 select.artists / select.backgrounds
  -> 产出普通 BatchTask

expand.mode = character_action_group
  -> 解析 select.characters
  -> 解析 select.action_groups
  -> ActionGroupStrategy 为每个 character 选择一个 group
  -> 展开该 group 内的 actions
  -> 产出普通 BatchTask
```

因此：

- 原有 `select.actions` + `expand.mode: product` / `zip` 行为不改变。
- 新增 `select.action_groups` 只服务 `expand.mode: character_action_group`。
- `character_action_group` 模式必须配置 `select.action_groups`。
- `character_action_group` 模式不允许同时配置 `select.actions`，第一版直接报错，避免用户误以为会把动作池和动作组混合。
- 非 `character_action_group` 模式如果配置了 `select.action_groups`，第一版也直接报错，避免静默忽略。

这个分流规则保证 action group 是 batch 规划层能力，不会污染现有 selector、composer、renderer 或 execution 链路。

### `select.action_groups`

新增 `select.action_groups`，每一项是命名动作组。它复用现有 selector 能力，但必须有 `name`。

字段：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `name` | 是 | 动作组名，例如 `st_rp`、`st_sfw`。会进入 `task.source.action_group`。 |
| `selector` | 是 | 当前建议支持 `folder`、`collection`、`glob`、`explicit`。 |
| `root` | 视 selector 而定 | `folder` 用，动作分类目录。 |
| `refs` | 视 selector 而定 | `explicit` 用，直接列动作节点。 |
| `pattern` | 视 selector 而定 | `glob` 用。 |
| `recursive` | 否 | 是否递归扫描动作节点。 |
| `node_files` | 否 | 判断动作节点目录的文件名列表，沿用默认 `meta.yaml`、`node.yaml`、`tags.txt`。 |
| `include` / `exclude` | 否 | 过滤动作节点。 |
| `limit` | 否 | 限制该动作组最多取多少动作。 |
| `shuffle` | 否 | 是否打乱该动作组内部动作顺序。 |

不建议把 `action_groups` 放到顶层 `collections` 里强行复用，因为这里的业务语义是“候选动作组池”，不是普通动作列表。

### `expand`

`ExpandMode` 增加：

```python
character_action_group
```

新增字段：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `action_group_strategy` | `balanced_random` | 动作组选择策略：`random`、`ordered`、`balanced_random`。 |
| `action_group_record` | `null` | `balanced_random` 的历史记录文件。为空时使用临时内存记录，只在本次 plan 内均衡。相对路径按当前运行目录解析，和 `cache_dir` / `output_root` 一样属于运行态路径。 |
| `seed` | `null` | 让 `random` / `balanced_random` 可复现。 |

### `BatchTask.source`

`character_action_group` 产出的任务仍然是普通 `BatchTask`，但 `source` 增加调度信息：

```json
{
  "character": "F:/.../character_a",
  "action": "F:/.../st_rp/01_xxx",
  "artist": "20260412",
  "background": null,
  "action_group": "st_rp",
  "action_group_strategy": "balanced_random",
  "action_group_record": "cache/batch/action_group_record.json",
  "action_group_index": 0,
  "action_index_in_group": 0,
  "action_count_in_group": 37
}
```

## 策略语义

### `random`

每个角色从所有 action group 中随机选择一个。允许多个角色选到同一组。

适合想要随机探索、不关心均衡覆盖的批量。

### `ordered`

按角色顺序轮流分配 action group。

示例：

```text
角色A -> st_rp
角色B -> st_sfw
角色C -> st_foot
角色D -> st_rp
```

适合想要确定性批量、人工容易预期的场景。

### `balanced_random`

读取 `action_group_record`，找到历史 `selected_count` 最小的动作组，只在这些最少使用组中随机选择。每次为一个角色选定动作组后，立刻把该组 `selected_count + 1` 写回 record，避免同一批次后续角色继续重复抽到同一组。

如果 record 不存在，从空记录开始。

如果多个组次数相同，则在这些组中随机。

如果 `seed` 存在，则相同输入、相同 record 状态下选择结果可复现。

这等价于“随机 + 尽量不可重复”：一轮所有组都选过后，才进入下一轮。

## ActionGroupRecord

建议文件结构：

```json
{
  "schema": "tags-machine-core.action-group-record/v1",
  "updated_at": "2026-06-13T00:00:00+00:00",
  "groups": {
    "st_rp": {
      "selected_count": 2,
      "completed_count": 2,
      "failed_count": 0,
      "last_selected_at": "2026-06-13T00:00:00+00:00"
    },
    "st_sfw": {
      "selected_count": 1,
      "completed_count": 1,
      "failed_count": 0,
      "last_selected_at": "2026-06-13T00:00:00+00:00"
    }
  }
}
```

字段语义：

| 字段 | 含义 |
| --- | --- |
| `selected_count` | 该动作组被分配给角色的次数。用于 balanced random 选择。 |
| `completed_count` | 该动作组对应的角色批次全部任务成功或结束后累计。第一版可以只在整组没有失败时增加。 |
| `failed_count` | 该组执行中出现失败的次数。 |
| `last_selected_at` | 最近一次被选中时间。 |

第一版选择策略只依赖 `selected_count`。`completed_count` / `failed_count` 用于后续 UI、报告和质量分析。

## 架构设计

### 组件

```text
BatchSpec
  -> BatchSelect.actions           # 原有动作池，服务 product / zip
  -> BatchSelect.action_groups
  -> ExpandConfig.character_action_group fields

BatchPlanner
  -> 按 expand.mode 分流
  -> product / zip: 复用 select.actions
  -> character_action_group: 使用 ActionGroupResolver + ActionGroupStrategy
  -> BatchTask[]

BatchRunner
  -> 执行普通 BatchTask
  -> 写 status / manifest / report
  -> 记录 action group lifecycle 日志

BatchExecutor
  -> 不感知 action group
  -> 继续处理普通 character + action + artist
```

### 新增内部模块建议

在 `src/tags_machine_core/batch/` 下新增：

```text
action_groups.py
```

职责：

- 定义 `ActionGroupSpec`、`ResolvedActionGroup`、`ActionGroupRecord`。
- 解析 `select.action_groups`。
- 实现 `ActionGroupStrategy`。
- 读写 `action_group_record`。

这样 `planner.py` 不会继续膨胀，selector 也不用理解“动作组调度”的业务语义。

### 改动模块清单

第一版预计只改动 refactor 的 batch、文档、示例和测试：

| 模块 | 改动 |
| --- | --- |
| `src/tags_machine_core/batch/models.py` | 增加 `select.action_groups`，扩展 `ExpandMode`，给 `ExpandConfig` 增加 action group 策略字段。 |
| `src/tags_machine_core/batch/action_groups.py` | 新增模块，负责 action group 解析、策略选择、record 读写。 |
| `src/tags_machine_core/batch/planner.py` | 增加 `character_action_group` 分支，按角色选择动作组并展开成普通 `BatchTask`。 |
| `src/tags_machine_core/batch/runner.py` | 补充业务日志：任务进度、角色、动作组、动作、重试、图片路径、组完成摘要。 |
| `src/tags_machine_core/batch/report.py` | 报告中展示 `source.action_group`、`source.character`、`source.action` 等来源字段，保持旧 report 兼容。 |
| `tests/test_batch_generation.py` | 补规划层和策略层覆盖：`ordered`、`random + seed`、`balanced_random + record`、冲突校验。 |
| `examples/batches/character_action_group_20260412.yaml` | 新增最小业务示例。 |
| `docs/batch_generation_readme.md` | 增加新模式的 YAML 字段、使用方式、日志说明和输出结构说明。 |
| `docs/superpowers/specs/2026-06-13-character-action-group-batch-design.md` | 保持本设计文档与实现同步。 |

明确不改动：

- AgentComposer / ScriptComposer。
- NovelAI renderer / execution。
- 旧 `tags_machine` 项目代码。
- `prompt_list`、`prompt_file`、`product`、`zip`、`manual` 的既有语义。

### 数据流

```text
load_batch_spec
-> BatchSpec.model_validate
-> BatchPlanner.plan
   -> if mode in product / zip:
        resolve select.actions
        build existing task matrix
   -> if mode == character_action_group:
        resolve characters
        resolve artists
        resolve backgrounds
        resolve action_groups
        validate select.actions is empty
        for each character:
          selected_group = strategy.choose(action_groups)
          for action in selected_group.actions:
            build BatchTask(nodes=[character, action, artist], source={...})
-> BatchRunner.run_tasks
-> BatchExecutor.execute
-> GenerationService / Composer / Renderer / NovelAI execution
```

## 日志设计

默认日志级别仍保持 `error`。批量跑图建议显式使用：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\xxx.yaml --log-level info --full
```

新增 info 日志：

```text
batch plan action_groups resolved groups=3 characters=12 strategy=balanced_random
action group selected character=character_a group=st_rp strategy=balanced_random action_count=37 selected_count=3
batch task started index=1/37 character=character_a action=01_xxx group=st_rp composer=agent resolution=portrait nt=1
batch task succeeded task_id=... image_count=1 images=[...]
batch task retry scheduled task_id=... attempt=1/3 delay=2 error=...
action group completed character=character_a group=st_rp succeeded=36 failed=1
action group record updated path=cache/batch/action_group_record.json group=st_rp selected_count=3
```

trace 日志可包含：

- resolved node 完整路径。
- prompt preview。
- render params 摘要。
- action group record 原始内容和写回内容。

warning / error：

- action group 为空。
- record 文件无法解析。
- record 写回失败。
- 某组动作全部失败。

## 错误处理

- `expand.mode: character_action_group` 但没有 `select.characters`：直接报错。
- 没有 `select.action_groups`：直接报错。
- `character_action_group` 模式同时配置了 `select.actions`：直接报错。
- 非 `character_action_group` 模式配置了 `select.action_groups`：直接报错，提示改用 `character_action_group` 或删除 `select.action_groups`。
- action group 缺少 `name`：直接报错。
- action group 解析后动作数为 0：直接报错，错误中包含 group name 和 root/pattern。
- `action_group_strategy` 不在允许范围：直接报错。
- `balanced_random` record JSON 损坏：默认失败，不静默重置，避免历史记录被误覆盖。
- record 写回失败：任务规划失败，不继续运行。因为继续运行会破坏“少跑优先”的语义。

## 和现有模式的关系

- `product`：仍用于角色 × 动作 × artist 全量组合。
- `zip`：仍用于按索引配对。
- `prompt_list` / `prompt_file`：仍是完整 prompt 主链路。
- `manual`：仍用于完全手写任务。
- `character_action_group`：用于“每个角色选择一组动作分类，再跑完该组动作”。

该模式只影响 `BatchPlanner` 阶段。产出的 `BatchTask` 和其他模式一致，因此不会影响 AgentComposer 稳定链路。

字段选择建议：

```yaml
# 全量组合旧模式：继续用 select.actions
select:
  actions:
    - selector: folder
      root: F:/.../动作改2/st_rp
      recursive: true
expand:
  mode: product

# 每个角色抽一个动作分类：使用 select.action_groups
select:
  action_groups:
    - name: st_rp
      selector: folder
      root: F:/.../动作改2/st_rp
      recursive: true
expand:
  mode: character_action_group
```

## 示例任务展开

输入：

```yaml
characters: [A, B, C, D]
action_groups: [st_rp, st_sfw, st_foot]
strategy: ordered
```

动作数量：

```text
st_rp: 3
st_sfw: 2
st_foot: 4
```

输出任务顺序：

```text
A + st_rp/01
A + st_rp/02
A + st_rp/03
B + st_sfw/01
B + st_sfw/02
C + st_foot/01
C + st_foot/02
C + st_foot/03
C + st_foot/04
D + st_rp/01
D + st_rp/02
D + st_rp/03
```

## 验收标准

### 配置与规划验收

- `plan-batch` 能读取 `character_action_group` YAML 并输出正确任务数。
- `ordered` 任务顺序和预期一致。
- `random` 在固定 `seed` 下结果可复现。
- `balanced_random` 能读取 record，并优先选择 `selected_count` 最小的组。
- `balanced_random` 在规划后写回 record。
- `BatchTask.source` 包含 action group 调度信息。

### 真实业务验收

真实 NovelAI 出图优先于纯接口测试。最小业务验收：

- 准备 2 个角色、3 个动作组，每个动作组至少 2 个动作。
- 使用 `balanced_random` 跑一次 `run-batch --limit` 或小批次完整运行。
- 验证每个角色只绑定一个 action group。
- 验证同一角色下动作组内动作连续执行。
- 验证输出图片可打开，PNG 参数可读取。
- 验证 `report.md` 和日志能看出 character、action_group、action、image path。

### 回归边界

- `prompt_list`、`prompt_file`、`product` 原有模式不改变。
- AgentComposer 不经过 PromptPolicyPipeline 的现有稳定行为不改变。
- NovelAI renderer 不新增 action group 判断。
- 旧 `tags_machine` 目录不写入新架构文件。

## 开发任务建议

1. 更新 batch 数据模型：
   - `BatchSelect` 增加 `action_groups`。
   - `ExpandMode` 增加 `character_action_group`。
   - `ExpandConfig` 增加 `action_group_strategy`、`action_group_record`、`seed`。

2. 新增 `batch/action_groups.py`：
   - 解析 action group。
   - 实现三种策略。
   - 实现 record 读写。

3. 更新 `BatchPlanner`：
   - 增加 `_plan_character_action_group`。
   - 产出普通 `BatchTask`。
   - 在 `source` 写入调度元数据。

4. 更新日志：
   - planner 输出 action group 选择日志。
   - runner 输出任务进度、图片路径、重试信息。
   - report 保持兼容，但可以显示 `source.action_group`。

5. 更新文档和示例：
   - `docs/batch_generation_readme.md` 增加新模式说明。
   - 新增 `examples/batches/character_action_group_20260412.yaml`。

6. 业务验证：
   - 先 `plan-batch --full` 检查任务展开。
   - 再真实 NovelAI 小批次出图。
   - 把结果记录到 `docs/batch_generation_business_test_*.md`。

## 待确认点

第一版建议如下：

- 默认策略：`balanced_random`。
- `balanced_random` 每次为角色选中动作组后立即更新 `selected_count`。
- record 损坏时直接失败，不自动重置。
- `completed_count` / `failed_count` 第一版只记录整组执行后的摘要，不参与选择。
- `action_groups` 放在 `select` 下，不复用 `collections.actions`。
