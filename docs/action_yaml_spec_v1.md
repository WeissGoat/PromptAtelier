# Action YAML 规范 v1

本文档确认动作节点的轻量 YAML 结构。当前结论是：`action` 节点也使用 `meta.yaml`，只描述动作提示词素材和它对角色素材选择的影响，不承载复杂镜头拆解。

## 结论

action v1 先服务当前最重要的需求：

> composer 需要知道这个 action 应该按哪种角色裁剪视角选择 character tags。

因此 action v1 使用：

- 文件名：`meta.yaml`
- schema：`tags-machine.action/v1`
- 正向动作素材：`tags`
- 负向动作素材：`negative_prompt`
- 角色裁剪视角：`character_scope`
- 不拆 `pose`
- 不拆 `camera`
- 不拆 `focus`
- 不写每个角色 section 的 include/suppress 规则

换句话说，action 不需要知道 `hair / eyes / upper_clothes` 具体怎么过滤。它只需要声明：

```yaml
character_scope: foot_detail
```

然后 composer 统一知道 `foot_detail` 应该如何选择 character section。

## 最小结构

```yaml
schema: tags-machine.action/v1
kind: action
id: sitting_feet_closeup
name: Sitting Feet Closeup

tags:
  action:
    - sitting
    - foot_focus
    - soles
    - toes
    - soles_toward_viewer

negative_prompt:
  - bad_feet
  - extra_toes

character_scope: foot_detail
```

## 字段说明

### `schema`

固定为：

```yaml
schema: tags-machine.action/v1
```

### `kind`

固定为：

```yaml
kind: action
```

### `id`

具体动作节点 id，通常使用动作节点文件夹名。

### `name`

可选的人类可读名称。

### `tags`

动作正向提示词素材。

当前 v1 推荐只使用一个 section：

```yaml
tags:
  action:
    - foot_focus
    - soles
```

原因是当前 composer 不需要知道这些词到底是 pose、camera 还是 composition。拆太细会增加维护成本，但不会提高当前规则质量。

如果某些动作已有历史分组，也可以被 reader 兼容读取，但 v1 主推 `tags.action`。

### `negative_prompt`

动作自带负向提示词素材，会被 composer 合并到最终 `PromptBundle.prompt.negative`。

示例：

```yaml
negative_prompt:
  - bad_feet
  - extra_toes
```

### `character_scope`

动作对角色素材的裁剪视角。

这是 action v1 最重要的结构化字段。它不是提示词，而是给 composer 的策略输入。

示例：

```yaml
character_scope: foot_detail
```

含义：

```text
这个动作是脚部局部镜头。
composer 应按 foot_detail 策略选择 character tags。
```

## 推荐 `character_scope` 枚举

第一版建议只保留少量够用的 scope：

- `default`：默认角色展示，不做特殊裁剪。
- `full_body`：全身可见。
- `upper_body`：上半身为主。
- `lower_body`：下半身为主。
- `portrait`：脸部/头像/半身偏头部。
- `face_detail`：脸部局部特写。
- `hand_detail`：手部局部特写。
- `foot_detail`：脚部局部特写。
- `object_focus`：道具或非角色主体为主，角色信息应弱化。

不确定时用 `default`，不要临时发明太多 scope。

## Composer 策略示例

下面这类规则属于 composer 策略，不写进 action `meta.yaml`：

```yaml
character_scope_policy:
  foot_detail:
    include_character_sections:
      - character
      - copyright
      - body
      - feet
      - legwear
      - footwear
    suppress_character_sections:
      - hair
      - eyes
      - face
      - head_accessories
      - upper_clothes
      - full_body_clothes
```

action 只引用：

```yaml
character_scope: foot_detail
```

这样每个 action 不需要重复一份 section 规则。

## 不写进 action 的内容

以下内容不建议放进 action v1：

- `pose` 独立字段。
- `camera` 独立字段。
- `focus` 独立字段。
- `visible_parts`。
- `character_sections.include`。
- `character_sections.suppress`。
- 每个角色 section 的过滤规则。
- 后端生图参数。
- 画风、artist、quality tags。

这些字段以后如果确实被 composer 用到了，可以进入 action v2。v1 不提前结构化暂时不用的信息。

## 旧 `tags.txt` 迁移

旧项目的动作 `tags.txt` 常见形态是一整行逗号分隔 prompt，并在 `=` 后追加 `origin_uc`、`node_background`、`gen_json` 等扩展行。v1 提供保守迁移命令：

```powershell
uv run python -m tags_machine_core migrate-action-tags `
  F:\my_project\new\tags_machine\design\动作改2\next\17_20240706_1720261297 `
  --character-scope foot_detail `
  --output migrated\nodes\actions\foot_closeup\meta.yaml
```

迁移策略：

- 只生成 `schema`、`kind`、`id`、`name`、`tags.action`、`negative_prompt`、`character_scope`、`legacy` 和 `agent`。
- 正向 prompt 会按顶层逗号拆成 `tags.action`；括号、方括号、花括号内部的逗号不会被拆开，避免破坏 `(soles detailed:1.2,toenails)` 这类权重组合。
- `origin_uc`、`uc`、`negative_prompt`、`after_uc`、`after_negative_prompt` 会提升为动作级 `negative_prompt`。
- `node_background`、`node_artist`、`gen_json` 等旧扩展只保留在 `legacy.raw_sections`，不提升为 action v1 字段。
- `character_scope` 可以通过 `--character-scope` 显式指定；没有指定时，迁移工具会根据有限关键词推断，例如 `toes focus` / `soles` 推断为 `foot_detail`，`pov hands` 推断为 `hand_detail`。推断结果必须人工复核。

迁移工具不会修改旧项目目录；只有传入 `--output` 时才写出新 YAML。

## 例子

### 脚底特写

```yaml
schema: tags-machine.action/v1
kind: action
id: foot_closeup
name: Foot Closeup

tags:
  action:
    - foot_focus
    - soles
    - toes
    - soles_toward_viewer

negative_prompt:
  - extra_toes
  - bad_feet

character_scope: foot_detail
```

### 上半身站立

```yaml
schema: tags-machine.action/v1
kind: action
id: upper_body_standing
name: Upper Body Standing

tags:
  action:
    - standing
    - upper_body
    - looking_at_viewer

negative_prompt: []

character_scope: upper_body
```

### 普通动作

```yaml
schema: tags-machine.action/v1
kind: action
id: simple_sitting

tags:
  action:
    - sitting
    - relaxed

negative_prompt: []

character_scope: default
```

## 与 character 的关系

组合链路：

```text
character.meta.yaml
  tags.character / tags.hair / tags.eyes / tags.upper_clothes ...

action.meta.yaml
  tags.action
  character_scope

composer policy
  character_scope -> include/suppress character sections

PromptBundle
  prompt.positive
  prompt.negative
```

action 和 character 都只描述素材事实。真正的选择策略由 composer 统一维护。

## 当前冻结点

action v1 暂时冻结以下决策：

- 使用 `meta.yaml`。
- 使用 `tags.action` 表示正向动作素材。
- 使用 `negative_prompt` 表示动作级负向素材。
- 使用 `character_scope` 作为角色素材裁剪视角。
- 不在 action YAML 中写角色 section 过滤规则。
- 不提前拆 `pose/camera/focus` 等当前未使用字段。
