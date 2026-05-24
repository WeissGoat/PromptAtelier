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
-> NovelAI execution
-> GenerationResult
```

默认不 import 旧项目里的运行时代码。

当前确定接入和验收主线只按 NovelAI 推进。ComfyUI / SD WebUI / Forge 相关代码只作为预研和未来扩展保留，等后续规范明确后再进入正式接入范围。

真实生图统一通过 `execution.py`：CLI、JSON API 和未来 worker 先拿到 `RenderRequest`，再进入 execution 层。`execute_render_request()` 负责 `run-prompt`、`generate`、`api-generate` 和 `execute-render-request` 的后端分发；当前默认只允许 NovelAI，并委托 `execute_novelai_generation()` 创建 `NovelAIClient`、保存图片、收集 PNG 内嵌参数、记录最终 request body，最后返回 `GenerationResult`。ComfyUI / SD 的真实执行仍需要显式实验开关。

## CLI

- `compose`：生成 `PromptBundle`
- `compose-nodes`：从结构化角色/动作/背景节点生成 `PromptBundle`
- `agent-task-nodes`：生成给外部 agent 读取的组合任务 JSON
- `compose-agent-nodes`：把外部 agent 结果落成 `PromptBundle`，支持缓存复用
- `render-plan`：生成 `RenderRequest`，不联网；当前验收主线为 NovelAI
- `render-plan-nodes`：从结构化节点生成 `RenderRequest`，不联网；当前验收主线为 NovelAI
- `run-prompt`：输入完整角色+动作 prompt，只叠加 NovelAI 画风；可 dry-run，也可直接生图
- `api-compose` / `api-agent-task` / `api-compose-agent` / `api-resolve-agent` / `api-render-plan` / `api-compose-render-plan` / `api-resolve-compose-render-plan` / `api-generate`：从 JSON 请求文件完成前端/worker 边界往返
- `generate`：调用 NovelAI 并保存图片
- `execute-render-request`：读取已有 `RenderRequest` 并执行；默认只执行 NovelAI，ComfyUI / SD 需要显式实验开关
- `backend-support`：输出后端支持矩阵；NovelAI 是默认执行后端，ComfyUI / SD 标记为预研执行后端
- `inspect-node`：读取节点文件或目录
- `validate-node-tree`：只读校验结构化节点目录，检查 v1 文件名、关键字段和禁止字段
- `inspect-style`：读取旧画风节点
- `migrate-style-tags`：把旧画风 `tags.txt` 转成结构化 style `node.yaml`
- `migrate-character-tags`：把旧角色 `tags.txt` 转成结构化 character `meta.yaml`
- `migrate-action-tags`：把旧动作 `tags.txt` 转成结构化 action `meta.yaml`
- `migrate-background-tags`：把旧背景 `tags.txt` 转成结构化 background `meta.yaml`
- `inspect-image-params`：读取 PNG 内嵌生图参数，可输出归一化结果
- `compare-render-params`：对比旧项目 PNG/request 和 core `RenderRequest`
- `create-acceptance-record`：生成旧项目对照验收记录
- `archive-acceptance-case`：把旧项目 oracle 和 core 产物复制成可回放资料包
- `archive-novelai-acceptance-nodes`：从结构化节点生成 NovelAI core 产物并归档旧项目对照资料包
- `archive-novelai-acceptance-prompt`：从完整 prompt 生成 NovelAI core 产物并归档旧项目对照资料包
- `verify-acceptance-record`：重算验收记录并检查未批准差异
- `verify-acceptance-suite`：批量重算验收记录，并检查必需样例是否齐全
- `verify-core`：运行当前无联网核心门禁，覆盖 compileall、unittest、示例节点校验、fixture 验收和 `git diff --check`
- `config`：查看配置解析结果

默认输出会截断图片/base64 字段，避免调试输出过大。需要完整 JSON 时使用 `--full`。

NovelAI 默认使用：

- 环境变量：`NAI_ACCESS_TOKEN`
- 接口：`https://image.novelai.net/ai/generate-image`

预研后端默认本地地址（当前不作为 v1 验收范围）：

- ComfyUI：`http://127.0.0.1:8188`
- Stable Diffusion WebUI / Forge：`http://127.0.0.1:7860`

预研后端真实执行需要在 `execute-render-request` 中显式传 `--allow-experimental-backend`；默认执行路径只承诺 NovelAI。前端、worker 或批量脚本需要判断后端能力时，读取 `backend-support` 的 JSON 输出，不要硬编码散落的后端范围。

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

