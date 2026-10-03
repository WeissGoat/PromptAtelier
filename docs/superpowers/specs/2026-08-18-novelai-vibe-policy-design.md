# NovelAI Vibe Policy 设计规范

## 1. 文档信息

- 日期：2026-08-18
- 状态：设计稿，待评审
- 适用范围：`tags_machine_core/refactor`
- 目标后端：NovelAI
- 关联配置：现有 `prompt_policy`

## 2. 背景

当前 artist 节点同时提供两类信息：

1. 画风 prompt、negative prompt、模型和采样参数；
2. NovelAI 专用的 vibe/reference 图片及其强度参数。

实际使用中，需要保留当前 artist 的文本画风和生成参数，但临时使用另一个 artist 的 vibe，或使用指定的外部 vibe 图片。这个行为不是 prompt token 替换，不能放进通用 `PromptPolicyPipeline` 的 token 规则中。

本功能统一使用现有 `prompt_policy.rules` 配置入口，由代码根据 Policy 的 scope、backend 和当前调用链决定执行阶段。

## 3. 目标

### 3.1 必须支持

- 使用另一个 artist 节点的 NovelAI vibe/reference 参数覆盖当前 artist 的 vibe；
- 使用本地图片文件作为 NovelAI vibe/reference 图片；
- 只替换 vibe/reference，不替换当前 artist 的 prompt、negative、model、sampler、steps、scale 等其他参数；
- 与现有 Policy 使用相同的配置形式：`enabled`、`options`、`order`、`require`、模板继承和局部覆盖；
- 在 Renderer 阶段执行后端专用 Policy；
- 最终 `RenderRequest`、PNG 信息和归档结果能追溯 vibe 来源，但不记录原始图片 base64；
- 当未配置该规则时，现有请求行为保持不变。

### 3.2 明确不做

- 不修改旧 `tags_machine`；
- 不修改 AgentComposer 的 prompt 生成逻辑；
- 不把完整 artist 替换成另一个 artist；
- 不把 NovelAI 专用字段加入通用 `PromptBundle.prompt`；
- 第一版不处理 ComfyUI、SD 的 vibe 语义；
- 第一版不处理 NovelAI Director Reference、ControlNet、img2img 或 mask；
- 第一版不依赖 `reference_image_multiple_cached` 的服务端缓存秘钥，只处理实际图片数据。

## 4. 术语

### 4.1 基础 artist

当前任务正常选择的 artist 节点。它仍然负责：

- 画风 prompt prefix/suffix；
- negative prompt；
- model；
- sampler、steps、scale 等默认生成参数；
- 未被 Policy 覆盖的其他 NovelAI 参数。

### 4.2 Vibe source

为当前 NovelAI 请求提供 reference 图片及相关参数的数据源。第一版支持：

- `artist`：从另一个 artist 节点提取 vibe/reference 参数；
- `image`：从本地图片文件读取图片数据。

### 4.3 Vibe 参数集合

第一版只处理以下字段：

```text
reference_image_multiple
reference_strength_multiple
reference_information_extracted_multiple
```

Policy 只覆盖这三个字段，不覆盖同一 artist 中的其他 `params`。

## 5. 配置规范

### 5.1 统一入口

不新增 `render_policy` 或 `novelai_policy` 顶层配置。配置继续放在现有 `prompt_policy` 下：

```yaml
prompt_policy:
  require: default
  rules:
    novelai_vibe:
      enabled: true
      options:
        source:
          type: artist
          ref: 20260412_2
        strength: [0.2]
        information_extracted: [1.0]
```

外部图片示例：

```yaml
prompt_policy:
  require: default
  rules:
    novelai_vibe:
      enabled: true
      options:
        source:
          type: image
          path: F:/ai_assets/vibe/watercolor.png
        strength: [0.2]
        information_extracted: [1.0]
```

### 5.2 规则字段

规则仍然使用现有通用结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enabled` | bool/null | 是否启用该规则。未填写时使用规则默认值。 |
| `options` | mapping | `novelai_vibe` 的数据源和覆盖参数。 |
| `order` | mapping | 仅参与同一 scope 的规则排序，不与 prompt 规则交叉排序。 |

### 5.3 `options.source`

#### artist 来源

```yaml
source:
  type: artist
  ref: 20260412_2
