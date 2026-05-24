# JSON API 契约 v1

这份文档定义 `tags_machine_core` 当前给前端、worker、队列和本地 CLI 复用的 JSON 边界。

当前 v1 的正式执行范围只包含 NovelAI。ComfyUI / SD 相关字段和代码可以用于 dry-run 或预研，但不能作为 v1 真实生图验收标准。

`compose-render-plan` 和状态分支响应由运行时 Pydantic 模型约束。状态响应是互斥分支，并保持旧契约：未使用的顶层分支直接省略，例如 `requires_agent` 不输出 `prompt_bundle: null`。

## 基本原则

- JSON API 是本地服务契约，不绑定 HTTP 框架；未来 HTTP 只需要薄封装 `GenerationJsonApi`。
- 输入文件路径按调用进程的当前工作目录解析；仓库示例默认从仓库根目录运行。
- `api-compose`、`api-agent-task`、`api-compose-agent`、`api-resolve-agent`、`api-render-plan`、`api-compose-render-plan`、`api-resolve-compose-render-plan` 都不联网。
- `api-generate` 会进入真实执行层，v1 默认只允许 NovelAI。
- Agent 拼接采用外部 agent 契约：core 只生成 agent task JSON，接收 agent result JSON，不直接绑定某个 LLM SDK。
- `PromptBundle.meta` 不包含 `shot` / `constraints`。动作镜头裁剪由 action `character_scope` 和最终 `meta.composition` 解释。
- style 的后端细节不写入 `PromptBundle`。NovelAI adapter 在生成 `RenderRequest` 时读取 style node 并叠加画风、质量词、negative、V4 payload 和 reference/vibe 参数。

## 核心对象

### PromptBundle

提示词生成模块的输出。

稳定字段：

- `schema`：固定为 `tags-machine-core.prompt-bundle/v1`。
- `prompt.positive`：完整正向提示词。
- `prompt.negative`：基础负向提示词。
- `meta.character_ref`：角色节点 id；完整 prompt 入口可以为 `null`。
- `meta.action_ref`：动作节点 id；完整 prompt 入口可以为 `null`。
- `meta.style_ref`：画风节点 id 或显式 style 引用。
- `meta.background_ref`：背景节点 id。
- `meta.composer_type`：`script` 或 `agent`。
- `meta.composition.character_scope`：本次组合实际采用的角色素材裁剪视角。
- `meta.composition.included_character_sections`：本次纳入的角色 section。
- `meta.composition.suppressed_character_sections`：本次抑制的角色 section。
- `meta.extra.agent.agent_model`：agent composer 输出时记录外部 agent 模型/版本，便于追溯缓存来源。
- `cache.cache_key`：agent 缓存 key。
- `cache.cache_hit`：本次是否命中缓存。

### AgentCompositionTask

发给外部 agent 的组合任务。

稳定字段：

- `schema`：固定为 `tags-machine-core.agent-composition-task/v1`。
- `nodes.character` / `nodes.action` / `nodes.background`：节点快照，包含 `id`、`kind`、`content_hash` 和结构化 `node`。
- `extra_prompt`：额外正向提示词。
- `negative`：额外负向提示词。
- `style_ref`：画风引用。
- `character_scope`：建议的裁剪视角，通常来自 action。
- `instructions`：给外部 agent 的人工/系统指令。
- `agent_model`：外部 agent 模型/版本标识，会进入 `cache_key`，避免模型升级后误用旧缓存。
- `cache_key`：该任务的稳定缓存 key。

请求里推荐使用 `agent.model` 传入模型/版本；同时兼容顶层 `agent_model`、`agent.agent_model` 和 `agent.model_version`。这些字段只用于 agent 任务和缓存追溯，不代表生图后端模型。

外部 agent 返回的最小结果：

```json
{
  "positive": "akemi homura, bare soles, foot focus",
  "negative": "extra toes, face focus",
  "character_scope": "foot_detail",
  "included_character_sections": ["character", "feet"],
  "suppressed_character_sections": ["eyes", "upper_clothes"]
}
```

### RenderRequest

生图适配层输出的后端执行计划。

稳定字段：

- `schema`：固定为 `tags-machine-core.render-request/v1`。
- `backend`：目标后端；v1 正式执行只承诺 `novelai`。
- `prompt`：后端最终正向提示词。
- `negative_prompt`：后端最终负向提示词。
- `model`：后端模型名。
- `seed`：随机种子。
- `size.width` / `size.height`：图片尺寸。
- `params`：后端参数；NovelAI 会包含 `v4_prompt`、`v4_negative_prompt`、`reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple`、`director_reference_images` 等关键字段。
- `style_payload`：style node 解析结果，便于调试和验收。
- `meta`：composer、action、style 等链路信息。

