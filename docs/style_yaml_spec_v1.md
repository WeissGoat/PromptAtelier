# Style YAML 规范 v1

style 节点描述画风素材和后端相关素材。它既要能被 agent 读取，也要能被 adapter 稳定解析。

## 核心边界

style 节点可以包含两类信息：

- 通用画风素材：风格、质量词、构图倾向、通用负向词。
- 后端适配素材：NovelAI 的 prompt 前后缀和 vibe 参数，ComfyUI 的 workflow / LoRA / 节点覆盖，SD 的 checkpoint / VAE / ControlNet 等。

style 节点不应该包含角色、动作、局部镜头裁剪规则。

## 文件名

推荐使用：

```text
node.yaml
```

原因是 style 往往比 character/action 更像通用节点，且会携带多个后端配置。

## 最小结构

```yaml
schema: tags-machine.style/v1
kind: style
id: anime_comfy
name: Anime Comfy

tags:
  style:
    - "anime style"
  quality:
    - "best quality"

negative_prompt:
  - "lowres"
  - "bad anatomy"

renderers:
  novelai:
    prompt_prefix:
      - "{best quality}"
    prompt_suffix:
      - "clean lineart"
    negative_prompt:
      - "worst quality"
    params:
      sampler: k_euler
      steps: 28

  comfyui:
    workflow: portrait_workflow
    checkpoint: anime_comfy.safetensors
    loras:
      - name: lineart
        weight: 0.65
    params:
      steps: 32
      cfg: 6.5

  sd:
    checkpoint: anime_sd.safetensors
    vae: anime.vae.pt
    params:
      steps: 24
      cfg_scale: 7.5
```

## 字段说明

### `schema`

固定为：

```yaml
schema: tags-machine.style/v1
```

### `kind`

固定为：

```yaml
kind: style
```

迁移期旧 artist 节点仍可使用 `kind: artist`，但新结构化画风节点推荐统一使用 `style`。

### `tags`

通用正向画风素材。

推荐分组：

- `style`：核心画风词。
- `quality`：质量词。
- `lighting`：光照和色彩倾向。
- `composition`：通用构图倾向。
- `medium`：媒介或渲染类型，例如 watercolor、cel shading。

这些 tags 不是最终 prompt。NovelAI adapter 可以把它们合入画风 prompt，ComfyUI/SD adapter 当前主要把它们保留在 `style_payload` 中，后续 UI 和执行器也可以读取。

### `negative_prompt`

通用负向画风素材，会被支持的后端合并到最终负向提示词。

### `renderers`

后端专属配置。后端强相关内容只放在对应后端下面，不向 PromptBundle 扩散。

## NovelAI 配置

```yaml
renderers:
  novelai:
    prompt_prefix:
      - "{best quality}"
    prompt_suffix:
      - "clean lineart"
    negative_prompt:
      - "worst quality"
    after_negative_prompt:
      - "extra fingers"
    params:
      model: nai-diffusion-4-5-full
      sampler: k_euler_ancestral
      noise_schedule: karras
      steps: 28
      scale: 5.0
      reference_image_multiple:
        - "<base64 image>"
      reference_strength_multiple:
        - 0.25
      reference_information_extracted_multiple:
        - 0.6
```

NovelAI adapter 的组合顺序：

```text
renderers.novelai.prompt_prefix
+ PromptBundle.prompt.positive
+ tags 中的通用画风素材
+ renderers.novelai.prompt_suffix
```

负向词组合顺序：

```text
PromptBundle.prompt.negative
+ negative_prompt
+ renderers.novelai.negative_prompt
+ renderers.novelai.after_negative_prompt
```

默认 `include_common_tags: true`。如果某个 NovelAI style 只想使用 `prompt_prefix/suffix`，可以显式关闭：

```yaml
renderers:
  novelai:
    include_common_tags: false
```

## ComfyUI 配置

```yaml
renderers:
  comfyui:
    workflow: portrait_workflow
    checkpoint: anime_comfy.safetensors
    loras:
      - name: lineart
        weight: 0.65
    embeddings:
      - badhandv4
    control:
      enabled: false
    node_overrides:
      "12.inputs.cfg": 6.5
    params:
      steps: 32
      cfg: 6.5
      sampler: euler
      scheduler: karras
```

ComfyUI adapter 只产出 dry-run `RenderRequest`，真实 workflow 展开和节点 patch 由后续 client / executor 负责。

## SD 配置

```yaml
renderers:
  sd:
    checkpoint: anime_sd.safetensors
    vae: anime.vae.pt
    loras:
      - name: feet_detail
        weight: 0.8
    embeddings:
      - easynegative
    controlnet: []
    hires_fix:
      enabled: false
    params:
      steps: 24
      cfg_scale: 7.5
      sampler: "DPM++ 2M"
      scheduler: karras
```

SD adapter 当前也只生成 dry-run `RenderRequest`。

## 与 PromptBundle 的关系

PromptBundle 只记录：

```yaml
meta:
  style_ref: anime_comfy
```

style 的后端细节不会写入 PromptBundle。adapter 根据 `style_ref` 或 `--style-node` 读取 style node，再生成对应后端的 `RenderRequest`。

## YAML 引号

画风词经常包含 `{}`、`[]`、`:`，必须优先使用引号：

```yaml
tags:
  quality:
    - "{best quality}"
    - "[[artist:kedama_milk]]"
```

避免裸写：

```yaml
tags:
  quality:
    - {best quality}
```

## 当前冻结点

style v1 暂时冻结以下决策：

- 新结构化画风节点使用 `node.yaml`。
- 新节点使用 `kind: style`，迁移期兼容 `kind: artist`。
- 通用画风词放在 `tags`。
- 通用负向词放在 `negative_prompt`。
- 后端专属内容放在 `renderers.{backend}`。
- PromptBundle 只引用 `style_ref`，不携带 workflow / LoRA / vibe 细节。
