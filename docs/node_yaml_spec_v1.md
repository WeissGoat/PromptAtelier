# Node YAML 规范总览 v1

本文档只定义节点体系的总体边界。具体节点格式会拆成独立规范：

- [Character YAML 规范](character_yaml_spec_v1.md)
- [Action YAML 规范](action_yaml_spec_v1.md)
- [Style YAML 规范](style_yaml_spec_v1.md)
- [Background YAML 规范](background_yaml_spec_v1.md)

## 当前结论

节点 YAML 不应该把所有规则都写进每个节点。

更清晰的职责边界是：

```text
character：描述角色素材事实
action：描述动作素材和 character_scope
artist/style：描述画风素材和后端相关素材
composer：根据统一策略组合素材
adapter：根据后端生成 RenderRequest
```

例如：

```text
character.tags.hair = black_hair
character.tags.eyes = purple_eyes
action.character_scope = foot_detail
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

注意：`meta.yaml` 不表示“不重要”，只是说明它是轻量事实库格式。当前 character v1 和 action v1 都推荐使用 `meta.yaml`。

## 通用设计原则

- YAML 只存素材事实和必要元数据。
- 通用组合规则放在 composer 策略层。
- 后端强相关处理放在 adapter 层。
- `tags.txt` 在迁移期继续可用。
- 已经落地的 `design/角色/.../meta.yaml` 视为 character v1 的事实来源。
- agent 可以读取 YAML，但 agent 不应该把临时推理规则写回每个角色节点。
- `shot`、`constraints` 不是 v1 节点契约字段；reader 可以兼容忽略旧字段，但 composer 不会用它们决定角色裁剪。

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

action v1 也使用 `negative_prompt` 表示动作级负向素材。

### `prompt`

`prompt` 保留给最终产物或特殊 raw prompt 节点。

character v1 不推荐使用：

```yaml
prompt:
  positive: ...
```

原因是 character 的内容还需要根据 action 的 `character_scope`、composer 策略和 style 上下文筛选，不是最终可直接喂模型的完整提示词。

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

## Action 当前状态

action v1 已确认：

- 使用 `meta.yaml`
- 使用 `schema: tags-machine.action/v1`
- 使用 `tags.action` 存正向动作素材；长动作 prompt 推荐写成字符串，短 tag 或迁移产物可以用 list
- 使用 `negative_prompt` 存动作级负向素材；长负向 prompt 推荐写成字符串，短 tag 或迁移产物可以用 list
- 使用 `description` 作为人类/agent 摘要；`name` 通常可由 `id` 派生，不作为推荐必写字段
- 使用 `character_scope` 表示角色素材裁剪视角
- 不写角色 section include/suppress 规则
- 不提前拆 `pose` / `camera` / `focus`
- 不使用 `shot.body_scope` 或 `constraints` 作为 composer 输入

action 节点不应该关心某个角色有哪些 section。它只声明这个动作应使用哪种 `character_scope`。

示例：

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup
description: "脚底特写。"

tags:
  action: >-
    foot focus, soles toward viewer, toes spread

negative_prompt: >-
  extra toes, bad feet

character_scope: foot_detail
```

详细结构见 [Action YAML 规范](action_yaml_spec_v1.md)。

## Style 当前状态

style v1 已确认：

- 新结构化画风节点推荐使用 `node.yaml`
- 使用 `schema: tags-machine.style/v1`
- 使用 `kind: style`
- 使用 `tags` 存通用画风素材
- 使用 `negative_prompt` 存通用画风负向素材
- 使用 `renderers.novelai` / `renderers.comfyui` / `renderers.sd` 存后端专属配置
- 不写角色、动作、局部镜头裁剪规则

详细结构见 [Style YAML 规范](style_yaml_spec_v1.md)。

## Background 当前状态

background v1 已确认：

- 使用 `meta.yaml`
- 使用 `schema: tags-machine.background/v1`
- 使用 `kind: background`
- 使用 `tags` 存背景素材
- 使用 `negative_prompt` 存背景级负向素材
- 不写后端配置
- 不写角色 section include/suppress 规则

详细结构见 [Background YAML 规范](background_yaml_spec_v1.md)。

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
  composition:
    character_scope: foot_detail
    included_character_sections:
      - character
      - copyright
      - feet
    suppressed_character_sections:
      - hair
      - eyes
      - upper_clothes
```

`PromptBundle.prompt` 才是最终完整提示词。节点 YAML 只是输入素材。

这里不使用 `meta.shot.body_scope`，因为 v1 的动作节点已经直接声明 `character_scope`。`PromptBundle.meta.composition` 记录的是 composer 本次实际采用的裁剪结果，用来调试、缓存和回放，而不是再发明一套镜头字段。

## 校验门禁

迁移后建议先运行结构化节点校验：

```powershell
uv run python -m tags_machine_core validate-node-tree migrated\nodes --output migrated_node_validation.yaml
```

当前校验覆盖：

- `schema` / `kind` 必须匹配当前 v1 节点类型。
- character/action/background 使用 `meta.yaml`，style 使用 `node.yaml`。
- character/action/background/style 必须包含各自必需的 `tags` section。
- action 必须声明 `character_scope`。
- style 必须包含 `renderers.novelai`，因为当前正式生图主线只承诺 NovelAI。
- v1 节点不能写入 `rules`、`profiles`、`shot`、`constraints`、`include_scopes` / `exclude_scopes` 等规则字段。

`validate-node-tree` 失败时退出码为 2，可直接放进批量迁移或 CI 门禁。
