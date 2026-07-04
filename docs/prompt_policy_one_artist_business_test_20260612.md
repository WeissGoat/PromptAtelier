# PromptPolicyPipeline 单画风真实出图业务测试 2026-06-12

## 测试目标

按业务验收优先，不做 dry-run，不以单元测试为主要依据。固定一个画风测试 `PromptPolicyPipeline` 的不同 rule，避免画风差异干扰规则结论。

## 固定设置

- 画风：`20260412`
- 模型：`nai-diffusion-4-5-full`
- 配置：`configs/local.example.yaml`
- 命令入口：`run-prompt`
- 规则配置：`--prompt-policy-profile balanced`
- 每个 case：`--nt 1`
- 尺寸：`1024x1024`
- 输出目录：`F:\my_project\new\tags_machine\refactor\outputs\prompt_policy_real_20260611_one_artist_20260412`

## 参数验收

7 个 case 都已真实出图。每张图均提取 PNG 参数，并与对应 `GenerationResult` 对比：

- `png_gen_match: true`
- `diff_count: 0`

说明最终写入 PNG 的参数与 core 记录的生成请求一致。

## Case 结果

| Case | 覆盖 rule | 图片 | 最终 prompt 关键结果 | 视觉结论 |
| --- | --- | --- | --- | --- |
| `rule01_normalize_dedupe` | `tag_normalize`、`dedupe`、`character_count` | `5d8678b9_246814101_01.png` | `akemi homura` -> `akemi_homura`，`bare feet` -> `bare_feet`，重复 tag 被移除，`1girl` 前置 | 参数通过；视觉是 Homura 单人图 |
| `rule02_tag_conflict_barefoot` | `tag_conflict` | `db96e4f5_246814102_01.png` | 保留 `barefoot`、`bare_feet`，移除 `high_heels`、`socks`、`pantyhose`、`boots` | 画面为赤脚，无明显鞋袜，视觉通过 |
| `rule03_character_count_add` | `character_count` | `60ba6956_246814103_01.png` | 无人数 tag 时自动补 `1girl` 并前置 | 单人图，视觉通过 |
| `rule04_character_count_keep_2girls` | `character_count` | `c44b57e7_246814104_01.png` | 显式 `2girls` 保留并前置，没有额外补 `1girl` | 两个角色稳定出现，视觉通过 |
| `rule05_clothing_policy_control` | `clothing_policy` | `3ae6d754_246814105_01.png` | 移除 `school_uniform`、`skirt`、`jacket`，添加 `{{alternative_clothing}}` | 未表现为校服/裙装，衣着被改写，视觉通过 |
| `rule06_visibility_foot_detail` | `visibility_policy` | `dc09fabc_246814106_01.png` | 移除 `long_hair`、`purple_eyes`、`school_uniform`、`white_shirt`、`black_jacket`，保留 `bare_feet`、`foot_focus`、`soles`、`lower_body`、`head_out_of_frame` | 明显脚部特写，头部裁切，视觉通过 |
| `rule07_visibility_from_back` | `visibility_policy` | `21c61a4a_246814107_01.png` | 移除 `purple_eyes`、`blue_eyes`，但 `looking_at_viewer`、`smile`、`mouth` 仍保留 | 画面变成回头看镜头，背面镜头失败 |

## 业务结论

固定 `20260412` 后，当前 `balanced` 规则里已经有效的部分：

- 空格/下划线规范化可用。
- 重复 tag 去重可用。
- 赤脚与鞋袜冲突过滤可用。
- 人数 tag 自动补全和前置可用。
- `clothing_control` 场景的衣着过滤可用。
- 脚部局部特写场景能过滤显式头发、眼睛、上衣/校服类 tag，并在真实出图里明显改善构图。

当前明确失败点：

- `from_back` / `facing_away` 只过滤了眼睛类 tag，没有过滤 `looking_at_viewer`、`smile`、`mouth` 等脸部/视线/表情 tag。
- 因为这些 tag 仍在最终 prompt 里，实际图片会变成“背对身体但回头看镜头”，不满足背面镜头业务目标。

## 下一步建议

下一步优先修 `visibility_policy`：

- `from_back`、`facing_away`、`head_down`、`blindfold` 等触发时，同时过滤 `looking_at_viewer`、`smile`、`mouth`、`face`、`expression`、`nose`。
- 修完后只重跑 `rule07_visibility_from_back`，仍固定 `20260412`，用真实出图验收。

