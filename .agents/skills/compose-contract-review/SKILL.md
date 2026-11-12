---
name: compose-contract-review
description: >-
  复核 PromptAtelier「Agent 拼接契约」的出图结果：找出缺图、失败、只有旧提示词的帧，看联系表检查人物是否换人、
  服装和道具是否回退、相邻帧是否雷同，读 PNG 元数据核对参数和负面词，然后给出逐帧修改建议或直接改契约。
  在契约出过图之后、用户要求「看看结果 / 复核 / 挑图 / 哪些帧要重出」时使用；写契约本身用 compose-contract-author。
---

# 复核 Agent 拼接契约的出图结果

写契约（规划、写帧、`contract check`）用 `compose-contract-author`；这个 Skill 管出图之后。
出图可在 Web 或用 `contract generate` 提交（会花额度）。用户要求测试、例图或重出时可使用该命令；先确认用户指定的画风（已指定则沿用），只生成所需帧。仅要求复核时先读现有结果。

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

## 流程

1. `contract review <id> --sheets`。先看 `counts` 和 `todo`：失败和缺图的帧列出来，错误是网络 / 额度 / Cloudflare 这类的，不用改提示词；用户要求重出时可用 `contract generate` 或 Web。
2. 打开 `overview_*.jpg` 按顺序看整条故事线，逐项查连续性：
   - 人物：是不是同一个人（发色、瞳色、发型、标志物）；特写帧最容易换人。
   - 服装阶段、道具（口塞、绳索、武器）、身体痕迹：有没有无故回退或跳变。
   - 姿势与位置、人数与关系、镜头方向 / POV：前后能不能接上。
   - 相邻帧是否雷同到只像换了 seed。
3. 可疑的帧再看 `frames_*.jpg` 里的全部候选，区分「提示词问题」（每张都错）和「运气问题」（个别 seed 错，挑别的或多出几张）。
4. 结合 `prompt_issues`（`identity_anchor`、`frame_novelty` 等校验结果）和 `audit`：
   - `audit.warnings` 里的画幅不符、正负面词打架、成人契约的负面词里有 `nsfw`、分角色块没生效，按提示处理；
   - `audit.params` 列出每个画风实际用的模型、步数、CFG、采样器和尺寸，同一画风出现多种组合时确认是不是有意的。
5. 给用户一份逐帧的结论：哪些帧可用（建议采用哪张）、哪些要重出、哪些要改提示词以及怎么改。
   用户同意后直接改契约文件里对应帧的提示词，改完 `contract check`；已要求测试或重出时按用户指定画风生成这些帧，否则告知哪些帧需要重出（旧图会变成 `stale`）。

## 注意

- 生图命令连接正在运行的后台，默认读 `runtime/dev_web.json`，可用 `--server` 或 `$PROMPTATELIER_URL` 指定；不接受 `--config / --root`，参数详见 `compose-contract-author`。

- 判断「换人」「回退」要看图，不要只看提示词；校验器只能抓到提示词层面的问题。
- 挑图的结论写给用户，采用（星标）由用户在 Web 里点；不要改 `.contract_picks` 下的文件。
- 只看某个画风或只看当前提示词的图时加 `--artist` / `--current-only`，避免旧轮次干扰判断。
