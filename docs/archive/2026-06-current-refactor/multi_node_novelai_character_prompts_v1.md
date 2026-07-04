# 多节点与 NovelAI Character Prompts 方案 v1

本文档记录 2026-05-31 这一版输入层、Composer、Renderer 和 Client 的边界调整。

## 分层边界

新的运行链路按以下职责划分：

```text
InputResolver / NodeReader
  读取 artist / character / action / background 等节点
  输出 ResolvedNodeSet

Composer
  消费 ResolvedNodeSet
  输出 PromptBundle

Renderer / Adapter
  业务后端适配层
  消费 PromptBundle + ResolvedNodeSet
  输出 RenderRequest

Client / Execution
  纯请求层
  只消费 RenderRequest
```

Renderer 可以理解业务节点对象。例如 NovelAI renderer 可以消费 character 节点和 artist/style 节点，用来组装 NovelAI V4+ 的 `character_prompts`、style prompt、vibe/reference 参数等。但 renderer 不负责读文件、扫描 `design` 或自行解析 ref。

NovelAI renderer 不执行 `character_scope` 规则。`character_scope` 属于 Composer / AgentComposer 的提示词生成策略；Renderer 只拿 character node 的候选 tags 和已经生成好的 base prompt 做精确匹配，匹配到的角色 tags 才会被移入 `char_captions`。

Client / Execution 不再理解业务节点，只负责把 `RenderRequest` 交给具体生图 API。

`RenderRequest.meta` 会保留 `source_nodes`、`node_refs`、`character_materials` 等追踪信息，供前端展示、日志排查和验收对比使用。Client 不读取这些业务字段，也不会把它们作为 NovelAI 请求参数发送。

## 多节点输入

核心输入支持 `nodes[]`：

```json
{
  "nodes": [
    {"role": "artist", "ref": "20260412_2"},
    {"role": "character", "ref": "nodes/characters/homura"},
    {"role": "character", "ref": "nodes/characters/madoka"},
    {"role": "action", "ref": "nodes/actions/two_girls"},
    {"role": "background", "ref": "nodes/backgrounds/classroom"}
  ]
}
```

也支持前端更容易组织的映射格式：

```json
{
  "nodes": {
    "character": [
      "nodes/characters/homura",
      {"ref": "nodes/characters/madoka"}
    ],
    "action": "nodes/actions/two_girls"
  }
}
```

旧入口继续保留：

```json
{
  "nodes": {
    "character": "nodes/characters/homura",
    "action": "nodes/actions/foot_detail"
  }
}
```

CLI 旧参数 `--artist`、`--character`、`--action`、`--background` 继续作为快捷入口；新增 `--node role:path` 用于多角色和未来扩展节点。

## 多角色 Composer

ScriptComposer 和 AgentComposer 都可以消费多个 character 节点。输出的 `PromptBundle.meta.extra` 会记录本次实际使用的节点和角色素材：

```json
{
  "meta": {
    "extra": {
      "node_refs": [
        {"role": "character", "ref": "homura", "id": "homura", "index": 0},
        {"role": "character", "ref": "madoka", "id": "madoka", "index": 1}
      ],
      "character_materials": [
        {
          "ref": "homura",
          "id": "homura",
          "index": 0,
          "used_sections": ["character", "feet"],
          "suppressed_sections": ["hair", "eyes", "upper_clothes"],
          "positive_tags": ["akemi homura", "bare soles"],
          "negative_tags": []
        }
      ]
    }
  }
}
```

位置和空间关系暂不放在 character 输入里。第一版由 action prompt 自己表达，例如 `2girls, standing side by side`。

## AgentComposer

Agent 模式也使用 `ResolvedNodeSet`。缓存 key 由以下内容生成：

- composer version
- 每个节点的 `content_hash`
- `extra_prompt`
- `negative`
- `character_scope`
- `agent_model`

`instructions` 会写入 task 供外部 agent 读取，但不进入缓存 key。

如果 `run-prompt --composer agent` 携带完整 `--prompt` 或 `--prompt-file`，该 prompt 被视为外部 agent 已经拼好的结果，会写入 cache 后继续生成。

如果没有完整 prompt，也没有 `agent_result`，则只返回 `requires_agent` 和 `agent_task`，不进入生图。

`character_scope` 仍保留在结构里，但业务上优先来自 action 节点。它主要用于过滤角色素材，例如 foot_detail 只保留 identity/body/feet/legwear 等部分。

## NovelAI Character Prompts

NovelAI V4+ 可通过 render params 显式开启：

```json
{
  "params": {
    "character_prompts": {
      "mode": "auto",
      "max_characters": 6,
      "default_caption_prefix": "girl"
    }
  }
}
```

启用条件：

- model 必须是 `nai-diffusion-4*`。
- 必须显式传入 `character_prompts.mode=auto`。
- 必须有 character 节点或 `PromptBundle.meta.extra.character_materials`。

启用后，NovelAI renderer 会：

- 从 character node 收集候选角色 tags。
- 只把已经出现在 base caption 中的角色 tags 放入 `v4_prompt.caption.char_captions`。
- 从 base caption 中移除精确匹配到的角色 tags。
- 保留 action、background、style、quality 等非角色内容在 base caption。
- 最多消费前 6 个角色；`max_characters` 可调，但上限仍固定为 6。
- 默认在每个角色 caption 前加 `girl`。如不需要，可传 `default_caption_prefix: ""`。
- 对 legacy artist/style 路径保持旧 tags_machine 风格的紧凑逗号格式，只移动角色词，不额外改写整段 prompt。

这意味着 Renderer 不会把 character node 里存在、但 base prompt 没有出现的 `hair` / `eyes` / `clothes` 等 tags 主动补进角色 caption。局部镜头要过滤哪些角色词，应由 AgentComposer 生成 base prompt 时完成。

未开启时保持旧单 prompt 行为。

当前真实链路已验证：

- `run-prompt + full prompt + character/action nodes + character_prompts.auto` 可真实调用 NovelAI 出图。
- `run-action + character/action nodes + character_prompts.auto` 可真实调用 NovelAI 出图。
- PNG 参数中能读取 `v4_prompt.caption.char_captions` 与 `v4_negative_prompt.caption.char_captions`。
- `reference_image_multiple`、`reference_strength_multiple` 等 artist/vibe 参数仍由输入层读取并进入 NovelAI 请求。

## Artist / Style 输入层

旧 `design/画风/<artist>/tags.txt` 本质上是 artist/style 节点。解析职责归输入层：

```text
design/画风/<artist>/tags.txt
-> nodes.NovelAIStyleRepository.load_node()
-> NodeDocument(kind=style)
-> ResolvedNode(role=artist)
-> NovelAI renderer
```

`NovelAIStyleRepository.load()` 仅保留兼容；新代码优先使用 `load_node()`，让 renderer 统一消费 `NodeDocument.renderers.novelai`。

`tags_machine_core.renderers.NovelAIStyleRepository` 暂时保留为兼容导出，但不再是推荐引用位置。