```

- `type` 必须为 `artist`；
- `ref` 按现有 artist repository 规则解析；
- 复用当前 `NovelAIArtistRepository` 或等价的 NodeDocument 加载链路；
- 只读取源 artist 的 Vibe 参数集合；
- 源 artist 没有 `reference_image_multiple` 时直接报错；
- 不读取源 artist 的 prompt、negative、model 或普通采样参数。

#### image 来源

```yaml
source:
  type: image
  path: F:/ai_assets/vibe/watercolor.png
```

- `path` 支持绝对路径；
- 相对路径按当前 Policy 配置文件所在目录解析；
- 文件必须存在且为普通文件；
- 读取二进制内容并编码为 NovelAI 请求使用的 base64 字符串；
- 不把 base64 写入日志、普通 Policy trace、PNG 摘要或错误信息。

### 5.4 覆盖参数

```yaml
options:
  source:
    type: image
    path: F:/ai_assets/vibe/watercolor.png
  strength: [0.2]
  information_extracted: [1.0]
```

规则：

- `strength` 对应 `reference_strength_multiple`；
- `information_extracted` 对应 `reference_information_extracted_multiple`；
- 未配置覆盖值时，使用 artist source 自带值；
- image source 必须显式配置 `strength` 和 `information_extracted`，不使用隐藏的 NovelAI 默认值；
- 单个数值可以规范化为单元素列表；
- 数组长度必须为 1 或与图片数量一致；长度为 1 时允许按图片数量广播；其他情况直接报错；
- 数值范围由 NovelAI Render Policy 校验，非法值直接报错；
- 第一版固定使用 `replace` 语义，不支持 append 或 merge。

## 6. 架构

### 6.1 总体链路

```text
输入节点
  -> Composer
  -> PromptBundle
  -> PromptPolicyPipeline
       只执行 scope=prompt 的规则
  -> NovelAIRenderAdapter
       生成基础 RenderRequest
  -> NovelAIRenderPolicyPipeline
       只执行 scope=renderer、backend=novelai 的规则
  -> RenderRequest
  -> NovelAI Client
