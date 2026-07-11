# NovelAI Artist Vibe 参数选择修复设计

## 背景

旧画风节点的 `tags.txt` 可能同时包含 `gen_param` 和 `gen_json`。其中 `gen_param` 常用于可读参数摘要，可能省略体积较大的 `reference_image_multiple`；`gen_json` 才是完整 NovelAI 请求参数。

当前 `NovelAIArtistRepository` 将两者视为同一种参数来源，并采用文件中先出现的参数块。当 `gen_param` 位于 `gen_json` 前面时，完整 vibe 图片参数不会进入 artist node，后续 Renderer、`core_novelai_client` 和 `ai_image_gateway_raw` 都无法恢复这些数据。

## 目标

- 同时存在时，使用第一个有效的 `gen_json`。
- 不存在 `gen_json` 时，回退到第一个有效的 `gen_param`。
- 多个 `gen_json` 仍只采用第一个，保持现有画风节点约定。
- Renderer 和两个 NovelAI 执行器接收相同的完整 `RenderRequest`。
- `generation.executor` 继续支持 `core_novelai_client` 与 `ai_image_gateway_raw` 切换。

## 非目标

- 不在 Renderer 中重新读取 `tags.txt`。
- 不在 gateway 中补齐或推断 vibe 参数。
- 不改变画风 prompt、模型、采样器及其他参数的覆盖规则。
- 不迁移或重写现有画风节点。

## 设计

`NovelAIArtistRepository` 解析扩展参数时分别记录：

- 第一个有效 `gen_json`。
- 第一个有效 `gen_param`，仅作为回退值。

读取完成后按 `gen_json > gen_param > 空参数` 选择最终 `artist.params`。这项选择属于输入层，因为输入层负责把旧节点转换成完整的 artist node；Renderer 只消费结构化结果，执行器只发送 Renderer 产出的请求。

结构化 artist migration 中若存在同样的选择逻辑，也采用相同优先级，避免 CLI 直接加载和迁移后加载产生不同结果。

## 配置切换

`configs/local.yaml` 中通过以下字段选择生图执行器：

```yaml
generation:
  executor: ai_image_gateway_raw
```

可选值为：

- `ai_image_gateway_raw`：通过 ai-image-gateway 的 NovelAI raw client 请求。
- `core_novelai_client`：通过 refactor 原有 NovelAI client 请求。

切换只发生在执行层，不改变 Batch、Composer、Policy、Renderer 或 artist 解析。

## 验收

使用画风节点 `109841329_01_official_typemoon_main_vibe_7682_aafa_koyama_cg_v45_latest_stable`：

1. `inspect-artist` 输出包含两个 `reference_image_multiple` 和对应的两个 `reference_strength_multiple`。
2. 同一 `RenderRequest` 分别交给两个执行器构建 payload，`input`、`model` 和 `parameters` 完全一致。
3. payload 保留 `reference_image_multiple`、`reference_strength_multiple` 和 `reference_information_extracted_multiple`。
4. 无 `gen_json`、只有 `gen_param` 的旧 NAI3 artist 仍可正常加载。
5. 不触发真实 NovelAI 请求即可完成参数验收；完成后再选择一个执行器做单张真实出图确认。

