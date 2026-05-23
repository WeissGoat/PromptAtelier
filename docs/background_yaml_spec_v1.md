# Background YAML 规范 v1

background 节点描述场景、环境和背景负向素材。它参与提示词生成，但不处理角色裁剪规则，也不处理具体后端参数。

## 核心边界

background 节点应该回答：

```text
画面发生在哪里？
环境里有哪些稳定元素？
有哪些背景层面的负向约束？
```

它不应该回答：

```text
角色应该保留哪些 section？
NovelAI / ComfyUI / SD 应该使用什么模型？
```

## 文件名

推荐使用：

```text
meta.yaml
```

background 通常比 style 更轻量，和 character/action 一样主要是素材事实库。

## 最小结构

```yaml
schema: tags-machine.background/v1
kind: background
id: simple_room
name: Simple Room

tags:
  background:
    - "simple room"
    - "wooden floor"
  lighting:
    - "soft window light"

negative_prompt:
  - "crowded background"
  - "messy room"
```

## 字段说明

### `schema`

固定为：

```yaml
schema: tags-machine.background/v1
```

### `kind`

固定为：

```yaml
kind: background
```

### `tags`

正向背景素材，推荐分组：

- `background`：核心背景。
- `location`：地点。
- `environment`：环境元素。
- `lighting`：光照。
- `weather`：天气。
- `time`：时间。
- `mood`：氛围。
- `extra`：无法归入其他组但确实需要保留的素材。

当前 script composer 会把 background 的全部 tags 合入最终正向 prompt。

### `negative_prompt`

背景级负向素材，会合并到最终 `PromptBundle.prompt.negative`。

## 不写进 background 的内容

background v1 不建议包含：

- `character_scope`
- 角色 section include/suppress 规则
- `renderers.novelai` / `renderers.comfyui` / `renderers.sd`
- 模型、采样器、LoRA、workflow
- 临时 agent 推理规则

如果某个背景必须绑定特定后端工作流，优先把这部分放进 style 或未来独立 preset 节点，而不是污染 background。

## 与 action 的关系

action 决定角色裁剪视角，background 只补充场景素材。

组合链路：

```text
character.meta.yaml
+ action.meta.yaml
+ background.meta.yaml
-> composer
-> PromptBundle
```

## 示例

```yaml
schema: tags-machine.background/v1
kind: background
id: simple_room
name: Simple Room

description: 简单室内背景，适合作为局部特写和普通角色展示的默认场景。

tags:
  background:
    - "simple room"
    - "wooden floor"
  lighting:
    - "soft window light"
  mood:
    - "quiet atmosphere"

negative_prompt:
  - "crowded background"
  - "messy room"

agent:
  summary: 简单室内背景，不包含角色和镜头规则。
  labels:
    - background
    - indoor
```

## 当前冻结点

background v1 暂时冻结以下决策：

- 使用 `meta.yaml`。
- 使用 `kind: background`。
- 使用 `tags` 保存正向背景素材。
- 使用 `negative_prompt` 保存背景级负向素材。
- 不写角色裁剪规则。
- 不写后端配置。