```

### 6.2 Policy scope

现有 Policy 注册机制需要从“只有 prompt rule”扩展为统一 Policy Catalog。每条规则增加内部元数据：

```text
id
version
scope: prompt | renderer
backend: null | novelai | comfyui | sd
default_enabled
options_model
```

外部配置仍然只有一份 `prompt_policy.rules`。

内部执行器按 scope 筛选：

- `PromptPolicyPipeline` 只构造和执行 `scope=prompt` 的规则；
- `NovelAIRenderPolicyPipeline` 只构造 `scope=renderer` 且 `backend=novelai` 的规则；
- 后续新增 ComfyUI Policy 时复用同一 Catalog，但由 ComfyUI Renderer 的 Pipeline 执行；
- prompt rule 和 renderer rule 不互相参与排序；
- 规则 ID 仍然全局唯一，配置错误可以在统一入口提前发现。

`novelai_vibe` 的内部注册信息：

```text
id: novelai_vibe
version: v1
scope: renderer
backend: novelai
default_enabled: false
```

### 6.3 Renderer 接入位置

`NovelAIRenderAdapter` 先完成现有逻辑：

1. 解析基础 artist；
2. 合并 artist prompt、bundle prompt 和 negative；
3. 生成 Character Prompts；
4. 生成基础 `final_params`；
5. 构造基础 `RenderRequest`。

随后调用 `NovelAIRenderPolicyPipeline`，由 Policy 返回更新后的 `RenderRequest`。Policy 不直接调用 NovelAI Client，也不修改 PromptBundle 的正负面文本。

推荐内部接口：

```python
request = render_policy_pipeline.apply(
    request,
    bundle=bundle,
    resolved_nodes=resolved_nodes,
    policy=resolved_policy,
    target=policy_target,
)
```

### 6.4 Policy 配置传递

同一次调用中，Composer 和 Renderer 必须使用同一份已解析的 `PromptPolicyConfig`：

1. `GenerationService` 解析 `prompt_policy` 模板和局部覆盖；
2. 将配置传给 prompt pipeline；
3. 将同一配置传给 Renderer Policy Pipeline；
4. 不通过 `params` 传递 Policy 配置；
5. 不通过环境变量隐式选择 vibe source。

为了兼容直接调用 Renderer 的现有代码：

- 未传 Policy 配置时，Renderer 使用无效化的空配置，不执行 `novelai_vibe`；
- CLI、Batch、JSON API 等正式入口必须把已解析配置传入 render request 构建过程；
- 现有不配置 Policy 的调用行为不变。

## 7. 执行语义

### 7.1 触发条件

`novelai_vibe` 只有在以下条件同时满足时执行：

1. `prompt_policy.enabled=true`；
2. 规则自身已启用；
3. 当前 Renderer backend 为 `novelai`；
4. 当前 Policy target 允许执行；
5. `options.source` 已配置；
6. source 解析成功并得到至少一张图片。

未配置规则、规则被关闭、后端不是 NovelAI 或 target 不允许时，记录 trace 后跳过。

规则已启用但 source 缺失或无效时，视为配置错误并直接失败，不回退到基础 artist vibe。这样可以避免配置看似生效但实际使用了错误画风。

### 7.2 target 与 AgentComposer

Renderer 阶段沿用现有 `PromptPolicyConfig.apply_to`，不增加新的外部配置字段。调用入口把当前链路映射为 Policy target：

| 调用链 | Policy target |
| --- | --- |
| ScriptComposer 节点组合 | `script` |
| 完整 prompt/run-prompt | `full_prompt` |
| AgentComposer | `agent` |

`NovelAIRenderPolicyPipeline` 在执行前调用 `config.target_enabled(target)`。因此同一份 Policy 配置可以同时供 prompt 阶段和 Renderer 阶段使用，是否执行由同一份 `apply_to` 决定。

- ScriptComposer：遵循现有 `apply_to.script`；
- full prompt/run-prompt：遵循现有 `apply_to.full_prompt`；
- AgentComposer：遵循现有 `apply_to.agent=false` 默认值，保持 AgentComposer 不经过 PromptPolicyPipeline，也不默认执行该 Renderer Policy；
- 如果未来需要让 Agent 链路使用后端 Policy，必须通过明确的 target 配置开启，不能因为 Renderer 位于后端层就隐式改变 Agent 行为。

### 7.3 覆盖优先级

最终 vibe 参数按以下优先级生成：

```text
当前 artist 自带 vibe
  -> Policy source 覆盖图片和 source 默认值
  -> Policy options.strength 覆盖强度
  -> Policy options.information_extracted 覆盖信息提取强度
```

Policy 只覆盖 Vibe 参数集合。以下字段必须保持基础 artist/request 的结果：

```text
prompt
negative_prompt
model
sampler
steps
scale
seed
resolution
characterPrompts
其他非 Vibe NovelAI 参数
```

## 8. Source Resolver

### 8.1 ArtistVibeSourceResolver

职责：

- 根据 `ref` 加载 artist NodeDocument；
- 读取 `renderers.novelai.params`；
- 白名单提取 Vibe 参数集合；
- 深拷贝列表，避免污染源节点或当前 artist；
- 计算源参数摘要 hash；
- 不暴露源 artist 的非 Vibe 字段。

### 8.2 ImageVibeSourceResolver

职责：

- 解析绝对或相对路径；
- 检查文件存在、可读和普通文件属性；
- 读取图片字节；
- 生成 base64 请求值；
- 计算 SHA-256；
- 返回图片数量、字节大小和摘要信息。

不在日志或 JSON 报告中输出图片 base64。

### 8.3 解析结果内部结构

建议使用内部对象，不直接用裸字典在多个模块间传递：

```text
ResolvedVibeSource
  source_type: artist | image
  source_ref: str
  images: list[str]
  strengths: list[float]
  information_extracted: list[float]
  source_sha256: list[str]
  source_sizes: list[int]
