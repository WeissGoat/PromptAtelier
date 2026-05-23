# Node YAML 规范 v1

`node.yaml` 是新提示词库的结构化格式。它的目标不是把所有提示词技巧都拆成复杂对象，而是让脚本和 agent 都能稳定理解：这个节点是什么、哪些词什么时候该用、哪些词在特定镜头下应该禁用。

## 设计原则

- 保留提示词原文，不破坏 NovelAI / SD 常用的 `(){}[]`、`1.2::tag::` 等权重写法。
- 用结构化字段描述语义边界，例如角色身份、身体部位、镜头范围、后端参数。
- 角色、动作、画风、背景都使用同一个外壳，降低 agent 读取成本。
- 后端强相关内容放到 `renderers`，不污染通用提示词层。
- `tags.txt` 在迁移期继续可用，`node.yaml` 优先级更高。

## 顶层结构

```yaml
schema: tags-machine-core.node/v1
kind: character
id: akemi_homura
name: Akemi Homura
description: 魔法少女小圆角色节点

tags:
  identity:
    - akemi homura
  traits:
    - calm

shot:
  framing: close-up
  body_scope: foot_detail
  camera: low angle

prompt:
  positive:
    - text: akemi homura
      role: identity
      include_scopes: ["*"]
    - text: purple eyes
      role: eyes
      include_scopes: [face_detail, upper_body, full_body]
      exclude_scopes: [foot_detail]
    - text: black hair
      role: hair
      include_scopes: [face_detail, upper_body, full_body]
      exclude_scopes: [foot_detail]
    - text: bare soles
      role: feet
      include_scopes: [foot_detail, lower_body, full_body]
  negative:
    - text: extra toes
      role: anatomy

constraints:
  required_parts:
    - akemi homura
  forbidden_parts:
    - purple eyes
  notes:
    - foot_detail 镜头下不要强行描述脸部和发型。

renderers:
  novelai:
    params:
      sampler: k_euler_ancestral

agent:
  summary: 脚底特写时只保留身份与足部相关外观。
  labels:
    - character
    - foot-aware
```

## 字段说明

### `schema`

固定为 `tags-machine-core.node/v1`。旧草稿里的 `tags-machine.node/v1` 也会被 reader 兼容读取。

### `kind`

节点类型：

- `character`
- `action`
- `artist`
- `background`
- `vibe`
- `story`
- `unknown`

### `tags`

给人和 agent 快速浏览的标签组。它可以继续接收旧 `tags.txt` 的简单文本，但不建议把所有正式提示词都只塞在这里。

### `shot`

镜头语义：

- `framing`：构图，例如 `close-up`、`medium shot`、`full body`。
- `body_scope`：画面主体范围，例如 `foot_detail`、`face_detail`、`upper_body`、`lower_body`、`full_body`。
- `camera`：机位，例如 `low angle`、`overhead view`。

`body_scope` 是脚本过滤角色字段的核心。

### `prompt.positive[]`

正向提示词片段。每一项可以是字符串，也可以是对象。

字符串简写：

```yaml
prompt:
  positive:
    - akemi homura
    - bare soles
```

对象写法：

```yaml
prompt:
  positive:
    - text: purple eyes
      role: eyes
      include_scopes: [face_detail, upper_body, full_body]
      exclude_scopes: [foot_detail]
```

字段：

- `text`：真实提示词文本，可以包含 `(){}[]` 和模型权重语法。
- `role`：语义角色，例如 `identity`、`hair`、`eyes`、`feet`、`clothing`、`pose`。
- `weight`：可选数值，仅做 meta，不强制改写 `text`。
- `include_scopes`：在哪些 `body_scope` 下启用。包含 `"*"` 表示总是可用。
- `exclude_scopes`：在哪些 `body_scope` 下禁用。
- `notes`：给 agent 或人工维护者的说明。

判定规则：

1. 如果 `exclude_scopes` 包含当前 `body_scope`，禁用。
2. 如果 `include_scopes` 为空，默认启用。
3. 如果 `include_scopes` 包含 `"*"`，启用。
4. 否则只有当前 `body_scope` 在 `include_scopes` 中时启用。

### `prompt.negative[]`

负向提示词片段，结构和 positive 一样。通常可以少写 scope，除非某些负向词只适用于特定镜头。

### `constraints`

给 composer 和 agent 的硬约束：

- `required_parts`：最终提示词里必须保留的语义。
- `forbidden_parts`：最终提示词里应该避免出现的语义。
- `notes`：非硬性说明。

### `renderers`

后端强相关配置。提示词生成层只传递引用，不直接理解这些字段。

NovelAI 示例：

```yaml
renderers:
  novelai:
    prompt_prefix:
      - year 2024
      - best quality
    negative_prompt: lowres, bad anatomy
    params:
      model: nai-diffusion-4-5-full
      sampler: k_euler_ancestral
      noise_schedule: karras
      steps: 28
      reference_strength_multiple: [0.2]
```

ComfyUI 示例：

```yaml
renderers:
  comfyui:
    workflow_ref: anime_portrait_v1
    loras:
      - name: homura_character
        strength_model: 0.8
        strength_clip: 0.8
```

### `agent`

给 agent 读取的摘要和标签：

```yaml
agent:
  summary: 角色是 Homura，脚部特写时不强调眼睛和发型。
  labels:
    - character
    - foot-aware
  warnings:
    - 不要在 foot_detail 镜头中加入 full body clothing dump。
```

## 角色节点建议

角色节点不要只写“一整套角色外观 dump”。建议拆成：

- `identity`：角色名、作品名、核心识别词。
- `face`：眼睛、表情、脸部特征。
- `hair`：发型、发色。
- `clothing`：服装。
- `body`：体型、身体特征。
- `feet` / `hands`：局部特写可用的部位特征。

脚底特写中通常保留：

- 角色身份。
- 动作需要的足部或腿部词。
- 和画面主体相关的材质、姿势、接触关系。

脚底特写中通常过滤：

- 眼睛。
- 头发细节。
- 上半身衣服 dump。
- 全身构图词。

## 动作节点建议

动作节点应声明自己的镜头范围：

```yaml
kind: action
id: foot_closeup
shot:
  framing: extreme close-up
  body_scope: foot_detail
  camera: low angle
prompt:
  positive:
    - text: foot focus
      role: composition
    - text: soles toward viewer
      role: pose
    - text: toes spread
      role: pose
  negative:
    - text: face focus
      role: composition
```

这样角色节点就能知道哪些字段该保留，哪些字段该跳过。

## 迁移策略

1. 先保留旧 `tags.txt`。
2. 给高频角色和动作节点补 `node.yaml`。
3. 脚本 composer 优先读 `node.yaml`，没有时退回 `tags.txt`。
4. agent 可以读取 `agent.summary` 和 `constraints` 做更细的冲突处理。
5. 后续写迁移脚本，把旧 `tags.txt` 初步拆成 `prompt.positive` 和 `tags.legacy`。