等价的 JSON API 文件入口适合前端和 worker 使用。完整请求/响应契约见 [JSON API 契约](docs/json_api_contract_v1.md)，README 只保留常用命令：

```powershell
uv run python -m tags_machine_core api-agent-task examples\requests\agent_resolution_requires_agent.json `
  --output agent_task.json

uv run python -m tags_machine_core api-compose-agent examples\requests\agent_compose_with_result.json `
  --output prompt_bundle.json

uv run python -m tags_machine_core api-resolve-agent examples\requests\agent_resolution_requires_agent.json `
  --output agent_resolution.json
```

`api-agent-task`、`api-compose-agent` 和 `api-resolve-agent` 也不调用模型。`api-resolve-agent` 会返回 `ready` 或 `requires_agent` 状态，调用方再决定复用缓存、落库 agent result，或把任务交给外部 agent。

仓库里的 `examples/requests/agent_resolution_requires_agent.json`、`examples/requests/agent_compose_with_result.json`、`examples/requests/compose_render_plan_novelai.json`、`examples/requests/full_prompt_render_plan_novelai.json`、`examples/requests/agent_compose_render_plan_novelai.json`、`examples/requests/agent_compose_render_plan_requires_agent.json` 和 `examples/requests/generate_novelai_mock.json` 是可直接运行的请求样例，并由测试保证能从仓库根目录解析节点相对路径。

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

`render-plan` / `render-plan-nodes` 只生成 `RenderRequest`，用于 UI、队列、diff 和验收。已有 NovelAI `RenderRequest` 可以交给执行入口：

```powershell
uv run python -m tags_machine_core execute-render-request core_render_request.json `
  --config configs\local.example.yaml `
  --output-dir outputs
```

完整 prompt 入口示例：

```powershell
uv run python -m tags_machine_core run-prompt `
  --dry-run `
  --prompt "akemi homura, bare soles, foot focus" `
  --style-node examples\nodes\styles\anime_comfy `
  --seed 123 `
  --nt 3

uv run python -m tags_machine_core run-prompt `
  --prompt-file agent_prompt.txt `
  --style-ref 20260412_2 `
  --config configs\local.example.yaml `
  --output-dir outputs `
  --seed 123 `
  --nt 3
```

`run-prompt` 用于“agent 或人工已经给出完整角色+动作混合 prompt”的场景。它不会再按 `character_scope` 裁剪角色节点，只把输入落成 `PromptBundle`，再由 NovelAI adapter 叠加画风、quality、negative、V4 payload、reference/vibe 参数。`--nt` 会写入 NovelAI `n_samples`，默认值保持旧接口习惯为 3。

JSON API 边界入口：

```powershell
uv run python -m tags_machine_core api-compose-render-plan examples\requests\compose_render_plan_novelai.json `
  --output api_response.json

uv run python -m tags_machine_core api-resolve-compose-render-plan examples\requests\agent_compose_render_plan_requires_agent.json `
  --output api_resolution.json
```

`api-compose-render-plan` 会输出同一份 `PromptBundle` 和 `RenderRequest`，用于前端预览、worker 队列和验收资料包，不会联网生图。`api-resolve-compose-render-plan` 是状态入口，可返回 `ready` 或 `requires_agent`。已有 `RenderRequest` 可以通过本地 JSON API 执行：

```powershell
uv run python -m tags_machine_core api-generate api_generate.json `
  --config configs\local.example.yaml `
  --output api_generate_response.json
```

`api-generate` 对应未来 `POST /generate` 的本地文件入口，输入 `RenderRequest` JSON，输出 `GenerationResult` JSON；v1 正式执行范围只包含 NovelAI。无需联网的 mock 请求样例见 `examples/requests/generate_novelai_mock.json`，响应形状 golden 见 `examples/responses/json_api_response_shapes.json`。

`generate` 是 NovelAI 的兼容快捷入口，会直接从 prompt 生成 `RenderRequest` 并保存图片；新流程优先使用 `run-prompt --dry-run` 预览完整 `PromptBundle + RenderRequest`，确认后再去掉 `--dry-run` 生图。`execute-render-request` 默认只执行 NovelAI；ComfyUI / SD WebUI / Forge 真实执行需要 `--allow-experimental-backend`，属于预研代码，不作为本阶段接入承诺。

旧 `tags.txt` 节点迁移示例：

