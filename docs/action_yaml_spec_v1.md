# Action meta.yaml 规范 v1

本文档正式定义 `action` 节点的 `meta.yaml` 结构。

当前结论：action 只描述“动作提示词素材”和“这个动作应采用的角色素材裁剪视角”。它不保存通用过滤规则，不拆 `pose` / `camera` / `focus`，也不携带任何 NovelAI / ComfyUI / SD 生图参数。

## 设计边界

action v1 解决一个明确问题：

```text
composer 需要知道：
这个动作本身有哪些正向/负向素材；
以及它应该按哪种 character_scope 选择 character tags。
```

因此 action 节点只声明：

```yaml
character_scope: foot_detail
```

`foot_detail` 具体要保留 `feet / legwear`，并过滤 `hair / eyes / upper_clothes`，这是 composer policy 的职责，不写进每个 action `meta.yaml`。

## 文件约定

- 文件名固定为 `meta.yaml`。
- schema 固定为 `tags-machine.action/v1`。
- `kind` 固定为 `action`。
- 节点目录名通常和 `id` 一致。
- `validate-node-tree` 会把 action 使用 `node.yaml` 视为 v1 契约错误。

推荐目录：

```text
nodes/
  actions/
    foot_closeup/
      meta.yaml
```

## 最小合法结构

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup
description: "脚部局部特写动作。"

tags:
  action: >-
    foot focus, soles toward viewer

negative_prompt: []

character_scope: foot_detail
```

最小结构必须满足：

- `schema`、`kind`、`id` 存在且匹配 v1。
- `tags` 是 mapping。
- `tags.action` 非空。
- `character_scope` 非空；不需要特殊裁剪时写 `default`。

## 推荐完整结构

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup
description: "脚部局部特写动作。"

tags:
  action: >-
    foot focus, soles toward viewer, toes spread, (detailed feet:1.2)

negative_prompt: >-
  face focus, full body, extra toes

character_scope: foot_detail

agent:
  summary: "脚部近景动作。外部 agent 组合完整 prompt 时应优先表达脚部、脚底、脚趾和近景镜头。"
  labels:
    - action
    - foot_detail

legacy:
  source_file: "F:/my_project/new/tags_machine/design/动作改2/..."
  raw_lines: []
  raw_sections: {}
```

`agent` 和 `legacy` 都是可选元数据。它们不能承载通用过滤规则，也不能改变 composer 的结构化行为。

## 字段表

| 字段 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- |
| `schema` | 是 | string | 固定为 `tags-machine.action/v1`。 |
| `kind` | 是 | string | 固定为 `action`。 |
| `id` | 是 | string | 动作节点 id，推荐使用目录名。 |
| `description` | 否 | string | 给人和外部 agent 看的动作摘要，不参与规则判断；手写 action 时优先使用它。 |
| `name` | 否 | string | 兼容/显示字段。通常可省略，UI 可从 `id` 派生名称；不要同时把 `name` 和 `description` 写成重复内容。 |
| `tags.action` | 是 | string 或 list[string] | 正向动作素材。长动作 prompt 推荐用单个字符串；短标签或迁移产物可以用 list。 |
| `negative_prompt` | 否 | string 或 list[string] | 动作级负向素材；缺省等价于空数组。长负向 prompt 推荐用单个字符串。 |
| `character_scope` | 是 | string | 角色素材裁剪视角；脚本 composer 用它执行 section 选择，agent composer 用它作为任务语义、缓存和 meta。 |
| `agent` | 否 | object | 外部 agent 可读的摘要、标签等辅助信息；不是规则。 |
| `legacy` | 否 | object | 迁移审计信息；只记录旧来源，不参与 composer 决策。 |

## tags.action

`tags.action` 是 action v1 唯一正式的正向动作素材 section。

动作 prompt 往往是一段较长、已经调过权重和顺序的文本。手写 action v1 时，推荐把它保存为单个字符串：

```yaml
tags:
  action: >-
    sitting, foot focus, soles toward viewer, low angle close-up,
    (detailed feet:1.2)
```

短动作或迁移产物也允许使用 list：

```yaml
tags:
  action:
    - "sitting"
    - "foot focus"
    - "soles toward viewer"
```

两种写法都会被 reader 归一化成动作素材列表。区别只在维护体验：

- 长字符串更适合保留动作 prompt 的原始顺序、逗号结构和权重组合。
- list 更适合少量短 tag，或迁移工具从旧 `tags.txt` 拆出来后人工复核。

不推荐把动作拆成多个结构字段：

```yaml
pose:
  - "sitting"
camera:
  - "low angle"
focus:
  - "foot focus"
```

原因是当前 composer 不消费 `pose`、`camera`、`focus` 这些细分结构。提前拆分只会增加维护成本，并且容易让规则分散到节点里。

如果旧素材迁移时保留了历史分组，`NodeReader` 可以兼容读取，但 v1 正式节点应收敛到 `tags.action`。需要新增正式 section 时，必须先说明消费方，再进入 action v2。

