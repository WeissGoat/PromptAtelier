# NovelAI 真实对比状态 v1

本文记录 `tags_machine_core` 与旧 `tags_machine` 的真实 NovelAI 出图对比进度。对比集保存在本地
`acceptance_compare/`，该目录包含真实 PNG、完整 request body、PNG 参数和报告，不纳入 git。

## 验收口径

- 旧项目只作为只读基准，不 import 旧项目代码。
- core 通过 `configs/local.example.yaml` 的 `legacy.design_root` 读取旧 `design`。
- 对比必须同时看参数和视觉：
  - 参数对比使用 `compare-render-params` / `compare-image-result`，包含 `reference_image_multiple`、`reference_strength_multiple`、V4 prompt、negative prompt、sampler、steps、scale、seed、尺寸等字段。
  - 视觉对比人工检查主体、动作、镜头、画风是否一致。
- 兼容旧 `run_action` 时，core 优先使用旧 PNG 中抽出的最终完整 prompt，通过 `run-prompt --params-json {"prompt_mode":"legacy-final"}` 进入 NovelAI 链路，避免把旧 formula 的 hardcode 带回新 composer。

## 已完成真实 case

| case | 覆盖入口 | 风格 | 结论 |
| --- | --- | --- | --- |
| `real_run_prompt_style002_001` | 旧 `run-prompt` vs core `run-prompt` | 普通 style | `pass`，参数 diff 0，视觉通过 |
| `real_run_action_homura_the_bro_5_001` | 旧 `run_action` vs core `run-prompt` | `the_bro_5`，带 reference/vibe | `pass`，参数 diff 0，视觉通过 |
| `real_run_action_foot_detail_homura_the_bro_5_001` | 旧 `run_action` 脚部局部特写 vs core `run-prompt` | `the_bro_5`，带 reference/vibe | `pass`，参数 diff 0，视觉通过 |

脚部局部特写 case 的关键结果：

- 旧图：`acceptance_compare/real_run_action_foot_detail_homura_the_bro_5_001/legacy/.../blackboard_next_character_1779899137_31779899138_1779604201_0.png`
- core 图：`acceptance_compare/real_run_action_foot_detail_homura_the_bro_5_001/core/21301cba_1779604201_01.png`
- 参数对比：`match: true`，`diff_count: 0`
- core request vs core PNG 参数：`match: true`，`diff_count: 0`
- PNG 文件 hash 不同，解码像素也存在极小差异：
  - 总像素：1,011,712
  - 差异像素：6,318
  - 差异比例：约 0.624%
  - 最大单通道差：1
  - 结论：肉眼视觉一致，属于极小像素级差异，不影响本阶段“效果一致”验收。

## 当前结论

`run-prompt` 作为 core 稳定主链路已经通过三类真实 NovelAI 对比：

- 完整 prompt 直跑。
- 旧 `run_action` 最终 prompt 兼容输入。
- 脚部局部特写这类容易暴露角色与动作割裂问题的输入。

这证明当前 NovelAI Renderer / Adapter 的参数兼容层可用；后续重点应转向新 composer / AgentComposer 的提示词质量评估，而不是继续把旧 formula 逐字搬进 core。

## 后续建议

- 保留 `legacy-final` 作为旧项目验收兼容层，不扩大到新 composer 的默认逻辑。
- 新增 AgentComposer 真实 case 时，记录“语义一致/改进”而不是要求和旧 `run_action` 逐字一致。
- 后续如果继续在 PowerShell 下跑 `--params-json`，需要对传给 native Python 的双引号做转义，例如 `{\"prompt_mode\":\"legacy-final\"}`；更长期可以给 CLI 增加 `--params-json-file`，减少 shell 引号问题。
