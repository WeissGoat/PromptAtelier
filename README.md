# Tags Machine Core

`tags_machine_core` 是 Tags Machine 的新一代旁路核心。

旧 `tags_machine` 仓库继续保持稳定，只作为数据源和兼容性参考。这个项目负责新的架构：

- 节点读取
- 提示词生成
- 提示词和结果缓存
- 生图后端适配
- 后续前端 UI 面向的服务 API

当前闭环：

```text
完整主体提示词 + style_ref
-> PromptBundle
-> RenderRequest
-> NovelAI 保存图片
```

默认不 import 旧项目里的运行时代码。

当前确定接入和验收主线只按 NovelAI 推进。ComfyUI / SD WebUI / Forge 相关代码只作为预研和未来扩展保留，等后续规范明确后再进入正式接入范围。

## CLI

- `compose`：生成 `PromptBundle`
- `compose-nodes`：从结构化角色/动作/背景节点生成 `PromptBundle`
- `agent-task-nodes`：生成给外部 agent 读取的组合任务 JSON
- `compose-agent-nodes`：把外部 agent 结果落成 `PromptBundle`，支持缓存复用
- `render-plan`：生成 `RenderRequest`，不联网；当前验收主线为 NovelAI
- `render-plan-nodes`：从结构化节点生成 `RenderRequest`，不联网；当前验收主线为 NovelAI
- `api-compose` / `api-render-plan` / `api-compose-render-plan`：从 JSON 请求文件完成前端/worker 边界往返
- `generate`：调用 NovelAI 并保存图片
- `execute-render-request`：读取已有 `RenderRequest` 并调用对应后端 client
- `inspect-node`：读取节点文件或目录
- `inspect-style`：读取旧画风节点
- `migrate-style-tags`：把旧画风 `tags.txt` 转成结构化 style `node.yaml`
- `inspect-image-params`：读取 PNG 内嵌生图参数，可输出归一化结果
- `compare-render-params`：对比旧项目 PNG/request 和 core `RenderRequest`
- `create-acceptance-record`：生成旧项目对照验收记录
- `archive-acceptance-case`：把旧项目 oracle 和 core 产物复制成可回放资料包
- `archive-novelai-acceptance-nodes`：从结构化节点生成 NovelAI core 产物并归档旧项目对照资料包
- `verify-acceptance-record`：重算验收记录并检查未批准差异
- `verify-acceptance-suite`：批量重算验收记录，并检查必需样例是否齐全
- `config`：查看配置解析结果

默认输出会截断图片/base64 字段，避免调试输出过大。需要完整 JSON 时使用 `--full`。

NovelAI 默认使用：

- 环境变量：`NAI_ACCESS_TOKEN`
- 接口：`https://image.novelai.net/ai/generate-image`

预研后端默认本地地址（当前不作为 v1 验收范围）：

- ComfyUI：`http://127.0.0.1:8188`
- Stable Diffusion WebUI / Forge：`http://127.0.0.1:7860`

结构化节点示例：

```powershell
uv run python -m tags_machine_core compose-nodes `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup
```

这个示例会读取角色和动作节点的 `meta.yaml`，并根据 action v1 的 `character_scope: foot_detail` 生成 `PromptBundle.meta.composition`。

Agent composer 示例：

```powershell
uv run python -m tags_machine_core agent-task-nodes `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --instruction "组合角色和动作，局部特写不要带入无关角色细节"

uv run python -m tags_machine_core compose-agent-nodes `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --agent-result agent_result.json `
  --cache-dir cache\prompt
```

`agent-task-nodes` 不调用模型，只输出稳定任务 JSON。外部 agent 返回 `positive`、`negative`、`character_scope` 和 section 裁剪结果后，`compose-agent-nodes` 会生成 `PromptBundle` 并写入缓存；同一输入后续可不传 `--agent-result`，直接从缓存复用。

NovelAI render plan 示例：

```powershell
uv run python -m tags_machine_core render-plan-nodes `
  --backend novelai `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --style-node examples\nodes\styles\anime_comfy `
  --seed 123

uv run python -m tags_machine_core render-plan `
  --backend novelai `
  --prompt "akemi homura, foot focus" `
  --params-json "{\"sampler\":\"k_euler_ancestral\"}"
```

`render-plan` / `render-plan-nodes` 只生成 `RenderRequest`，用于 UI、队列、diff 和验收。已有 `RenderRequest` 可以交给执行入口：

```powershell
uv run python -m tags_machine_core execute-render-request core_render_request.json `
  --config configs\local.example.yaml `
  --output-dir outputs
```

