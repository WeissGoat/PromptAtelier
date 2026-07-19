# Blackboard Action Group Rounds 业务验收

## 1. 验收目标

验证 `examples/batches/blackboard_action_new_manga_monochrome.yaml` 可以作为旧 `blackboard.py:run_tags_machine` 的批量调度替代：

- `action_new` 保留 `pn_*` 文件夹边界。
- 每轮一个角色、一个动作组、最多三个动作。
- 组内随机抽样后恢复原目录顺序。
- `balanced_random` 使用 run directory 状态。
- preview 不污染状态，resume 不重复执行成功 task。
- 真实链路经过 ScriptComposer、PromptPolicyPipeline、NovelAI Renderer 和 NovelAI client。

验收日期：2026-07-12。

## 2. Mock 300 Task 全链路验收

命令：

```powershell
uv run python -m tags_machine_core run-batch `
  examples/batches/blackboard_action_new_manga_monochrome.yaml `
  --mock-client --fresh --log-level error --full
```

结果：

| 项目 | 结果 |
| --- | --- |
| run id | `d77eec12` |
| task | 300 |
| succeeded | 300 |
| failed | 0 |
| round | 100 |
| 每轮 task | 3 |
| character | 12 |
| 解析出的非空 `pn_*` group | 81 |
| 本批实际使用 group | 60 |
| group selected count | 最小 1，最大 2 |
| completed round | 100 |
| failed round | 0 |

每个 mock task 仍完整经过：

```text
BatchPlanner
-> NodeReader
-> ScriptComposer
-> PromptPolicyPipeline
-> NovelAI Renderer
-> Mock Executor
-> BatchArchive
-> GenerationResult / PNG 参数 / report
```

Mock client 只替换最终 HTTP 生图调用。

### 2.1 前 12 个 Task 编排

| index | character | action group | action | round |
| ---: | --- | --- | --- | ---: |
| 0 | Homura | `pn_human_1boy2girls_body` | `02_core_20260601_多彩发FFM全裸` | 0 |
| 1 | Homura | `pn_human_1boy2girls_body` | `02_core_三P双飞深插_4star` | 0 |
| 2 | Homura | `pn_human_1boy2girls_body` | `02_core_萝莉3P床摄入后入` | 0 |
| 3 | Madoka | `pn_human_multi_boys1girl_foot` | `02_core_20260503_桌上睡奸足交_3star` | 1 |
| 4 | Madoka | `pn_human_multi_boys1girl_foot` | `02_core_20260523_MMF足交口交_4star` | 1 |
| 5 | Madoka | `pn_human_multi_boys1girl_foot` | `02_core_被缚白背景舔脚_20260514` | 1 |
| 6 | Fate | `pn_human_1boy1girl_sex_missionary_lying_bondage_clothed` | `02_core_20260504_传教士强制按压强奸_5star` | 2 |
| 7 | Fate | 同上 | `02_core_校园强奸NTR_5star` | 2 |
| 8 | Fate | 同上 | `03_cum_20260508_制服萝莉内裤拨开肏_2star` | 2 |
| 9 | Nanoha | `pn_human_1boy1girl_foot_footjob` | `02_core_20260505_双足足交_1star` | 3 |
| 10 | Nanoha | 同上 | `02_core_20260506_脚交牵绳坐椅` | 3 |
| 11 | Nanoha | 同上 | `03_cum_20260505_背后足交射精_3star` | 3 |

结论：同一角色连续执行一个动作组的三个动作，完成后切换下一个角色。

## 3. Preview 状态只读验收

状态文件：

```text
examples/batches/blackboard-action-new-manga-monochrome/state/action_groups.json
```

执行 `plan-batch` 前后 SHA256：

```text
6B361B1D83E7C800DD1C159E014E37D9E390E2DBFC74AC4445FC59C71BD76B63
```

结果：前后完全一致，`plan-batch` 没有写入动作组状态。

## 4. Fresh 与 Resume 验收

使用独立工作目录执行一个 mock task，再执行 resume：

