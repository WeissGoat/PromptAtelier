# Batch Generation 真实出图验收 2026-06-13

## 设置

- backend: NovelAI
- artist: `20260412`
- model: `nai-diffusion-4-5-full`
- nt: `1`
- BatchSpec: `examples/batches/prompt_list_20260412.yaml`

## 命令

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --limit 1 --full
```

## 结果

| Case | Status | Image | GenerationResult | PNG Params | Visual Result |
| --- | --- | --- | --- | --- | --- |
| `prompt-list-20260412 / standing_001` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\03b8a8e3_0_01.png` | `outputs\batches\prompt-list-20260412\tasks\standing_001_20260412_full_akemi_homura_1girl_standing_looking_at_viewer_39081556\generation_result.json` | `outputs\batches\prompt-list-20260412\tasks\standing_001_20260412_full_akemi_homura_1girl_standing_looking_at_viewer_39081556\png_params.json` | pass |
| `prompt-list-20260412 / foot_001` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\7d488468_0_01.png` | `outputs\batches\prompt-list-20260412\tasks\foot_001_20260412_full_akemi_homura_1girl_bare_feet_foot_focus_lower_body_7f54ad88\generation_result.json` | `outputs\batches\prompt-list-20260412\tasks\foot_001_20260412_full_akemi_homura_1girl_bare_feet_foot_focus_lower_body_7f54ad88\png_params.json` | pass |

## 参数证据

- 图片 sha256: `748150FD12AE61872C792F8BAB81789366338F8C1CD7426B461C2B28EC8A47A3`
- 图片大小: `1407907` bytes
- `foot_001` 图片 sha256: `0324C291D479C76AB2BEBBFF72F1A454AF2B7DCD1BE4043EA211382095762DE2`
- `foot_001` 图片大小: `1332412` bytes
- PNG 参数读取: pass
- `compare-render-params` 对比 PNG 参数与 `generation_result.json`: `diff_count=0`
- 生成参数摘要:
  - width: `1024`
  - height: `1024`
  - sampler: `k_euler_ancestral`
  - steps: `28`
  - scale: `5.0`
  - seed: `3088295945`
  - reference_image_multiple: 已写入并可读取

## 视觉结论

人工查看图片，`standing_001` 主体为单人角色，正面站姿，画风与 `20260412` 的手绘/线稿倾向一致；`foot_001` 为脚部特写/下半身构图，符合 foot focus case。该 case 可证明 `prompt_list` 批量任务已经真实经过：

```text
BatchSpec -> BatchPlanner -> BatchRunner -> BatchExecutor
-> GenerationService -> NovelAIRenderer -> execute_render_request
-> GenerationResult + PNG 参数归档
```

## Agent Cache Miss 验收

命令：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\agent_cache_miss.yaml --limit 1 --full
```

结果：

- status: `requires_agent`
- NovelAI 调用: 未触发
- agent task: `outputs\batches\agent-cache-miss\agent_tasks\danbooru_akemi_homura_暁美_魔法少女_0_0309_1709954237_20260412_agent_cacfc97d.json`

## Agent Result 回填真实出图

回填文件：

```text
outputs\batches\agent-cache-miss\agent_results\danbooru_akemi_homura_暁美_魔法少女_0_0309_1709954237_20260412_agent_cacfc97d.json
```

回填内容摘要：

```json
{
  "positive": "akemi_homura, 1girl, bare feet, foot focus, lower body, standing",
  "negative": "bad feet, extra toes"
}
```

再次执行：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\agent_cache_miss.yaml --limit 1 --full
```

结果：

| Case | Status | Image | Parameter Diff | Visual Result |
| --- | --- | --- | --- | --- |
| `agent-cache-miss / first action` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\39d47fed_0_01.png` | `diff_count=0` | pass |

参数证据：

- 图片 sha256: `BA273EC6C100926674B68C7295CF79DEF917E3B3340250992886A228B4FFCC83`
- 图片大小: `1676881` bytes
- `compare-render-params` 对比 PNG 参数与 `generation_result.json`: `diff_count=0`
- `v4_prompt.caption.char_captions[0].char_caption`: `girl, akemi_homura`

视觉结论：

人工查看图片，主体为下半身/脚部构图，脚部可见，画风与 `20260412` 一致。该 case 验证了：

- action folder selector 可以选出旧 design 动作节点。
- agent cache miss 可以先保存 agent task。
- `agent_results/<task_id>.json` 回填后可以继续真实出图。
- NAI4 character prompts 自动模式在 agent 回填链路中生效。

## Resume 验收

对已成功的 `prompt-list-20260412 / standing_001` 再次执行：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --limit 1 --full
```

结果：

- 本次运行返回 `skipped: 1`
- 任务 `status.json` 仍保持 `succeeded`
- 未重新调用 NovelAI

## Prompt File 真实出图验收

命令：

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
uv run python -m tags_machine_core run-batch examples\batches\prompt_file_20260412.yaml --limit 1 --full
```

结果：

