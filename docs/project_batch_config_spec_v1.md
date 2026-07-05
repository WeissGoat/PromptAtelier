# Project Batch Config Spec v1

本文档定义 batch 的项目级配置中心。目标是让日常批量跑图配置从“写底层 selector”变成“引用项目枚举”，同时保留现有 `BatchSpec`、`BatchPlanner`、Composer、Renderer 的边界。

## 目标

- 使用 `require` 引入项目配置片段。
- 项目配置片段可以保存工程默认值，也可以保存业务枚举。
- batch 文件可以继续使用完整 `select` / `expand`。
- batch 文件也可以使用更短的 `batch` 简写。
- `require` 和 `batch` 简写只在配置读取层展开，后续模块仍然接收普通 `BatchSpec`。

## 加载顺序

```text
内建默认值
-> require[0]
-> require[1]
-> ...
-> 当前 batch.yaml
-> batch 简写展开结果
```

`require` 按顺序加载。后面的配置覆盖前面的配置。当前文件永远最后覆盖被 require 的配置。

## 合并规则

- 标量：后者覆盖前者。
- 对象：递归合并。
- 数组：整体替换。
- `require` 只负责加载，不参与最终 `BatchSpec` 运行。
- `require` 必须显式写出路径，不做隐式自动发现。
- `require` 禁止循环引用。

示例：

```yaml
# project/base.yaml
defaults:
  backend: novelai
  nt: 1
  resolution: random_standard
collections:
  characters:
    madoka_main:
      - F:/my_project/new/tags_machine/design/角色/...
```

```yaml
# batch.yaml
require:
  - ../project/base.yaml

defaults:
  nt: 3

batch:
  characters: madoka_main
```

最终 `defaults.backend` 和 `defaults.resolution` 保留，`defaults.nt` 变成 `3`，`batch.characters` 展开成 `select.characters` 的 collection selector。

## 项目级配置内容

项目级配置片段使用普通 batch YAML 字段，不引入新的根 schema。

推荐放入：

- `config`
- `work_root`
- `output_dir`
- `defaults`
- `collections`
- `expand` 默认策略
- `run` 默认运行策略
- `archive` 默认归档策略
- `report` 默认报告策略

不推荐放入：

- 一次性 prompt。
- 临时调试输出目录。
- 只适合某一次任务的 `select` 明细。

## collections

`collections` 是项目级业务枚举。现有 selector 已经支持 `collection`，因此无需新增 Planner 逻辑。

```yaml
collections:
  characters:
    madoka_main:
      - F:/my_project/new/tags_machine/design/角色/danbooru_mahou_shoujo_madoka_magica

  actions:
    st_rp:
      - F:/my_project/new/tags_machine/design/动作改2/new
    st_sfw:
      - F:/my_project/new/tags_machine/design/动作改2/st_sfw

  artists:
    nai4_common:
      - "20260412"
      - "20260412_2"
```

`characters` 和 `actions` 的值是目录路径。`artists` 的值是 artist ref。
纯数字或包含下划线的 artist ref 建议始终加引号，避免 YAML 把 `20260412_2` 当数字解析。

collection 的值也可以使用表达式，适合维护类似旧 `nai_const.py` 的动态动作组：

```yaml
collections:
  actions:
    action_new:
      - selector: folder
        root: F:/my_project/new/tags_machine/design/动作改2
        include:
          names:
            - pn_*

    action_body:
      - collection: action_body_show
      - collection: action_body_ero
      - collection: action_other
```

collection item 支持三种形式：

- 字符串：按目录路径展开。
- `selector` 对象：复用普通 selector 语义，例如 `folder` + `include.names`。
- `collection` 对象：引用同类型 collection，展开后合并去重。

collection 引用会检测循环引用，例如 `a -> b -> a` 会直接报错。

### 旧 nai_const 动作组

`examples/project/nai_const_action_groups.yaml` 复刻旧 `nai_const.py` 中常用 action group。它只保存动作组枚举，不保存账号、vibe、运行状态或旧全局开关。

常用组：

- `action_ft`：足部/脚部相关动作。
- `action_body_show`：身体展示、擦边展示。
- `action_body_ero`：身体 erotica 相关动作。
- `action_body`：`action_body_show + action_body_ero + action_other`。
- `action_mouth`：嘴部、亲吻、口部相关动作。
- `action_dress`：换装/衣服动作。
- `action_dress_topic`：`st_clothes_topic*` 目录。
- `action_sfw`：安全或轻度展示动作。
- `action_sex_type`：旧基础 sex 类型动作。
- `action_sex_stand`：站姿 sex 扩展动作。
- `action_sex_new_type`：旧新增 sex 类型动作。
- `action_sex_story`：旧 story sex 动作。
- `action_sex_misc`：旧 misc sex 动作。
- `action_sex`：旧 `ACTION_SEX` 的组合版本。
- `action_2girl`：双女相关动作。
- `action_other`：`st_other*` 目录。
- `action_prepare`：`st_prepare*` 目录。
- `action_new`：`pn_*` 目录。
- `select_action`：旧 `SELECT_ACTION_LIST` 的组合版本。

