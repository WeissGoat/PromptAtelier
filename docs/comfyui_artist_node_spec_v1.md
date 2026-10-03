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
| `renderers.comfyui.output_nodes` | 否 | 只下载指定输出节点的图片。为空时下载所有图片输出。声明后提交时默认只保留这些节点的上游子图（见下文）。 |
| `renderers.comfyui.node_overrides` | 否 | 高级固定覆盖，用于 workflow 特殊节点。 |
| `renderers.comfyui.input_files` | 否 | LoadImage 等节点要读的输入图，提交前上传到目标 ComfyUI 的 input 目录。每项是路径字符串，或 `{path, name, subfolder}`；相对路径基于 artist node 目录。 |

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

## 提交前的处理

套用参数后、提交给 ComfyUI 之前，core 会按目标（`comfyui.targets`）做两件事：

- **裁剪到 output_nodes**（`prune_to_output_nodes`，默认开）：只保留 `output_nodes` 及其上游节点。
  ComfyUI 会执行 prompt 里所有输出节点，并要求每个 `class_type` 都已安装；裁剪后预览、备用保存等分支不再执行，
  云端也不必安装它们用到的插件。cunyfunky 从 64 个节点裁到 24 个。
- **路径归一化**（`path_style`）：`posix` 会把相对文件路径里的 `\` 改成 `/`。Windows 上导出的
  `画风调整\\add_contrast_XL.safetensors` 在 Linux 的 ComfyUI 上会因下拉值精确匹配失败而报 `value_not_in_list`。

用 `comfyui-check --artist-node <dir>` 可以查看裁剪后的节点、需要的插件和模型文件；加 `--manifest` 对照运行环境清单，
加 `--config ... --comfyui-target ... --live` 对照目标 ComfyUI 的 `/object_info`。

## Cunyfunky 基准

`comfyui_cunyfunky` 使用 `218.inputs.wildcard_text` 注入正向提示词，保留 workflow 自带链路：

```text
ImpactWildcardProcessor -> OldNAIToComfyUI -> CLIPTextEncode
```

checkpoint、VAE、LoRA、FaceDetailer、UltimateSDUpscale 等都继续由 workflow 自己控制。