| Case | Status | Image | Parameter Diff | Visual Result |
| --- | --- | --- | --- | --- |
| `prompt-file-20260412 / prompts_20260412_0001` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\8f13219e_0_01.png` | `diff_count=0` | pass |

参数证据：

- 图片 sha256: `69441744A373AB768EB315B2F3FFE9E00262E52ADC3BF70C5E552D26D6093139`
- 图片大小: `1341757` bytes
- `compare-render-params` 对比 PNG 参数与 `generation_result.json`: `diff_count=0`
- 分辨率: `832x1216`，来自 `resolution: random_standard`
- `reference_image_multiple`: 已写入并可读取，PNG 参数与 `GenerationResult.request_body` 一致。

视觉结论：

人工查看图片，主体为单角色站姿，正面视线，画风与 `20260412` 的线稿/水彩倾向一致。该 case 验证了 `prompt_file` selector 可以从文本文件展开完整 prompt，并继续走真实 NovelAI 生图链路。

## Action Folder / Collection 真实出图验收

为避免该验收被 agent cache miss 卡住，本次使用临时 spec 将 `composer` 设为 `script`，只验证旧 `design` 动作分类文件夹选择、collection 展开、脚部动作节点读取、NovelAI 出图和归档链路。

命令：

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
uv run python -m tags_machine_core run-batch examples\batches\action_folder_script_20260412.yaml --limit 3 --full
```

结果：