```powershell
uv run python -m tags_machine_core audit-legacy-tags `
  F:\my_project\new\tags_machine\design\动作改2 `
  --kind action `
  --output migration_audit_actions.yaml

uv run python -m tags_machine_core plan-legacy-tags-migration `
  F:\my_project\new\tags_machine\design\动作改2 `
  --kind action `
  --output-root migrated `
  --output migration_plan_actions.yaml

uv run python -m tags_machine_core apply-legacy-tags-migration `
  F:\my_project\new\tags_machine\design\动作改2 `
  --kind action `
  --output-root migrated `
  --output migration_apply_actions.yaml

uv run python -m tags_machine_core validate-node-tree `
  migrated\nodes `
  --output migrated_node_validation.yaml

uv run python -m tags_machine_core migrate-style-tags `
  F:\my_project\new\tags_machine\design\画风\sample_style `
  --output migrated\nodes\styles\sample_style\node.yaml

uv run python -m tags_machine_core migrate-character-tags `
  F:\my_project\new\tags_machine\design\角色\danbooru_angel_beats_207\danbooru_715_tachibana_kanade_立華かなで `
  --variant school_uniform `
  --output migrated\nodes\characters\tachibana_kanade\meta.yaml

uv run python -m tags_machine_core migrate-action-tags `
  F:\my_project\new\tags_machine\design\动作改2\next\17_20240706_1720261297 `
  --character-scope foot_detail `
  --output migrated\nodes\actions\foot_closeup\meta.yaml

uv run python -m tags_machine_core migrate-background-tags `
  F:\my_project\new\tags_machine\design\背景\simple_room `
  --output migrated\nodes\backgrounds\simple_room\meta.yaml
```

`audit-legacy-tags` 用于迁移前预检，可以扫描单个 `tags.txt`、单个旧节点目录或一个旧节点根目录；它只读源目录，不会生成 `meta.yaml` / `node.yaml`。报告里的 `summary` 会统计 `ok`、`needs_review`、`errors` 和 issue code 数量；`items` 会列出每个旧节点的迁移风险，例如 character 的 `unclassified`、action 的默认 `character_scope`、疑似混入角色外观词、旧扩展字段是否只归档不执行。

`plan-legacy-tags-migration` 在预检基础上生成批量迁移计划，只写计划文件，不写节点 YAML。计划会把旧 `tags.txt` 映射到 `--output-root\nodes\{styles|characters|actions|backgrounds}\...\{node.yaml|meta.yaml}`，并标出 `ready`、`needs_review`、`target_exists`、`blocked`、`error` 状态；遇到目标文件已存在或目标路径冲突时不会覆盖，需要人工处理。

`apply-legacy-tags-migration` 会重新生成迁移计划，然后只写出 `ready` 项对应的结构化节点；`needs_review`、`target_exists`、`blocked`、`error` 都会跳过并写入结果报告。这个命令不覆盖目标文件，也不会写旧项目目录。

`validate-node-tree` 用于迁移后只读校验结构化节点目录。它会扫描 `node.yaml` / `meta.yaml`，检查 schema/kind 是否符合 v1、character/action/background 是否使用 `meta.yaml`、style 是否使用 `node.yaml`、必需 `tags` section 是否存在、action 是否声明 `character_scope`、style 是否包含 `renderers.novelai`，并报告 v1 不允许写入节点的规则字段。失败时 CLI 退出码为 2，适合放进批量迁移后的验收脚本。

这些迁移命令默认不修改旧项目目录；只有传入 `--output` 时才写出结构化 YAML。style 迁移会保留 NovelAI 画风扩展参数；character 迁移只提升角色事实 tags，旧替换规则保留在 `legacy.raw_sections`；action 迁移只提升动作 tags、动作负向词和 `character_scope`；background 迁移只提升场景 tags 和背景级负向词，不把 `gen_json` 等旧扩展转成后端参数。

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
uv run python -m tags_machine_core archive-novelai-acceptance-prompt `
  --case-id default_action_prompt_001 `
  --output-dir acceptance `
  --legacy-source old_request.json `
  --prompt-file agent_prompt.txt `
  --style-node examples\nodes\styles\anime_comfy `
  --seed 123 `
  --nt 3 `
  --required-case default_action `
  --overwrite
