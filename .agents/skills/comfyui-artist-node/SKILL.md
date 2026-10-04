---
name: comfyui-artist-node
description: >-
  把一个 ComfyUI workflow 接成本项目的 ComfyUI 画风（artist node）：导出 API workflow、写 node.yaml 绑定、
  补插件和模型、预检并在本机或云端出图验证。在新增/修改 ComfyUI 画风、绑定报错、云端缺节点或缺模型时使用。
---

# 接入 ComfyUI 画风（artist node）

字段的完整定义见 `docs/comfyui_artist_node_spec_v1.md`，参考实现是 `examples/nodes/artists/comfyui_cunyfunky/`。

## artist node 只管三件事

1. 用哪个 **API** workflow（`File -> Export (API)` 导出，顶层是数字节点 id；顶层有 `nodes`/`links` 的是 UI 格式，不能提交）。
2. core 的标准输入写到 workflow 的哪些节点路径（点路径，如 `"165.inputs.text"`）。
3. 下载哪些输出节点的图（`output_nodes`）。

checkpoint、LoRA、采样参数等都以 workflow 为准，artist node 不重复保存。

## 步骤

1. 在本机 aki 里调好 workflow，导出 API 和 UI 两份 JSON，放进节点的 `workflows/`。
   用户真实的画风节点在 design 根目录的 `画风/comfyui/<名字>/`（`configs/local.yaml` 的 `legacy.design_root`），
   不在本仓库里；`examples/nodes/artists/` 只放示例和测试用节点。
2. 写 `node.yaml`：`renderers.comfyui` 下必填 `workflow`、`workflow_path`，以及 `inputs` 的
   `positive_prompt`、`negative_prompt`、`width`、`height`、`seed`；建议写 `output_nodes`。
   只声明 `comfyui` 渲染器的画风会走 ComfyUI，Web 的 Artist 选择器里带 `ComfyUI` 标记。
3. 提示词写法 `prompt_format`：默认 `comfyui`，由渲染层把节点里的 NovelAI 写法（`{x}`、`[x]`、`1.2::x::`）换算成
   ComfyUI 权重；正向提示词应直接绑到 `CLIPTextEncode` 的 `text`。如果 workflow 自带 NovelAI 转换节点才用 `novelai`。
   不要把正向提示词绑到 `ImpactWildcardProcessor` 这类会把 `{tag}` 当随机选项展开的节点。
4. 绑定校验 `strict_bindings` 默认开：路径指向的节点或输入不存在就报错。报错时修绑定，不要关掉它；
   只有确实要给节点新增输入时才设 `false`。
5. 预检（不花钱）：

   ```bash
   uv run python -m tags_machine_core comfyui-check --artist-node <节点目录> --manifest deploy/comfyui/manifest.yaml --config configs/local.yaml --comfyui-target modal
   ```

   看三处：裁剪后保留的节点（`output_nodes` 的上游；预览等分支会被裁掉）、
   `manifest.not_provided_by_manifest`（缺的插件或内置节点）、`missing_models`。
6. 缺插件：在 `deploy/comfyui/manifest.yaml` 的 `custom_nodes` 加 repo + commit（对齐本机 aki 的版本）和 `provides`，
   再重新部署（会整个重建镜像，见 `comfyui-cloud-deploy`）。缺模型：见 `comfyui-models`。
7. 验证出图：先本机 aki（`--comfyui-target local`），再云端；加 `--live` 预检会对照云端 `/object_info`，会触发一次冷启动。
   出的 PNG 里 `tags_machine_core` 元数据的 `render` 段记录了原始提示词、换算后的提示词、seed、尺寸、workflow 和运行位置。

## 常见问题

- `value_not_in_list`：下拉值精确匹配失败。多半是 Windows 路径分隔符（目标 `path_style: posix` 会处理），
  或者云端缺这个模型文件。
- 某个 `class_type` 不存在：云端没装对应插件；先确认它是否在 `output_nodes` 的上游，不在的话裁剪后不需要。
- seed 不给或给负数（Web 的 `-1`）表示随机，渲染层会抽一个实际值写进请求和文件名。
- 目前 ComfyUI 渲染层不会把 artist node 自己的 `tags` 加进提示词，画风完全由 workflow 决定。

## 测试

改渲染或绑定相关代码后：

```bash
uv run pytest tests/test_comfyui_prompt.py tests/test_comfyui_workflow_prep.py tests/test_comfyui_targets.py tests/test_web_comfyui.py -q
```

全量测试要跳过会真调 NovelAI 的用例：`uv run pytest -q --deselect tests/test_live_compare_generation.py`。