```

该对象只在 Renderer Policy 层和 source resolver 之间使用，最终请求仍然使用 NovelAI 原生参数名。

## 9. 元数据、缓存和日志

### 9.1 RenderRequest meta

最终请求增加摘要信息：

```json
{
  "novelai_render_policy": {
    "enabled": true,
    "rules": ["novelai_vibe@v1"],
    "source_type": "artist",
    "source_ref": "20260412_2",
    "image_count": 2,
    "source_sha256": ["sha256:..."],
    "strength": [0.2, 0.2],
    "information_extracted": [1.0, 1.0],
    "replaced_fields": [
      "reference_image_multiple",
      "reference_strength_multiple",
      "reference_information_extracted_multiple"
    ]
  }
}
```

不写入原始 base64。

### 9.2 PNG 信息

`build_core_png_text` 增加 NovelAI Render Policy 摘要，保证从实际生成图片可以确认：

- 是否执行了 `novelai_vibe`；
- 来源是 artist 还是 image；
- 来源引用和图片 hash；
- 最终强度数组和信息提取数组；
- 被覆盖的字段。

图片参数本身继续由现有 PNG 参数归档逻辑记录。原始 base64 只保留在实际请求内存和必要的请求归档中，不进入普通展示摘要。

### 9.3 缓存签名

Vibe Policy 必须进入最终请求的可复现签名：

- artist source：对 source artist 的 Vibe 参数计算 hash；
- image source：对图片内容计算 SHA-256，而不是只使用路径；
- strength、information_extracted 和规则配置进入 policy signature；
- source 文件内容改变时，不能复用旧的 vibe 请求缓存。

Prompt composition cache 和 render request cache 仍然分开。Vibe 变化不应改变 prompt 文本缓存，但必须改变最终 RenderRequest 的签名和归档结果。

## 10. 错误处理

以下情况直接抛出可读的配置错误：

- `novelai_vibe` source type 未知；
- artist ref 不存在；
- artist 没有可用 `reference_image_multiple`；
- image path 不存在或不可读；
- 图片数量与强度数组长度不匹配；
- 强度或信息提取值超出 NovelAI 支持范围；
- Policy 配置中出现未知字段；
- Renderer Policy 误用于不支持的 backend。

不允许静默把错误 source 回退为当前 artist 的 vibe。

## 11. 日志规范

- `trace`：规则筛选、source 解析开始/结束、跳过原因、字段匹配结果；
- `info`：Policy 生效、source 类型、source ref、图片数量、最终覆盖字段；
- `warning`：兼容性跳过或非致命的默认值广播；
- `error`：source 不存在、参数校验失败、编码失败。

日志中禁止输出：

- 图片 base64；
- NovelAI token；
- 完整的超长请求体。

## 12. 验收标准

### 12.1 Mock 参数验收

至少覆盖：

1. 不配置 `novelai_vibe`：最终请求与当前实现一致；
2. 当前 artist + artist source：只改变三类 Vibe 参数；
3. 当前 artist + image source：图片被编码并出现在 NovelAI Client payload；
4. 自带两张 vibe 图片的 artist source：强度数组正确保留或广播；
5. source 图片内容改变：source hash 和最终 request signature 改变；
6. source 缺失、路径不存在、长度不匹配：直接报错；
7. backend 为非 NovelAI：规则不执行且不污染其他 Renderer；
8. AgentComposer：不经过 PromptPolicyPipeline，默认不执行该后端 Policy。

### 12.2 真实 NovelAI 业务验收

选一个稳定的基础 artist，分别生成：

- 基础 artist 自带 vibe；
- 基础 artist + 另一个 artist 的 vibe；
- 基础 artist + 外部 vibe 图片。

每个 case 保存：

- 最终图片路径；
- `RenderRequest`；
- `GenerationResult`；
- PNG 参数；
- Policy 摘要；
- 人工视觉结论。

业务验收重点：

- 当前 artist 的人物/画风 prompt 仍然存在；
- 模型、采样器、steps、scale、尺寸和 seed 没有被源 artist 偷换；
- PNG 参数中的 reference/vibe 与最终 `RenderRequest` 一致；
- 图像视觉上表现为当前 prompt 叠加新 vibe，而不是完整切换成源 artist；
- 真实 NovelAI 请求成功，且不引入额外不支持的参数。

## 13. 实施边界

预计新增或修改：

- 统一 Policy Catalog / registry；
- Renderer Policy 基础协议和 NovelAI Policy Pipeline；
- NovelAI Vibe source resolver；
- `GenerationService` 的 Policy 配置传递；
- NovelAI Renderer 的 Policy 调用和请求元数据；
- PNG Policy 摘要；
- batch / CLI / JSON API 的统一配置传递；
- 中文配置文档和业务验收记录。

不修改：

- 旧 `tags_machine`；
- AgentComposer 的 composition 和 cache 逻辑；
- PromptBundle 的 prompt 文本结构；
- 其他后端的实际请求协议。
