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

## 参数证据

- 图片 sha256: `748150FD12AE61872C792F8BAB81789366338F8C1CD7426B461C2B28EC8A47A3`
- 图片大小: `1407907` bytes
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

人工查看图片，主体为单人角色，正面站姿，画风与 `20260412` 的手绘/线稿倾向一致。该 case 可证明 `prompt_list` 批量任务已经真实经过：

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

## 当前结论

- `plan-batch` 可以展开 prompt list 和 action collection。
- `run-batch` 可以真实调用 NovelAI，并归档 `task.json`、`prompt_bundle.json`、`render_request.json`、`generation_result.json`、`png_params.json`、`images.json`。
- `inspect-batch` 可以读取 manifest。
- `agent` 模式 cache miss 会保存 agent task，不会误调用 NovelAI；回填 agent result 后可以继续真实出图。
- `resume` 可以跳过已成功任务。

## 待继续补强

- `retry` 当前已按异常文本匹配实现，但还需要用可控的假 executor 或真实 429/502 场景补充业务记录。
- `report.md` 是按单次运行写入，resume 后会显示本次 skipped 结果；后续可以增加 `report_history.md` 或 inspect 级总览。
