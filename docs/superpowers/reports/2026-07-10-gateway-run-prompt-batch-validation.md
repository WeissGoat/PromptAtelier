# 2026-07-10 gateway run-prompt / batch 业务验证报告

## 结论

本轮验证确认：`ai-image-gateway` raw NovelAI executor 已经能通过两条主业务链路真实出图。

- 父项目 `prompt_preset_service.py run-prompt` 能走到 `refactor`，再走 `ai-image-gateway` raw provider，最终生成 NovelAI 图片。
- `nt > 1` 且未显式指定分辨率时，会拆成多次 `n_samples=1` 请求；seed 按请求递增，分辨率从标准尺寸中轮换。
- `refactor run-batch` 在 mock 和真实 NovelAI 两种模式下都能完成任务、归档 `GenerationResult`、读取 PNG 参数。
- 直接运行 `refactor` CLI 时仍要求显式提供 `NAI_ACCESS_TOKEN`；父项目 bridge 可以从旧 `novelai/client.py` 自动读取 token。这是当前刻意保留的边界：`refactor` 不反向依赖旧 tags_machine。

## 验证环境

- 父项目目录：`F:\my_project\new\tags_machine`
- refactor 子模块目录：`F:\my_project\new\tags_machine\refactor`
- refactor 分支：`codex/refactor-core-gateway-integration`
- refactor 实现提交：`9c1fb22 feat: integrate ai-image-gateway raw novelai executor`
- refactor 验证报告提交：`2e18a09 docs: record gateway business validation`（原分支）/ `2bd0071 docs: record gateway business validation`（validation-only 分支）
- 父项目分支：`dev`
- 父项目提交：`85d4bfe feat: route run-prompt through gateway-backed refactor`
- NovelAI executor 配置：`generation.executor: ai_image_gateway_raw`

## 验证 1：父项目 run-prompt 单图真实出图

目的：确认 agent 面向入口 `prompt_preset_service.py run-prompt` 可以通过 bridge 进入新 core，并由 gateway raw executor 完成真实 NovelAI 出图。

输出图片：

```text
F:\my_project\new\tags_machine\custom_generateoutput_dir\gateway_bridge_check\864d6860_123456_01.png
```

确认结果：

- 图片生成成功。
- PNG 参数可读取。
- 模型为 `nai-diffusion-4-5-full`。
- 图片尺寸为 `1024x1024`。
- `n_samples` 为 `1`。
- PNG 参数中保留了 `reference_image_multiple` / `reference_strength_multiple`，说明 artist 的 vibe/reference 参数没有丢。

## 验证 2：父项目 run-prompt 多图拆请求

命令：

```powershell
uv run python prompt_preset_service.py run-prompt `
  --prompt "akemi_homura, 1girl, standing, looking at viewer" `
  --artist 20260412 `
  --nt 3 `
  --seed 223344 `
  --output_dir custom_generateoutput_dir\gateway_bridge_nt3 `
  --format png
```

输出图片：

```text
F:\my_project\new\tags_machine\custom_generateoutput_dir\gateway_bridge_nt3\4a6d1568_223344_01.png
F:\my_project\new\tags_machine\custom_generateoutput_dir\gateway_bridge_nt3\d6530171_223345_01.png
F:\my_project\new\tags_machine\custom_generateoutput_dir\gateway_bridge_nt3\d0e68243_223346_01.png
```

确认结果：

| 图片 | seed | 尺寸 | n_samples |
| --- | ---: | --- | ---: |
| `4a6d1568_223344_01.png` | `223344` | `1216x832` | `1` |
| `d6530171_223345_01.png` | `223345` | `832x1216` | `1` |
| `d0e68243_223346_01.png` | `223346` | `1024x1024` | `1` |

说明：

- 这条链路保持了“多图拆单图请求”的策略，避免一次 `n_samples=3`。
- 未显式指定分辨率时，会使用标准尺寸集合，而不是固定 `1024x1024`。
- gateway raw executor 下不再强制旧 client 的 `timeout=1`，避免真实生成请求过早超时；仍保留 retry 逻辑。

## 验证 3：refactor run-batch mock

命令：

```powershell
uv run python -m tags_machine_core run-batch examples/batches/prompt_list_20260412.yaml --mock-client --fresh --limit 2 --output-root outputs/batches-gateway-review-mock
```

确认结果：

- 2 个任务成功。
- BatchPlanner / BatchRunner / BatchExecutor / Archive 链路可以跑通。
- mock 模式不会调用 NovelAI，适合快速验证任务展开和归档结构。

## 验证 4：refactor run-batch 真实 NovelAI

第一次直接运行失败：

```text
Missing NovelAI token environment variable: NAI_ACCESS_TOKEN
```

这是预期行为。`refactor` 作为新 core，不从父项目旧 `novelai/client.py` 抓 token。

设置 token 后运行：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
$client = Get-Content 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
if ($client -match 'return\s+"([^"]+)"') { $env:NAI_ACCESS_TOKEN = $matches[1] }
uv run python -m tags_machine_core run-batch examples/batches/prompt_list_20260412.yaml --fresh --limit 1 --output-root outputs/batches-gateway-review-real-token
```

输出图片：

```text
F:\my_project\new\tags_machine\refactor\examples\batches\outputs\batches-gateway-review-real-token\prompt-list-20260412\outputs\8fd89a8c_0_standing_001_20260412_a6ceea71\4eccf6f9_0_01.png
```

归档文件：

```text
F:\my_project\new\tags_machine\refactor\examples\batches\outputs\batches-gateway-review-real-token\prompt-list-20260412\outputs\8fd89a8c_0_standing_001_20260412_a6ceea71\generation_result.json
F:\my_project\new\tags_machine\refactor\examples\batches\outputs\batches-gateway-review-real-token\prompt-list-20260412\outputs\8fd89a8c_0_standing_001_20260412_a6ceea71\png_params.json
```

确认结果：

- 真实 NovelAI 出图成功。
- `generation_result.json` 中保留 `request_body`。
- `png_params.json` 中保留 NovelAI PNG 参数。
- `png_params.json` 中包含 `tags_machine_core` 元信息。
- `png_params.json` 中包含 `ai_image_gateway.retry_records`，且本次 `status_code = 200`。
- artist `20260412` 的 reference/vibe 参数进入最终请求和 PNG 参数。

## 当前边界

- 父项目 `prompt_preset_service.py run-prompt` 是 agent 面向入口，保留旧 token 自动桥接能力。
- `refactor` CLI 是新架构入口，默认只读取环境变量或配置，不 import 旧项目代码。
- 当前只验证 NovelAI；ComfyUI / SD 仍不在本阶段范围。
- 本报告只记录真实业务验证和结果路径，不提交生成图片目录。

## 下一步建议

1. 保持 `refactor` 的 token 边界：直接 CLI 继续要求 `NAI_ACCESS_TOKEN`，不要让 core 依赖旧 tags_machine。
2. 给父项目增加 batch 便捷入口前先确认命令面；如果要给 agent 用，建议像 run-prompt 一样只暴露少量稳定参数。
3. 后续每次改动 NovelAI renderer、gateway executor、batch executor，都至少跑一个真实 NovelAI case，并记录图片路径和 PNG 参数结论。
