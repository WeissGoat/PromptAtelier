---
name: compose-contract-review
description: >-
  用于 PromptAtelier 契约出图后的复核、挑图与重出建议。主 Agent 准备审片材料并裁决，图片复核子 Agent 看联系表、原图和候选，核实实际画面与前后帧穿帮。
---

# 复核 Agent 拼接契约的出图结果

## 主 Agent 准备材料与裁决

1. 用 `contract show`、`contract results` 读取契约与结果，再用 `contract review <id> --sheets` 准备联系表、`audit` 和 `todo`。标出失败、缺图、排队及只有旧图的帧，分别注明画风、轮次和词版。
2. 将[图片复核派单模板](../../../src/tags_machine_core/compose_contracts/writing_guide.md#图片复核派单模板)连同用户原始要求、计划、最终词块、联系表和原图交给能看图的子 Agent。分段时带上相邻帧。主 Agent 默认只读审片报告，核对覆盖、交界和证据。缺少证据就指定帧号退回补看，缺少看图子 Agent 就标明待视觉复核。
3. 在修订任务中，主 Agent 依据报告修正有问题的提示词，重新交提示词复核子 Agent 审查。修补并复核最终版后按授权重出，再把新图和上轮问题交给图片复核子 Agent。若仍有待修问题，继续从改词开始。用户只要求审片时，交付报告和修订建议。最终采用由用户选择。见[修订与重出流程](../../../src/tags_machine_core/compose_contracts/writing_guide.md#提示词修订与重出流程)。

## 图片复核子 Agent 审片

收到看图派单，从指定轮次的 `overview_*.jpg` 开始，按帧顺序比较画面。对疑点打开该帧和前后帧原图，用 `frames_*.jpg` 对比同帧候选。用[图片复核派单模板](../../../src/tags_machine_core/compose_contracts/writing_guide.md#图片复核派单模板)中的证据要求交付逐帧报告。四项红线及判定细则见[共享质检清单](../../../src/tags_machine_core/compose_contracts/writing_guide.md#红线质检清单最小检查维度)。

排查可能原因时，可对照 `prompt_issues`（如 `identity_anchor`、`frame_novelty`）、`audit.warnings`（画幅、正负词冲突、分角色块是否生效）及 `audit.params`（模型、步数、CFG、采样器和尺寸）。图片提供画面证据，元数据帮助解释差异，任务记录用于辨认网络或额度等生成失败。

## 命令（在 PromptAtelier 仓库根目录执行）

| 命令 | 作用 |
|---|---|
| `uv run tm-core contract results <id> [--frames f01-f30] [--artist <画风>] [--current-only] [--all]` | 每帧状态和最新一轮的图（`--all` 列全部）、各轮次、失败原因 |
| `uv run tm-core contract review <id> --sheets [--frames …] [--artist …] [--current-only] [--per-frame 8] [--out <目录>]` | 结构化复核 + 联系表；输出里的 `sheets` 是图片路径，`todo` 是待办 |
| `uv run tm-core contract show <id> --frames f10-f14` | 看某几帧的提示词，定位问题 |
| `uv run tm-core contract check <id>` | 改完契约后重新校验 |
| `uv run tm-core contract generate <id> --artist <用户指定的ref> --frames f10-f14 --dry-run` | 预检；实际出图去掉 --dry-run，可加 --wait。默认跳过相同参数，想要新候选加 --force |
| `uv run tm-core contract job <任务id> --wait` | 等待已提交的任务；结果含图片路径，超时不要重提 |

帧状态（`status`）：`ok` 有图；`missing` 缺图；`stale` 只有旧提示词出的图（提示词改过还没重出）；
`failed` 这一帧最近一次出图失败（`failure.error` 是原因，来自 Web 出图任务记录）；`pending` 排队或生成中。
`pending` 依据的是任务记录；后端中途关掉的话会一直显示 pending，以 Web 任务面板为准。

联系表默认写到 `<出图目录>/.contract_review/<id>/`，每次覆盖：
- `overview_NN.jpg`：每帧一张代表图（已采用 > 当前提示词 > 其他，新的在前），按帧顺序排，看整条故事线；
- `frames_NN.jpg`：每帧一行全部候选。左边色条：绿=有图、灰=只有旧图、红=缺图或失败、蓝=排队；金框=已采用；「旧」=用旧提示词出的图。

生图命令连接运行中的后台，默认读取 `runtime/dev_web.json`，可用 `--server` 或 `$PROMPTATELIER_URL` 指定。用户要求测试或重出时，主 Agent 使用用户指定的画风和帧范围。完整参数与后台配置见 `compose-contract-author`。查看特定画风或当前词版的图时，加 `--artist` 或 `--current-only`。