JSON API 边界示例：

```json
{
  "compose": {
    "nodes": {
      "character": "examples/nodes/characters/homura",
      "action": "examples/nodes/actions/foot_closeup"
    },
    "style": "examples/nodes/styles/anime_comfy"
  },
  "render": {
    "backend": "novelai",
    "style": "examples/nodes/styles/anime_comfy",
    "seed": 123
  }
}
```

```powershell
uv run python -m tags_machine_core api-compose-render-plan api_request.json `
  --output api_response.json
```

`api-compose-render-plan` 会输出同一份 `PromptBundle` 和 `RenderRequest`，用于前端预览、worker 队列和验收资料包，不会联网生图。

`generate` 是 NovelAI 的快捷入口，会直接从 prompt 生成 `RenderRequest` 并保存图片。`execute-render-request` 当前验收只要求 NovelAI 链路稳定；ComfyUI / SD WebUI / Forge 入口属于预研代码，不作为本阶段接入承诺。

旧画风节点迁移示例：

```powershell
uv run python -m tags_machine_core migrate-style-tags `
  F:\my_project\new\tags_machine\design\画风\sample_style `
  --output migrated\nodes\styles\sample_style\node.yaml
```

`migrate-style-tags` 默认不修改旧项目目录；只有传入 `--output` 时才写出结构化 YAML。

旧项目对照验收示例：

```powershell
uv run python -m tags_machine_core inspect-image-params old.png --normalized
uv run python -m tags_machine_core compare-render-params old.png core_render_request.json --show-normalized
uv run python -m tags_machine_core create-acceptance-record `
  --case-id foot_detail_homura_001 `
  --legacy-source old.png `
  --core-source core_render_request.json `
  --prompt-bundle core_prompt_bundle.json `
  --output acceptance\foot_detail_homura_001.yaml
uv run python -m tags_machine_core verify-acceptance-record acceptance\foot_detail_homura_001.yaml
uv run python -m tags_machine_core archive-acceptance-case `
  --case-id foot_detail_homura_001 `
  --output-dir acceptance `
  --legacy-source old.png `
  --core-source core_render_request.json `
  --prompt-bundle core_prompt_bundle.json `
  --required-case foot_detail
uv run python -m tags_machine_core archive-novelai-acceptance-nodes `
  --case-id foot_detail_homura_001 `
  --output-dir acceptance `
  --legacy-source old.png `
  --character examples\nodes\characters\homura `
  --action examples\nodes\actions\foot_closeup `
  --style-node examples\nodes\styles\anime_comfy `
  --seed 123 `
  --required-case foot_detail `
  --overwrite
uv run python -m tags_machine_core verify-acceptance-suite acceptance --require-minimum-set
```

`compare-render-params` 会完整比较 NovelAI 请求关键字段，包括 `v4_prompt`、`v4_negative_prompt`、`reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple` 等。图片/base64 字段会用长度和 sha256 摘要比较，避免把大段 base64 打进终端。

`create-acceptance-record` 会把旧图/旧请求、新 `RenderRequest`、归一化 diff、白名单差异、`PromptBundle.meta.composition` 和可选 `GenerationResult` 归档成 JSON/YAML；如果提供 `--generation-result`，会验证其中的 `request_body` 与 core `RenderRequest` 归一化后一致。`archive-acceptance-case` 会进一步把这些证据复制到独立样例目录，并更新 suite manifest，方便后续不运行旧项目也能回放。`archive-novelai-acceptance-nodes` 会先从结构化节点生成 core 侧 `PromptBundle` 和 NovelAI `RenderRequest`，再复用同一套归档逻辑，适合批量补旧项目 oracle 样例。`verify-acceptance-record` 会重新读取记录里的源文件并重算 diff，存在未批准差异时返回非 0。`verify-acceptance-suite` 可以验证单个 record、record 目录或 manifest；`--require-minimum-set` 会要求 `default_action`、`foot_detail`、`hand_detail`、`complex_character`、`reference_style` 五类样例都存在，并输出 `case_checks` 检查局部镜头 composition 和 reference/vibe 数组是否真的覆盖到。

详细文档：

- [整体设计与开发方案](docs/development_plan_v1.md)
- [Node YAML 规范](docs/node_yaml_spec_v1.md)
- [Character YAML 规范](docs/character_yaml_spec_v1.md)
- [Action YAML 规范](docs/action_yaml_spec_v1.md)
- [Style YAML 规范](docs/style_yaml_spec_v1.md)
- [Background YAML 规范](docs/background_yaml_spec_v1.md)
