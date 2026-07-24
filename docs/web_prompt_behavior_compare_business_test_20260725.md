# Prompt Behavior Compare 真实业务验收记录

## 1. 测试信息

- 日期：2026-07-25
- 前端：`http://127.0.0.1:53173/`
- 后端：`http://127.0.0.1:1456/api`
- 后端绑定 `8765` 在本机被 Windows 拒绝，因此本次使用 `1456`；前端通过启动脚本自动注入对应 API 地址。
- 编排入口：Web Custom -> Compare Generate
- 模型：`nai-diffusion-4-5-full`
- NT：`1`
- Seed：`424242`
- 图片尺寸：`1024 × 1024`

本记录不保存或展示 NovelAI token。

## 2. 输入节点

```text
Artist:
F:/my_project/new/tags_machine/design/画风/109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable

Character:
F:/my_project/new/tags_machine/design/角色/danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女

Action:
F:/my_project/new/tags_machine/design/动作改2/new/20260502_夜外强奸_5star
```

实际 Web 页面展开结果：

```text
Artist 1 × Character 1 × Action 1 × Behavior 2 × Groups 1 = 2
```

## 3. Behavior 方案

### 3.1 Default

```text
Character Prompts: Auto
Add male caption: true
Identity: inherit
Policy rules: inherit
```

### 3.2 No Character Prompts

```text
Character Prompts: Off
Identity: inherit
Policy rules: inherit
```

两套方案使用同一组节点、negative、尺寸、模型、采样器、steps、scale 和 seed。

## 4. 真实生成结果

重跑后两个任务均成功，属于同一 Compare group：

```text
outputs/compare_20260724162409_3b5af247/group_001_seed_424242/
```

| Behavior | 图片 | SHA256 | 尺寸 | Seed |
| --- | --- | --- | --- | --- |
| Default | `27a7fd6a_424242_01.png` | `C3603FDC55B8A93BA4E889DA74D6CB1FD73FC311F8863FA25115DF10483B61F7` | 1024×1024 | 424242 |
| No Character Prompts | `187c5668_424242_01.png` | `4793096F207CBF5D5E2005703D4ABCF1EA24C787065DA1FD9C4E2369E6B18960` | 1024×1024 | 424242 |

绝对路径：

```text
F:/my_project/new/tags_machine/refactor/outputs/compare_20260724162409_3b5af247/group_001_seed_424242/27a7fd6a_424242_01.png
F:/my_project/new/tags_machine/refactor/outputs/compare_20260724162409_3b5af247/group_001_seed_424242/187c5668_424242_01.png
```

## 5. PNG 参数验收

两张图片从实际 PNG 读取到的共同参数：

```text
model: nai-diffusion-4-5-full
sampler: k_euler_ancestral
steps: 23
scale: 5.0
seed: 424242
width: 1024
height: 1024
n_samples: 1
```

关键差异：

### Default / Auto

```text
v4_prompt.caption.char_captions: 2 条
  1. girl, 2.0::akemi_homura::, magical_girl
  2. boy,
v4_negative_prompt.caption.char_captions: 2 条
```

角色相关内容从 base prompt 中拆分到 Character Prompts，实际 PNG 中可以读取到角色 caption。

### No Character Prompts / Off

```text
v4_prompt.caption.char_captions: []
v4_negative_prompt.caption.char_captions: []
```

`2.0::akemi_homura::, magical_girl` 保留在 base prompt 中，没有角色 caption 拆分。

结论：两套 Behavior 没有被错误地复用同一份 render request，且实际 PNG 参数反映了预期差异。

## 6. 视觉验收

两张图片均保持了：

- 同一画风的高对比单色/青色表现。
- 同一角色与动作主题。
- 相同尺寸和 seed 条件。

由于 Character Prompts 的条件组织方式不同，两张图的镜头构图、角色姿态和局部细节明显不同。该差异是本次 Compare 的目标，不要求像素一致。

```text
visual_result: pass
parameter_result: pass
request_result: pass
```

## 7. 异常记录

第一次运行时 Default 任务受到 NovelAI `429` 限流，按当前配置完成 3 次重试后失败；Off 任务随后成功。等待冷却后重跑同一矩阵，两个任务均成功。该异常属于外部服务限流，未改变 Compare 矩阵或 seed 规则。

## 8. 验收结论

Prompt Behavior 完整方案 Compare 已通过真实业务验收：

1. 方案可以在 Web 中创建、编辑和选择。
2. Compare 数量和执行任务数量一致。
3. 同组 seed 一致。
4. Auto/Off 的 Character Prompts 实际写入 PNG 的方式不同。
5. 两张真实图片和参数均可读取并能按 Behavior 区分。