```text
examples/batches/.tmp/fresh-check-2/blackboard-action-new-manga-monochrome
```

结果：

- `--fresh` 后保留新的 `batch_source.json` 和 `batch.yaml`。
- resume 使用相同 `run_id` 重建相同 task id。
- 已成功 task 状态为 `skipped`，没有再次调用 executor。
- resume 前后 `state/action_groups.json` SHA256 相同。
- selected count 没有重复增加。
- `resume-batch --mock-client` 可以显式保持 mock 执行模式。

该验收同时修复了两个旧问题：

- Runner 在 CLI 归档 batch source 后再次删除 run directory。
- 未配置 seed 时，resume 重规划得到不同动作组和 task id。

## 5. NovelAI 真实出图验收

命令：

```powershell
uv run python -m tags_machine_core run-batch `
  examples/batches/blackboard_action_new_manga_monochrome.yaml `
  --fresh --limit 6 `
  --work-root .tmp/real-final `
  --output-dir .tmp/real-final-output `
  --log-level error --full
```

run id：`3c14b4a0`。

### 5.1 任务结果

| round | character | action group | task | 结果 |
| ---: | --- | --- | ---: | --- |
| 0 | Homura，自动补充 Madoka | `pn_human_1boy2girls_mouth_kiss_lying_misc_02` | 0 | NovelAI 持续 429，三次 batch attempt 后失败 |
| 0 | Homura，自动补充 Madoka | 同上 | 1 | succeeded，3 images |
| 0 | Homura，自动补充 Madoka | 同上 | 2 | succeeded，3 images |
| 1 | Madoka | `pn_human_1boy1girl_crotch_ass_focus_all_fours_misc` | 3 | succeeded，3 images |
| 1 | Madoka | 同上 | 4 | succeeded，3 images |
| 1 | Madoka | 同上 | 5 | succeeded，3 images |

成功生成 15 张真实图片。失败 task 在等待一分钟并多次 resume 后仍持续返回 NovelAI 429；其他成功 task 均被稳定识别为 `skipped`，没有重复出图。

### 5.2 参数抽查

五个成功 task：

- model：`nai-diffusion-4-5-full`。
- resolution：`1216x832`、`832x1216`、`1024x1024` 三种标准尺寸。
- 每 task：3 images。
- artist：`104994507_01_flat_color_artist_stack_vibe_86b3d31d_619_cfg07_strength04_v45_latest_stable`。
- 每张图有独立 seed，参数已归档到 `render_request.json`、`generation_result.json` 和 `png_params.json`。

代表图片：

```text
F:/my_project/new/tags_machine/refactor/examples/batches/.tmp/real-final-output/3c14b4a0_1_0_1_199c4e5c/bdb7d1fb_790087301_01.png
F:/my_project/new/tags_machine/refactor/examples/batches/.tmp/real-final-output/3c14b4a0_3_1_0_8ecd66e5/0ee1626a_2107689039_01.png
```

### 5.3 视觉检查

- Round 0 正确出现 Homura 和 Madoka，角色身份清晰，多角色关系与动作组主题一致。
- Round 1 正确切换到 Madoka，局部镜头、姿势和服装提示生效。
- 两个 round 均保持配置 artist 的 flat-color、清晰线稿和简单背景风格。
- 没有观察到角色名称丢失、完全重复图片或错误切换角色的情况。

## 6. 最终结论

通过：

- 动作 collection 的目录边界解析。
- 三动作 round 编排。
- 角色轮换。
- `balanced_random` 状态管理。
- preview 状态只读。
- fresh 元数据归档。
- resume task 身份和状态幂等。
- ScriptComposer、Policy、Renderer、NovelAI 生图及归档链路。
- 真实图片视觉和参数抽查。

未完全通过：

- 六个真实 task 中有一个持续受到 NovelAI 429 限流，最终结果为 5 succeeded / 1 failed。
- 该失败已经正确归档并可继续 resume，不属于动作组规划、Composer 或 Renderer 错误。
