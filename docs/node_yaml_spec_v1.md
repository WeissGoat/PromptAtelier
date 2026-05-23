# Node YAML 规范总览 v1

本文档只定义节点体系的总体边界。具体节点格式会拆成独立规范：

- [Character YAML 规范](character_yaml_spec_v1.md)
- Action YAML 规范：待讨论
- Artist / Style YAML 规范：待讨论
- Background YAML 规范：待讨论

## 当前结论

节点 YAML 不应该把所有规则都写进每个节点。

更清晰的职责边界是：

```text
character：描述角色素材事实
action：描述动作和镜头事实
artist/style：描述画风素材和后端相关素材
composer：根据统一策略组合素材
adapter：根据后端生成 RenderRequest
```

例如：

```text
character.tags.hair = black_hair
character.tags.eyes = purple_eyes
action.shot.body_scope = foot_detail
composer policy = foot_detail 默认不取 hair / eyes / upper_clothes
```

这里的过滤逻辑属于 composer，不属于 character YAML。

## 文件约定

迁移期允许同一个节点目录同时存在：

```text
tags.txt      # 旧格式，继续兼容
meta.yaml     # 轻量结构化元数据，角色节点当前使用
node.yaml     # 通用结构化节点，后续用于 action/style/background 等
```

读取优先级建议：

1. `node.yaml`
2. `meta.yaml`
3. `tags.txt`

注意：`meta.yaml` 不表示“不重要”，只是说明它是轻量事实库格式。当前 character v1 就推荐使用 `meta.yaml`。

## 通用设计原则

- YAML 只存素材事实和必要元数据。
- 通用组合规则放在 composer 策略层。
- 后端强相关处理放在 adapter 层。
- `tags.txt` 在迁移期继续可用。
- 已经落地的 `design/角色/.../meta.yaml` 视为 character v1 的事实来源。
- agent 可以读取 YAML，但 agent 不应该把临时推理规则写回每个角色节点。

## 字段命名原则

### `tags`

`tags` 表示可用于正向提示词的素材分组。

它不是最终 prompt，而是 prompt material。

例如 character 中：

```yaml
tags:
  character:
    - akemi_homura
  hair:
    - black_hair
  eyes:
    - purple_eyes
```

composer 会根据 action 和策略决定最终取哪些 section。

### `negative_prompt`

`negative_prompt` 表示节点自带的负向提示词素材。

它也不是最终完整 negative prompt，而是会被 composer 合并进 `PromptBundle.prompt.negative`。

当前 character v1 保留这个字段名，因为它已经落地，并且对 agent 和生图链路都直观。

### `prompt`

`prompt` 保留给最终产物或特殊 raw prompt 节点。

character v1 不推荐使用：

```yaml
prompt:
  positive: ...
```

原因是 character 的内容还需要根据 action、shot、style 策略筛选，不是最终可直接喂模型的完整提示词。

## Character 当前状态

character v1 已确认：

- 使用 `meta.yaml`
- 使用 `schema: tags-machine.character/v1`
- 使用 `tags` 存正向素材分组
- 使用 `negative_prompt` 存角色级负向素材
- 不写 `rules`
- 不写 `profiles`
- 不写 `include_scopes` / `exclude_scopes`
- 不写通用镜头过滤规则

详细结构见 [Character YAML 规范](character_yaml_spec_v1.md)。

## Action 待讨论重点

action 节点不应该关心某个角色有哪些 section，但它需要提供足够清晰的镜头事实，让 composer 能选择 section。

下一步需要确认：

- action 用 `node.yaml` 还是 `meta.yaml`
- `shot.body_scope` 的枚举
- `shot.focus` 是否允许多值
- `visible_parts` 如何表达
- action 自己的正向素材仍叫 `tags` 还是叫 `prompt_material`
- action 的负向素材是否也叫 `negative_prompt`
- 是否需要 `intensity`、`contact`、`camera`、`composition` 等结构字段

目前倾向：

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup

tags:
  base:
    - foot_focus
    - soles
    - toes
  pose:
    - soles_toward_viewer
  camera:
    - close-up

shot:
  body_scope: foot_detail
  focus:
    - feet
  visible_parts:
    - feet
    - legs
```

这只是讨论草案，不作为冻结规范。

## YAML 引号规则

提示词中经常出现 `{}`、`[]`、`:`、`#`、`,` 等字符。建议这些字符串统一加引号。

推荐：

```yaml
tags:
  style:
    - "{best_quality}"
    - "[[artist:kedama_milk]]"
    - "dark_orb_(madoka_magica)"
```

避免：

```yaml
tags:
  style:
    - {best_quality}
    - [artist:kedama_milk]
```

原因是 YAML 可能把 `{}` 当 map，把 `[]` 当 list，把 `:` 当 key 分隔。

## PromptBundle 边界

所有节点最终都应由 composer 组合成统一的 `PromptBundle`：

```yaml
prompt:
  positive: "akemi_homura, bare_feet, foot_focus"
  negative: "extra_toes"
meta:
  character_ref: homura
  action_ref: foot_closeup
  shot:
    body_scope: foot_detail
```

`PromptBundle.prompt` 才是最终完整提示词。节点 YAML 只是输入素材。