### GenerationResult

真实生图后的结果。

稳定字段：

- `schema`：固定为 `tags-machine-core.generation-result/v1`。
- `backend`：实际执行后端。
- `images`：保存后的本地图片路径、文件名和图片级 meta。
- `request_body`：发送给后端的最终请求体。
- `png_info`：保存后读取的 PNG 内嵌参数或读取错误。
- `cache_hit`：是否命中生成侧缓存；当前主要预留。

## 请求入口

### api-compose

输入：直接 prompt 或节点引用。

用途：只生成 `PromptBundle`。

节点模式：

```json
{
  "nodes": {
    "character": "examples/nodes/characters/homura",
    "action": "examples/nodes/actions/foot_closeup"
  },
  "style": "examples/nodes/styles/anime_comfy",
  "extra_prompt": "low angle close-up",
  "negative": "face focus",
  "character_scope": "foot_detail"
}
```

完整 prompt 模式：

```json
{
  "prompt": "akemi homura, bare soles, foot focus",
  "negative": "extra toes",
  "style": "examples/nodes/styles/anime_comfy"
}
```

如果请求包含 `"composer": "agent"`、`agent` 或 `agent_result`，`api-compose` 会走 agent composer 路径，效果等价于 `api-compose-agent`。

### api-agent-task

输入：节点引用、agent 指令、可选 `agent.model` 和可选缓存配置。

用途：只生成给外部 agent 读取的 `AgentCompositionTask`，不调用模型。

示例请求：`examples/requests/agent_resolution_requires_agent.json`

### api-compose-agent

输入：节点引用、agent result、可选 `agent.model` 和可选缓存配置。

用途：把外部 agent result 严格落成 `PromptBundle`，并写入缓存。缓存命中时可以不传 `agent.result`。

如果缓存未命中且没有 `agent.result`，该入口会失败。前端/worker 如果需要状态分支，应使用 `api-resolve-agent`。

示例请求：`examples/requests/agent_compose_with_result.json`

### api-resolve-agent

输入：和 `api-compose-agent` 相同。

用途：给前端/worker 使用的状态分支入口。

缓存命中或请求里带 `agent.result` 时返回：

```json
{
  "schema": "tags-machine-core.agent-compose-resolution/v1",
  "status": "ready",
  "prompt_bundle": {}
}
```

缓存缺失且没有 `agent.result` 时返回：

```json
{
  "schema": "tags-machine-core.agent-compose-resolution/v1",
  "status": "requires_agent",
  "agent_task": {}
}
```

调用方拿到 `requires_agent` 后，把 `agent_task` 交给外部 agent；拿到 agent result 后，再调用 `api-compose-agent` 或再次调用 `api-resolve-agent`。

示例请求：`examples/requests/agent_resolution_requires_agent.json`

### api-render-plan

输入：已有 `PromptBundle`。

用途：把 `PromptBundle` 转成 `RenderRequest`，不联网。

```json
{
  "prompt_bundle": {
    "schema": "tags-machine-core.prompt-bundle/v1",
    "prompt": {
      "positive": "akemi homura, bare soles, foot focus",
      "negative": "extra toes"
    }
  },
  "backend": "novelai",
  "style": "examples/nodes/styles/anime_comfy",
  "seed": 123,
  "width": 832,
  "height": 1216,
  "params": {
    "n_samples": 1,
    "cfg_rescale": 0.15
  }
}
```

### api-compose-render-plan

输入：`compose` 段和 `render` 段。

用途：一步生成 `PromptBundle` 和 `RenderRequest`，用于预览、队列入库和验收资料包。

返回：

```json
{
  "schema": "tags-machine-core.compose-render-plan-result/v1",
  "prompt_bundle": {},
  "render_request": {}
}
```

如果 `compose` 段走 agent composer，但缓存缺失且没有 `agent.result`，该入口会失败。前端/worker 如果需要状态分支，应使用 `api-resolve-compose-render-plan`。

示例请求：

- `examples/requests/compose_render_plan_novelai.json`
- `examples/requests/full_prompt_render_plan_novelai.json`
- `examples/requests/agent_compose_render_plan_novelai.json`

### api-resolve-compose-render-plan

输入：和 `api-compose-render-plan` 相同。

用途：给前端/worker 使用的预览状态分支入口。

可生成计划时返回：

```json
{
  "schema": "tags-machine-core.compose-render-plan-resolution/v1",
  "status": "ready",
  "prompt_bundle": {},
  "render_request": {}
}
```