## negative_prompt

`negative_prompt` 表示动作自带的负向素材。

它不是最终完整 negative prompt。composer 会把它和 character / background / 显式 negative 等素材合并进 `PromptBundle.prompt.negative`，后续 adapter 再叠加 style 和后端相关 negative。

长负向 prompt 推荐使用字符串：

```yaml
negative_prompt: >-
  bad feet, extra toes, face focus
```

短负向 tag 或迁移产物可以使用 list：

```yaml
negative_prompt:
  - "bad feet"
  - "extra toes"
```

没有动作级负向素材时写：

```yaml
negative_prompt: []
```

## character_scope

`character_scope` 是 action v1 最重要的结构化字段。

它不是 prompt tag，而是 composer 的裁剪视角标识：

```yaml
character_scope: foot_detail
```

推荐枚举：

| scope | 含义 |
| --- | --- |
| `default` | 默认角色展示，不做特殊裁剪。 |
| `full_body` | 全身可见。 |
| `upper_body` | 上半身为主。 |
| `lower_body` | 下半身为主。 |
| `portrait` | 头像、脸部或偏头部半身。 |
| `face_detail` | 脸部局部特写。 |
| `hand_detail` | 手部局部特写。 |
| `foot_detail` | 脚部局部特写。 |
| `object_focus` | 道具或非角色主体为主，角色信息应弱化。 |

不确定时使用 `default`，不要临时发明 scope。新增 scope 必须同时更新 composer policy、验收样例和文档。

### 消费语义

- 脚本 composer / `run-action`：默认使用 `action.character_scope` 执行 character section include/suppress。
- AgentComposer：默认从 `action.character_scope` 推导任务 scope，用于 agent task 语义、cache key 和 `PromptBundle.meta.composition`。AgentComposer 本身不执行 character tag 过滤。
- 完整 prompt 的 `run-prompt`：输入已经是完整角色 + 动作 prompt，不读取 action 节点，因此不使用 `character_scope`。
- `--character-scope`：只作为临时覆盖/调试参数，优先级高于 action；正常素材库应以 action `meta.yaml` 为准。

## agent

`agent` 是可选辅助元数据，用于让外部 agent 更容易理解动作节点。

允许内容：

```yaml
agent:
  summary: "脚底极近景动作，强调脚底、脚趾和近景镜头。"
  labels:
    - action
    - foot_detail
```

禁止把通用规则写进 `agent`，例如：

```yaml
agent:
  suppress_character_sections:
    - hair
    - eyes
```

这类规则属于 composer policy。否则同一个 scope 会在多个 action 里重复，后续很难维护。

## legacy

`legacy` 只用于迁移和审计。

允许内容：

```yaml
legacy:
  source_file: "F:/my_project/new/tags_machine/design/动作改2/..."
  raw_lines:
    - "原始 tags.txt 行"
  raw_sections:
    gen_json:
      - "{\"steps\": 28}"
```

`legacy.raw_sections` 可以保留旧 `gen_json`、`node_artist`、`node_background` 等信息，但这些信息不会提升为 action v1 字段。后端参数应该进入 style / adapter / render request，不进入 action。

## 不允许的字段

action v1 不允许把规则、镜头拆解或后端参数写进节点。

明确禁止：

- `rules`
- `profiles`
- `include_scopes`
- `exclude_scopes`
- `shot`
- `constraints`
- `pose`
- `camera`
- `focus`
- `visible_parts`
- `character_sections`
- `include_character_sections`
- `suppress_character_sections`
- `renderers`
- `generation`
- `backend`
- `params`
- `style`
- `artist`
- `quality`
- `prompt`

其中 `prompt` 不用于 action v1，是因为 action 节点保存的是“动作素材”，不是最终可直接喂模型的完整 prompt。完整 prompt 应该由 composer 输出到 `PromptBundle.prompt`。

## Composer policy 示例

下面是 composer 层可以维护的策略示例，不属于 action `meta.yaml`：

```yaml
character_scope_policy:
  foot_detail:
    include_character_sections:
      - character
      - identity
      - copyright
      - role
      - body
      - feet
      - legwear
      - extra
    suppress_character_sections:
      - hair
      - eyes
      - face
      - headwear
      - upper_clothes
      - full_body_clothes
```

action 节点只写：

```yaml
character_scope: foot_detail
```

这样可以避免每个脚部特写 action 重复一份 `hair / eyes / upper_clothes` 过滤规则。

## YAML 引号规则

NovelAI / Danbooru 风格提示词里经常出现 `()`、`{}`、`[]`、`:`、`#`、`,` 等字符。

长 prompt 推荐用 YAML folded block `>-`。它会把换行折叠成空格，适合保存很长的逗号分隔提示词：

```yaml
tags:
  action: >-
    foot focus, soles toward viewer, (detailed feet:1.2),
    [[toes]], {best foot detail}
```

如果使用 list，建议每个 tag 字符串都加双引号，尤其是包含权重、冒号、方括号或花括号时。

推荐：

