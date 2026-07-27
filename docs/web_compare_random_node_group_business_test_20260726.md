# Web Compare 随机节点组内共享业务验收

## 验收目标

验证 Compare Matrix 使用随机 Action 时：

- 同一 NT Group 内所有矩阵组合共享同一个随机 Action。
- 不同 Group 重新抽取 Action。
- 同组 seed 一致，不同组 seed 不同。
- 结论从实际生成 PNG 的参数读取，不依赖前端请求对象。

## 运行配置

- Artist: `109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable`
- Character: `danbooru_akemi_homura_暁美ほむら _魔法少女`
- Action: Folder `new` 随机节点
- Action classify: `domain=foot`、`subtype=sole_focus`
- Prompt Behavior: `Default`、`No Character Prompts`
- NT: `2`
- Base seed: `424242`
- Matrix: `1 Artist × 1 Character × 1 Action × 2 Behavior × 2 Group = 4 images`

## 实际结果

### Group 1

- Seed: `424242`
- Action: `口塞足交捆绑精液_4star`
- Random draw: `draw_index=0`、`deck_cycle=1`
- Image: `F:/my_project/new/tags_machine/refactor/outputs/compare_20260726041538_f9fef0ad/group_001_seed_424242/e0681223_424242_01.png`
- Image: `F:/my_project/new/tags_machine/refactor/outputs/compare_20260726041538_f9fef0ad/group_001_seed_424242/ff8d40bb_424242_01.png`

### Group 2

- Seed: `424243`
- Action: `20260531_脚部脱鞋特写坐姿`
- Random draw: `draw_index=1`、`deck_cycle=1`
- Image: `F:/my_project/new/tags_machine/refactor/outputs/compare_20260726041538_f9fef0ad/group_002_seed_424243/2e07b79d_424243_01.png`
- Image: `F:/my_project/new/tags_machine/refactor/outputs/compare_20260726041538_f9fef0ad/group_002_seed_424243/7e03f329_424243_01.png`

## PNG 参数验证

使用 `tags_machine_core.verification.read_image_parameters()` 读取四张实际 PNG：

| Group | Image | seed | random action | draw_index |
| --- | --- | ---: | --- | ---: |
| 1 | `e0681223_424242_01.png` | 424242 | `口塞足交捆绑精液_4star` | 0 |
| 1 | `ff8d40bb_424242_01.png` | 424242 | `口塞足交捆绑精液_4star` | 0 |
| 2 | `2e07b79d_424243_01.png` | 424243 | `20260531_脚部脱鞋特写坐姿` | 1 |
| 2 | `7e03f329_424243_01.png` | 424243 | `20260531_脚部脱鞋特写坐姿` | 1 |

## 结论

通过。随机 Action 已按 Group 共享：组内 Action ref、draw index 和 seed 一致；下一组重新抽取并使用新的 seed。四个 NovelAI 任务均成功生成。
