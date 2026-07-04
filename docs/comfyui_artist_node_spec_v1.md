# ComfyUI Artist Node Spec v1

## 定位

ComfyUI artist node 是工作流预设节点。它不保存 checkpoint、VAE、LoRA、ControlNet、upscale、自定义节点参数等 workflow 内部配置；这些配置以 ComfyUI API workflow JSON 为准。

artist node 只声明三件事：

- 使用哪个 API workflow。
- core 的标准输入字段写入 workflow 的哪些节点路径。
- 需要下载哪些输出节点的图片。

## 字段

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `renderers.comfyui.workflow` | 是 | 给日志、UI、归档查看的 workflow 名称。 |
| `renderers.comfyui.workflow_path` | 是 | API workflow JSON 路径。相对路径基于 artist node 目录解析。 |
| `renderers.comfyui.inputs.positive_prompt` | 是 | 正向提示词写入路径。 |
| `renderers.comfyui.inputs.negative_prompt` | 是 | 负向提示词写入路径。 |
| `renderers.comfyui.inputs.width` | 是 | 宽度写入路径。 |
| `renderers.comfyui.inputs.height` | 是 | 高度写入路径。 |
| `renderers.comfyui.inputs.seed` | 是 | seed 写入路径。 |
| `renderers.comfyui.optional_inputs` | 否 | 只有外部显式传参时才覆盖的路径映射。 |
| `renderers.comfyui.output_nodes` | 否 | 只下载指定输出节点的图片。为空时下载所有图片输出。 |
| `renderers.comfyui.node_overrides` | 否 | 高级固定覆盖，用于 workflow 特殊节点。 |

路径使用 ComfyUI API workflow 的点路径，例如：

```yaml
inputs:
  positive_prompt: "218.inputs.wildcard_text"
  negative_prompt: "153.inputs.text"
  width: "23.inputs.width"
  height: "23.inputs.height"
  seed: "202.inputs.seed"
```

`optional_inputs` 支持一个字段绑定多个节点：

```yaml
optional_inputs:
  steps:
    - "3.inputs.steps"
    - "17.inputs.steps"
  cfg:
    - "3.inputs.cfg"
    - "17.inputs.cfg"
```

如果 CLI 或 batch 没有传 `steps/cfg/sampler/scheduler`，core 不会覆盖 workflow 默认值。

## Workflow 格式

`workflow_path` 必须指向 ComfyUI `File -> Export (API)` 导出的 API workflow。API workflow 顶层通常是数字节点 id，例如：

```json
{
  "3": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 123
    }
  }
}
```

UI workflow 顶层通常包含 `nodes` 和 `links`，不能直接提交给 `/prompt`。

## Cunyfunky 基准

`comfyui_cunyfunky` 使用 `218.inputs.wildcard_text` 注入正向提示词，保留 workflow 自带链路：

```text
ImpactWildcardProcessor -> OldNAIToComfyUI -> CLIPTextEncode
```

checkpoint、VAE、LoRA、FaceDetailer、UltimateSDUpscale 等都继续由 workflow 自己控制。