uv run python -m tags_machine_core verify-acceptance-suite acceptance --require-minimum-set
uv run python -m tags_machine_core verify-acceptance-suite examples\acceptance\suite.yaml --require-minimum-set
uv run python -m tags_machine_core verify-core
```

`compare-render-params` 会完整比较 NovelAI 请求关键字段，包括 `v4_prompt`、`v4_negative_prompt`、`reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple`、`director_reference_images` 等。图片/base64 字段会用长度和 sha256 摘要比较，避免把大段 base64 打进终端。

`create-acceptance-record` 会把旧图/旧请求、新 `RenderRequest`、归一化 diff、白名单差异、`PromptBundle.meta.composition` 和可选 `GenerationResult` 归档成 JSON/YAML；如果提供 `--prompt-bundle`，会记录 `prompt_bundle_contract_evidence`，检查 `PromptBundle.meta` 没有重新引入 `shot` / `constraints`；如果提供 `--generation-result`，会验证其中的 `request_body` 与 core `RenderRequest` 归一化后一致，并检查 `GenerationResult.images` 指向的图片文件存在、大小和 sha256。`archive-acceptance-case` 会进一步把这些证据复制到独立样例目录，归档时会把 `generation_result.json` 里的图片路径改写为资料包内相对路径，并更新 suite manifest，方便后续不运行旧项目也能回放。`archive-novelai-acceptance-nodes` 会先从结构化节点生成 core 侧 `PromptBundle` 和 NovelAI `RenderRequest`，再复用同一套归档逻辑，适合批量补结构化节点 oracle 样例。`archive-novelai-acceptance-prompt` 面向完整 prompt / agent prompt 样例，只叠加 NovelAI 画风后归档，用来验证它和旧 `run_action` 或旧 `run-prompt` oracle 的 render plan 等价。`verify-acceptance-record` 会重新读取记录里的源文件并重算 diff，存在未批准差异、非法 `PromptBundle` 契约字段或丢失的生成图片证据时返回非 0。`verify-acceptance-suite` 可以验证单个 record、record 目录或 manifest；`--require-minimum-set` 会要求 `default_action`、`foot_detail`、`hand_detail`、`complex_character`、`reference_style` 五类样例都存在，并输出 `case_checks` 检查局部镜头 composition 和 reference/vibe 数组是否真的覆盖到。

`examples/acceptance/` 提供仓库内置的静态 dry-run 最小资料包，覆盖上述五类 case，并包含 `PromptBundle`、NovelAI `RenderRequest`、`GenerationResult`、PNG 参数证据和 suite manifest。它用于测试验收格式、参数归一化、图片证据读取和 `--require-minimum-set` 语义检查是否稳定；它不是旧 `tags_machine` 的真实 oracle，不能通过 `--require-legacy-oracle` 或 `--require-legacy-evidence`。真实旧项目对照仍需要用 `archive-acceptance-case` / `archive-novelai-acceptance-*` 归档旧项目产物后补充。

`verify-core` 是当前仓库内的无联网门禁快捷入口，适合每个开发切片提交前运行。它不会证明真实旧项目 oracle 已归档；真实 oracle 仍需要对 acceptance 目录单独运行 `verify-acceptance-suite --require-legacy-oracle --require-legacy-evidence`。

`--require-minimum-set` 不只是检查样例名字：

- `default_action`：检查 NovelAI 核心参数、默认 negative、V4/V4.5 payload 没有丢。
- `foot_detail` / `hand_detail`：检查 `PromptBundle.meta.composition` 的 scope、纳入 section、抑制 section 是否符合局部镜头规则，并确认最终 prompt 没有残留被抑制 section 的典型词。
- `complex_character`：检查默认角色组合没有误过滤 `hair`、`eyes`、`upper_clothes`。
- `reference_style`：检查 `reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple` 非空且长度一致，并检查 `director_reference_images` 非空。

`examples/nodes` 也有测试门禁：schema/kind 必须符合 v1；character/action/background 使用 `meta.yaml`，style 使用 `node.yaml`；节点必须包含对应的必需 `tags` section；action 必须显式声明 `character_scope`；v1 样例里不能重新引入 `shot`、`constraints`、`rules`、`include_scopes` / `exclude_scopes` 等字段。

详细文档：

- [整体设计与开发方案](docs/development_plan_v1.md)
- [JSON API 契约](docs/json_api_contract_v1.md)
- [Node YAML 规范](docs/node_yaml_spec_v1.md)
- [Character YAML 规范](docs/character_yaml_spec_v1.md)
- [Action YAML 规范](docs/action_yaml_spec_v1.md)
- [Style YAML 规范](docs/style_yaml_spec_v1.md)
- [Background YAML 规范](docs/background_yaml_spec_v1.md)
