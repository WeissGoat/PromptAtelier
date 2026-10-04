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
| `renderers.comfyui.prompt_format` | 否 | workflow 期望的提示词写法。`comfyui`（默认）：渲染层把节点里的 NovelAI 写法转成 ComfyUI 写法（`{x}`→`(x:1.05)`、`[x]`→`(x:0.95)`、`1.2::x::`→`(x:1.2)`、字面圆括号转义），正向和负向都转；`novelai`：原样传入，由 workflow 自己的转换节点处理。 |
| `renderers.comfyui.size_presets` | 否 | 画风的竖横方尺寸：`portrait` / `landscape` / `square` 各一个 `{width, height}`（8 的倍数），可以只写其中几个。不写时用标准尺寸。见「尺寸」。 |
| `renderers.comfyui.default_size` | 否 | 请求没给 `size` 时用的选择，常用 `random`；不写等同 `custom`（用请求的宽高）。 |
| `renderers.comfyui.strict_bindings` | 否 | 默认 `true`：`inputs`、`optional_inputs`、`node_overrides` 指向的节点和输入必须在 workflow 里存在，否则直接报错。只有确实要给节点新增输入时才设成 `false`。 |

路径使用 ComfyUI API workflow 的点路径，例如：

```yaml
inputs:
  positive_prompt: "165.inputs.text"
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

不用在界面上手动导出：`scripts/comfyui_ui_to_api.mjs` 用 comfyui-mcp 的转换器（和 Codex 里的 comfyui MCP
`get_workflow` 同一套）把 UI 工作流转成 API 工作流，需要一个运行中的 ComfyUI 提供 `/object_info`：

```bash
npx -y -p comfyui-mcp@0.49.4 -c "node scripts/comfyui_ui_to_api.mjs <ui.json> <api.json>"
```

和手动导出比对过（cunyfunky）：节点、连线、取值一致，只少了界面扩展的显示控件（`speak_and_recognation`、ShowText 显示文本）。

## 尺寸

尺寸选择对所有后端（NovelAI、ComfyUI、SD）通用，实现在 `renderers/sizes.py`。请求参数 `size`：

- `random`：从画风的预设里抽一个；`portrait` / `landscape` / `square`：竖 / 横 / 方，用画风对应的那个；`custom`：用请求的 width/height。
- 画风在 `renderers.<backend>.size_presets` 里声明自己的竖横方尺寸（不同模型适合的尺寸不同）；没声明时用标准尺寸
  竖 832×1216、横 1216×832、方 1024×1024。选了画风没有的方向会报错。
- Web 的「尺寸」下拉默认随机，Width/Height 只在「自定义宽高」时生效。batch 的 `resolution`
  （`random_standard` / `portrait` / `normal_landscape` ...）换成对应的 `size`，写了 width/height 就是 `custom`。
- 不给 `size` 时用画风的 `default_size`，再没有就是 `custom`（CLI / API 直接传宽高的行为不变）。
- 尺寸在拼提示词时就定下（Web 的 Preview 里看到的就是出图用的），实际宽高写进请求，选中的方向写进 `meta.size_preset` 和 PNG 的 render 段。
- 横竖两路的原工作流合成一路即可：宽高绑到那一路的 EmptyLatentImage，横图竖图都走它。

## 种子与提示词

- 没给 seed 或给了负数（Web 的 `-1`）表示随机：渲染层抽一个 0–4294967295 的种子写进请求，归档和文件名里是实际用的值。
- 提示词正文来自组合后的 PromptBundle。注意：目前 ComfyUI 渲染层不会像 NovelAI 那样把 artist node 自己的 `tags` 加进提示词，画风完全由 workflow 决定。

## 提交前的处理

套用参数后、提交给 ComfyUI 之前，core 会按目标（`comfyui.targets`）做两件事：

- **裁剪到 output_nodes**（`prune_to_output_nodes`，默认开）：只保留 `output_nodes` 及其上游节点。
  ComfyUI 会执行 prompt 里所有输出节点，并要求每个 `class_type` 都已安装；裁剪后预览、备用保存等分支不再执行，
  云端也不必安装它们用到的插件。cunyfunky 从 64 个节点裁到 22 个。
- **路径归一化**（`path_style`）：`posix` 会把相对文件路径里的 `\` 改成 `/`。Windows 上导出的
  `画风调整\\add_contrast_XL.safetensors` 在 Linux 的 ComfyUI 上会因下拉值精确匹配失败而报 `value_not_in_list`。

用 `comfyui-check --artist-node <dir>` 可以查看裁剪后的节点、需要的插件和模型文件；加 `--manifest` 对照运行环境清单，
加 `--config ... --comfyui-target ... --live` 对照目标 ComfyUI 的 `/object_info`。

## Cunyfunky 基准

`comfyui_cunyfunky` 把正向提示词直接写入 `165.inputs.text`（CLIPTextEncode），NovelAI 写法由渲染层转换。
workflow 里原来的链路 `ImpactWildcardProcessor(#218) -> OldNAIToComfyUI(#219) -> CLIPTextEncode(#165)` 不再使用：
#218 会把 `{tag}` 当成随机选项展开，加权在进入 #219 之前就丢了。改绑后 #218/#219 会被裁剪掉。

checkpoint、VAE、LoRA、FaceDetailer、UltimateSDUpscale 等都继续由 workflow 自己控制。