使用示例：

```yaml
require:
  - ../project/base.yaml
  - ../project/collections.yaml
  - ../project/nai_const_action_groups.yaml

batch:
  characters: special_next_select
  action_groups: action_sex
  artist: "20260412"
  auto_num: true
```

`special_next_select` 这类角色组可以直接作为 character collection 指向旧 design 目录。只要目录下的子目录包含 `meta.yaml`、`node.yaml` 或 `tags.txt`，现有 folder selector 就会发现它们。

## resolution

batch 默认支持这些尺寸别名：

| 名称 | 尺寸 | 来源 |
| --- | --- | --- |
| `square` / `normal_square` | `1024x1024` | 旧 `Resolution.NORMAL_SQUARE` |
| `landscape` / `normal_landscape` | `1216x832` | 旧 `Resolution.NORMAL_LANDSCAPE` |
| `portrait` / `normal_portrait` | `832x1216` | 旧 `Resolution.NORMAL_PORTRAIT` |
| `random_standard` | 从上面三种随机选择 | 旧 `PRESET_LIST` |

## batch 简写

`batch` 是更高层的日常跑图入口。它在读取层展开成现有 `defaults`、`select` 和 `expand` 字段。

```yaml
batch:
  mode: blackboard_rounds
  characters: madoka_main
  action_groups:
    - st_rp
    - st_sfw
  artist: "20260412"
  composer: script
  strategy: balanced_random
  auto_num: true
  action_group_record: cache/action_groups/madoka.json
```

展开结果等价于：

```yaml
defaults:
  artist: 20260412
  composer: script

select:
  characters:
    - selector: collection
      name: madoka_main
  action_groups:
    - name: st_rp
      selector: collection
    - name: st_sfw
      selector: collection

expand:
  mode: blackboard_rounds
  action_group_strategy: balanced_random
  action_group_record: cache/action_groups/madoka.json
  auto_num: true
```

## 简写字段

| 字段 | 展开位置 | 含义 |
| --- | --- | --- |
| `mode` | `expand.mode` | 展开模式，默认 `blackboard_rounds` |
| `characters` | `select.characters` | 字符串或数组，默认按 character collection 名称解析 |
| `action_groups` | `select.action_groups` | 字符串或数组，默认按 action collection 名称解析 |
| `artists` | `select.artists` | 字符串或数组，默认按 artist collection 名称解析 |
| `artist` | `defaults.artist` | 单个 artist ref |
| `composer` | `defaults.composer` | `full` / `agent` / `script` |
| `nt` | `defaults.nt` | 每个任务生成张数 |
| `resolution` | `defaults.resolution` | 尺寸预设 |
| `model` | `defaults.model` | 后端模型 |
| `strategy` | `expand.action_group_strategy` | 动作组选择策略 |
| `max_tasks` | `expand.max_tasks` | 最大任务数 |
| `auto_num` | `expand.auto_num` | `blackboard_rounds` 自动按角色选择动作组并跑完整组 |
| `action_group_record` | `expand.action_group_record` | 动作组均衡记录 |
| `allow_fill_missing_cp_from_candidates` | `expand.allow_fill_missing_cp_from_candidates` | 多角色动作缺 CP 时是否从候选角色补齐 |

## 兼容边界

- `batch` 简写不影响 AgentComposer。
- `batch` 简写不影响 ScriptComposer。
- `batch` 简写不改变 `BatchTask` 结构。
- 已有完整 `select` / `expand` YAML 继续可用。
- 如果简写和完整字段同时写，同名目标字段以后展开的简写为准。为了避免误解，建议一个文件里只选一种写法。

## 验收

- `load_batch_spec()` 能递归加载 `require`。
- `require` 循环引用会报错。
- 标量、对象、数组按本文档规则合并。
- `batch.characters` 和 `batch.action_groups` 能展开成 collection selector。
- `batch.auto_num` 能展开成 `expand.auto_num`。
- 现有 `plan-batch` / `run-batch` 不需要感知 `batch` 简写。

## auto_num

`auto_num` 用于 `blackboard_rounds`。它表示“不手填任务数”，由 Planner 按角色自动展开：

```text
for character in characters:
    action_group = strategy.choose(action_groups)
    for action in action_group.actions:
        plan(character, action)
```

如果同时设置 `max_tasks`，`max_tasks` 只作为上限，Planner 达到上限后立即停止。

真实运行时，任务开始、跳过、完成日志会包含 `character`、`group`、`action`，方便看当前批量跑到哪个组合。