```yaml
tags:
  action:
    - "(detailed feet:1.2)"
    - "{best foot detail}"
    - "[[soles]]"
    - "soles, toes"
```

避免：

```yaml
tags:
  action:
    - {best foot detail}
    - [soles]
    - foot detail:1.2
```

原因：

- `{}` 在 YAML 中可能被解析成 flow mapping。
- `[]` 可能被解析成 flow sequence。
- 未加引号的 `:` 可能被当作 key/value 分隔。
- `#` 后面的内容可能被当作注释。
- `()` 本身通常安全，但为了权重 tag 的一致性也建议统一加引号。

## 旧 tags.txt 迁移

旧项目动作 `tags.txt` 常见形态是一整行逗号分隔 prompt，并在 `=` 后追加 `origin_uc`、`node_background`、`gen_json` 等扩展行。

迁移命令：

```powershell
uv run python -m tags_machine_core migrate-action-tags `
  F:\my_project\new\tags_machine\design\动作改2\next\17_20240706_1720261297 `
  --character-scope foot_detail `
  --output migrated\nodes\actions\foot_closeup\meta.yaml
```

迁移策略：

- 迁移工具为了便于人工复核，可能把正向 prompt 按顶层逗号拆成 `tags.action` list。
- 正式整理 action 节点时，可以把长动作 list 合并成一个 `tags.action` 字符串，减少 YAML 噪音并保留整体 prompt 语义。
- 括号、方括号、花括号内部的逗号不会被拆开，避免破坏 `(soles detailed:1.2,toenails)` 这类组合。
- `origin_uc`、`uc`、`negative_prompt`、`after_uc`、`after_negative_prompt` 提升为动作级 `negative_prompt`。
- `node_background`、`node_artist`、`gen_json` 等旧扩展只保留在 `legacy.raw_sections`。
- `character_scope` 优先通过 `--character-scope` 显式指定。
- 未显式指定时，迁移工具只做有限关键词推断，例如 `toes focus` / `soles` -> `foot_detail`，`pov hands` -> `hand_detail`；推断结果必须人工复核。

迁移工具不会修改旧 `tags_machine` 目录。只有传入 `--output` 时才写出新 YAML。

## 示例

### 脚底特写

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup
description: "脚底特写。"

tags:
  action: >-
    foot focus, soles toward viewer, toes spread

negative_prompt: >-
  face focus, full body, extra toes

character_scope: foot_detail
```

### 上半身站立

```yaml
schema: tags-machine.action/v1
kind: action
id: upper_body_standing
description: "上半身站立动作。"

tags:
  action: >-
    standing, upper body, looking at viewer

negative_prompt: []

character_scope: upper_body
```

### 普通动作

```yaml
schema: tags-machine.action/v1
kind: action
id: simple_sitting
description: "普通坐姿。"

tags:
  action: "sitting, relaxed pose"

negative_prompt: []

character_scope: default
```

## 与 character / PromptBundle 的关系

```text
character.meta.yaml
  tags.character / tags.hair / tags.eyes / tags.upper_clothes / tags.feet ...

action.meta.yaml
  tags.action
  negative_prompt
  character_scope

composer policy
  character_scope -> include/suppress character sections

PromptBundle
  prompt.positive
  prompt.negative
  meta.action_ref
  meta.composition.character_scope
  meta.composition.included_character_sections
  meta.composition.suppressed_character_sections
```

action 和 character 都只保存素材事实。真正的选择结果记录在 `PromptBundle.meta.composition`，用于调试、缓存、回放和验收。

## 校验门禁

结构化动作节点应通过：

```powershell
uv run python -m tags_machine_core validate-node-tree migrated\nodes --output migrated_node_validation.yaml
```

action v1 校验重点：

- 文件必须是 `meta.yaml`。
- `schema` 必须是 `tags-machine.action/v1`。
- `kind` 必须是 `action`。
- `tags` 必须是 mapping。
- `tags.action` 必须存在且非空。
- `character_scope` 必须存在且非空。
- 禁止 `rules`、`profiles`、`shot`、`constraints`、`pose`、`camera`、`focus`、`include_scopes`、`exclude_scopes` 等规则字段。

## v1 冻结点

- action 使用 `meta.yaml`。
- action 使用 `tags.action` 存正向动作素材；长动作 prompt 推荐写成字符串，list 作为短 tag 或迁移兼容形式。
- action 使用 `negative_prompt` 存动作级负向素材；长负向 prompt 推荐写成字符串，list 作为短 tag 或迁移兼容形式。
- `description` 是推荐的人类/agent 摘要字段；`name` 只作为兼容/显示字段，通常可省略。
- action 必须声明 `character_scope`。
- `character_scope` 的通用过滤规则只在 composer policy 维护。
- action 不拆 `pose` / `camera` / `focus`。
- action 不写 `meta.shot` / `constraints`。
- action 不写 style、quality、artist、generation、renderer、backend 参数。
- PromptBundle 才保存最终 prompt 和本次 composer 的实际选择结果。