| Case | Status | Image | Parameter Diff | Visual Result |
| --- | --- | --- | --- | --- |
| `action-folder-script-20260412 / 0_0309_1709954237` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\80d3a228_0_01.png` | `diff_count=0` | pass |
| `action-folder-script-20260412 / 10_20240810_1723219638` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\f34fec5d_0_01.png` | `diff_count=0` | pass |
| `action-folder-script-20260412 / 11_裸足_聚焦` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\82f1e0c8_0_01.png` | `diff_count=0` | pass with note |

参数证据：

- `80d3a228_0_01.png` sha256: `E05558D60ED298CE9DBD23500E6087A33893E2AD9DF355BF303279E1B93D0672`, size: `1909503` bytes
- `f34fec5d_0_01.png` sha256: `34D3435C4ACD03D3E122A6559DC3F3F7795E1E1B14C3C6075866F4C659FDE1CD`, size: `1313749` bytes
- `82f1e0c8_0_01.png` sha256: `880B10CB6A48DAE5A001433A12763A41C400BD947B651DFCC6085740678E0C9F`, size: `1138206` bytes
- 三张图片的 `compare-render-params` 对比结果均为 `diff_count=0`。

视觉结论：

- 第一张：足部/腿部主体明确，角色和 `20260412` 画风一致。
- 第二张：足部/束缚腿部动作明确，角色和 `20260412` 画风一致。
- 第三张：脚部元素存在，但足部动作表达弱于前两张；链路和参数验收通过，后续应归入 ScriptComposer / 动作 prompt 质量优化。

该 case 验证了：

- `collection selector` 可以映射旧 `design/动作改2/st_ft_bare` 分类文件夹。
- `folder selector` 可以发现旧 action 节点。
- `script` composer 可以把 character + action + artist 传入现有 `GenerationService` 和 NovelAI renderer。
- 每个成功任务都归档了 `task.json`、`status.json`、`prompt_bundle.json`、`render_request.json`、`generation_result.json`、`png_params.json`、`images.json`。

## Batch JSON API 入口验收

命令：

```powershell
uv run python -m tags_machine_core api-plan-batch $env:TEMP\api_batch_plan_request.json --full
uv run python -m tags_machine_core api-run-batch $env:TEMP\api_batch_run_request.json --full
uv run python -m tags_machine_core api-resume-batch $env:TEMP\api_batch_resume_request.json --full
uv run python -m tags_machine_core api-inspect-batch $env:TEMP\api_batch_inspect_request.json --full
```

结果：

- status: pass
- schema: `tags-machine-core.api-plan-batch-result/v1`
- task_count: `2`
- `api-plan-batch` 支持 PowerShell BOM JSON request，内部复用 `BatchPlanner` 和同一套 manifest 写入逻辑。
- `api-run-batch` 在 resume 场景返回 `skipped: 1`，没有重复调用 NovelAI。
- `api-resume-batch` 在显式 run_dir + batch_spec 场景返回 `skipped: 1`，没有重复调用 NovelAI。
- `api-inspect-batch` 返回 `succeeded: 1`、`pending: 1`，并从 task `status.json` 回读成功任务图片路径。

## Character Action Group 真实出图验收

### 目标

验证 `character_action_group` 批量展开模式已经打通真实 NovelAI 出图链路：

```text
BatchSpec.select.characters
-> BatchSpec.select.action_groups
-> BatchPlanner(character_action_group)
-> BatchRunner
-> BatchExecutor
-> ScriptComposer
-> NovelAIRenderer
-> NovelAI execution
-> GenerationResult + PNG 参数
```

### 配置

- BatchSpec: `examples/batches/character_action_group_20260412.yaml`
- strategy: `balanced_random`
- action_group_record: `cache/batch/character_action_group_20260412_record.json`
- artist: `20260412`
- composer: `script`
- model: `nai-diffusion-4-5-full`
- limit: `1`

### 规划验证

命令：

```powershell
if (Test-Path 'cache\batch\character_action_group_20260412_record.json') {
  Remove-Item -LiteralPath 'cache\batch\character_action_group_20260412_record.json' -Force
}
uv run python -m tags_machine_core plan-batch examples\batches\character_action_group_20260412.yaml --log-level info --full
```

结果：

- `task_count`: `4`
- `selector_summary.composers.script`: `4`
- `selector_summary.node_roles.character`: `4`
- `selector_summary.node_roles.action`: `4`
- `selector_summary.action_groups.st_rp`: `2`
- `selector_summary.action_groups.st_sfw`: `2`

日志证明 planner 按角色选择动作组：

```text
batch plan action_groups resolved groups=3 characters=2 strategy=balanced_random
action group selected character=danbooru_akemi_homura_暁美ほむら _魔法少女 group=st_rp strategy=balanced_random action_count=2 selected_count=1
action group selected character=danbooru_kaname_madoka_鹿目まどか_魔法少女 group=st_sfw strategy=balanced_random action_count=2 selected_count=1
```

### 真实出图验证

命令：

```powershell
if (Test-Path 'cache\batch\character_action_group_20260412_record.json') {
  Remove-Item -LiteralPath 'cache\batch\character_action_group_20260412_record.json' -Force
}
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
uv run python -m tags_machine_core run-batch examples\batches\character_action_group_20260412.yaml --limit 1 --log-level info --full
```

结果：

| Case | Status | Image | Task Dir | GenerationResult | PNG Params | Visual |
| --- | --- | --- | --- | --- | --- | --- |
| `character-action-group-20260412 / st_rp` | succeeded | `F:\my_project\new\tags_machine\refactor\outputs\f28188dd_0_01.png` | `outputs\batches\character-action-group-20260412\tasks\danbooru_akemi_homura_暁美_魔法少女_st_rp_00_licks_penis_disgustingly_20260412_14807e1a` | `outputs\batches\character-action-group-20260412\tasks\danbooru_akemi_homura_暁美_魔法少女_st_rp_00_licks_penis_disgustingly_20260412_14807e1a\generation_result.json` | readable | pass |

关键输出：

- `counts.succeeded`: `1`
- `source.action_group`: `st_rp`
- `source.action_group_strategy`: `balanced_random`
- `source.action_group_record`: `cache\batch\character_action_group_20260412_record.json`
- `source.action_index_in_group`: `0`
- `source.action_count_in_group`: `2`
- `png_params_summary.has_png_info`: `true`

PNG 参数读取命令：

```powershell
uv run python -m tags_machine_core inspect-image-params outputs\f28188dd_0_01.png --normalized --full
```

PNG 参数验证：

- `model`: `nai-diffusion-4-5-full`
- `width`: `832`
- `height`: `1216`
- `n_samples`: `1`
- `steps`: `28`
- `sampler`: `k_euler_ancestral`
- `reference_image_multiple`: present
- `v4_prompt.caption.char_captions`: present
- `v4_negative_prompt.caption.char_captions`: present

业务结论：

- `character_action_group` 可以读取多个角色和多个动作分类。
- `balanced_random` 可以为角色选择动作组，并写入 `task.source`。
- 产出的任务仍然走普通 `BatchTask -> BatchExecutor -> Composer -> Renderer -> NovelAI` 链路。
- 真实 NovelAI 出图成功，图片可读取 PNG 参数。

## 当前结论

- `plan-batch` 可以展开 prompt list 和 action collection。
- `plan-batch` 可以展开 `character_action_group`，并在 summary 中统计 `action_groups`。
- `api-plan-batch` 可以从 JSON request 展开 batch 任务。
- `api-run-batch`、`api-resume-batch` 和 `api-inspect-batch` 可以通过 JSON request 驱动同一套 batch runner / manifest 链路。
- `prompt_file` selector 可以从文本文件展开完整 prompt 并真实出图。
- `action folder` / `collection selector` 可以从旧动作分类展开 3 个任务并真实出图。
- `character_action_group` 可以按角色选择动作分类并真实出图。
- `run-batch` 可以真实调用 NovelAI，并归档 `task.json`、`prompt_bundle.json`、`render_request.json`、`generation_result.json`、`png_params.json`、`images.json`。
- `inspect-batch` 可以读取 manifest。
- `agent` 模式 cache miss 会保存 agent task，不会误调用 NovelAI；回填 agent result 后可以继续真实出图。
- `resume` 可以跳过已成功任务。

## 待继续补强

- `retry` 当前已按异常文本匹配实现并写入 report，但还需要真实 429/502 场景补充业务记录。
- `report.md` 是按单次运行写入，resume 后会显示本次 skipped 结果；后续可以增加 `report_history.md` 或 inspect 级总览。