需要外部 agent 时返回：

```json
{
  "schema": "tags-machine-core.compose-render-plan-resolution/v1",
  "status": "requires_agent",
  "agent_task": {}
}
```

示例请求：

- `examples/requests/agent_compose_render_plan_novelai.json`
- `examples/requests/agent_compose_render_plan_requires_agent.json`

### api-generate

输入：已有 `RenderRequest`。

用途：执行真实生图并返回 `GenerationResult`。

```json
{
  "render_request": {
    "schema": "tags-machine-core.render-request/v1",
    "backend": "novelai",
    "prompt": "akemi homura, foot focus",
    "negative_prompt": "bad anatomy",
    "seed": 123,
    "params": {
      "n_samples": 3
    }
  },
  "output_dir": "outputs"
}
```

v1 中 `api-generate` 只接受 NovelAI。ComfyUI / SD 即使存在预研 client，也不能通过该入口默认执行。

示例请求：`examples/requests/generate_novelai_mock.json`

仓库测试会用 mock executor 验证这个请求的 `RenderRequest -> GenerationResult` JSON 边界，不会联网。

## 推荐工作流

### 脚本 composer 预览

```text
api-compose-render-plan
-> PromptBundle + RenderRequest
-> 人工或 UI 检查
-> api-generate
-> GenerationResult
```

适合规则稳定、批量跑图和旧项目对照验收。

### Agent composer 预览

```text
api-resolve-compose-render-plan
-> status: requires_agent
-> 外部 agent 生成 result
-> api-resolve-compose-render-plan
-> status: ready
-> api-generate
```

适合角色和动作存在语义冲突的场景，例如脚底特写需要过滤头发、眼睛和上半身服装。

### 完整 prompt 入口

```text
api-compose-render-plan
compose.prompt 已经包含完整角色 + 动作
-> 只叠加 NovelAI style / quality / negative / V4 / reference 参数
```

适合人工或外部 agent 已经产出完整 prompt 的场景。这个入口不会读取 character/action 节点，也不会按 `character_scope` 做二次裁剪。

## 示例请求文件

仓库内可直接运行的示例请求：

- `examples/requests/agent_resolution_requires_agent.json`
- `examples/requests/agent_compose_with_result.json`
- `examples/requests/compose_render_plan_novelai.json`
- `examples/requests/full_prompt_render_plan_novelai.json`
- `examples/requests/agent_compose_render_plan_novelai.json`
- `examples/requests/agent_compose_render_plan_requires_agent.json`
- `examples/requests/generate_novelai_mock.json`

这些路径由测试门禁校验：文档引用必须存在，仓库内请求样例必须被文档引用，并且样例能从仓库根目录解析相对节点路径。

## 响应形状样例

仓库内还提供响应形状 golden：

- `examples/responses/json_api_response_shapes.json`

这个文件不是完整响应快照，而是前端/worker 需要依赖的字段形状、状态分支和关键常量。测试会读取该文件，实际调用 `GenerationJsonApi`，并校验每个样例的 `schema`、`status`、核心节点引用、NovelAI `RenderRequest` 字段、V4 payload、缺失字段，以及 `PromptBundle.meta` 不输出 `shot` / `constraints`。

## CLI 对照

本地文件入口和未来 HTTP 路由可以保持一一对应：

| CLI | 未来 HTTP | 输出 |
| --- | --- | --- |
| `api-compose` | `POST /compose` | `PromptBundle` |
| `api-agent-task` | `POST /agent-task` | `AgentCompositionTask` |
| `api-compose-agent` | `POST /compose-agent` | `PromptBundle` |
| `api-resolve-agent` | `POST /resolve-agent` | agent 状态响应 |
| `api-render-plan` | `POST /render-plan` | `RenderRequest` |
| `api-compose-render-plan` | `POST /compose-render-plan` | `PromptBundle + RenderRequest` |
| `api-resolve-compose-render-plan` | `POST /resolve-compose-render-plan` | 预览状态响应 |
| `api-generate` | `POST /generate` | `GenerationResult` |

## 验收要求

- 新增或修改 JSON API 字段时，必须能说明消费方；没有明确消费方的字段先放入 `extra`。
- 新增请求样例时，必须放入 `examples/requests/`，并在本文档列出。
- 涉及 agent composer 的请求必须覆盖 `ready` 和 `requires_agent` 两类状态。
- 涉及 NovelAI adapter 的请求必须能生成包含 V4/V4.5 字段和 reference/vibe 参数的 `RenderRequest`。
- 真实生图后必须保留 `GenerationResult.request_body` 和图片证据，供旧项目 oracle 对照验收。
