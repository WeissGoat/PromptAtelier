# Web 随机节点业务验收

## 验收环境

- 日期：2026-07-26
- Frontend：`http://127.0.0.1:53173/`
- Backend：`http://127.0.0.1:1456/api`
- 生图后端：NovelAI
- Artist：`109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable`
- Character：`danbooru_akemi_homura_暁美ほむら _魔法少女`
- Seed：`424242`
- 分辨率：`1024x1024`

## 候选池验收

### Folder

配置：

```text
role: action
source: folder
value: 动作改2/new
```

结果：

```text
原始候选：1719
首屏加载：30
滚动分页：通过
搜索：通过
```

### classify.yaml 二次过滤

配置：

```text
domain: foot
subtype: sole_focus
```

结果：

```text
原始候选：1719
过滤后：40
未标注：0
条件不匹配：1679
无效：0
```

未启用分类过滤时，全部 1719 个 Folder 候选正常进入候选池，不要求存在 `classify.yaml`。

### Glob

配置：

```text
动作改2/new/*足部*
```

结果：15 个候选，接口分页返回正常。

### Collection

`web.project_requires` 成功加载项目 Collection。`action_new` 修复 include 语义后：

```text
候选：2238
首次扫描：约 5281 ms
五分钟进程缓存命中：约 74 ms
```

扫描只展开匹配 `pn_*` 的目录，不再错误递归所有未匹配目录。

## Preview 验收

使用 Folder + classify 随机 Action 点击 Preview：

```text
status: Preview ready: Default
```

Preview 成功解析随机 Action，并通过现有 ScriptComposer、PromptPolicyPipeline 和 NovelAI Renderer 生成最终 prompt。Preview 样例没有写回节点槽位，也没有消耗后续 Generate 的抽取序列。

## Primary 真实出图

图片：

```text
F:/my_project/new/tags_machine/refactor/outputs/random_20260725171500_62332e38/group_001_seed_424242/15597e8d_424242_01.png
```

结果：

```text
n_samples: 1
seed: 424242
model: nai-diffusion-4-5-full
random action: 20260526_standing_leglock
status: Random Primary complete · 1
```

实际 PNG 的 `tags_machine_core.random_nodes` 包含：

- `slot_id`
- `role`
- Folder 来源配置
- `domain=foot`、`subtype=sole_focus` 过滤配置
- 最终候选 ref/name/relative
- `draw_index`
- `deck_cycle`
- 原始与过滤后候选统计

## Compare 真实出图

矩阵：

```text
Artist 1 × Character 1 × Action 1 × Behavior 2 × NT 1 = 2
```

图片：

```text
F:/my_project/new/tags_machine/refactor/outputs/compare_20260725171941_763dac26/group_001_seed_424242/2aa079f4_424242_01.png
F:/my_project/new/tags_machine/refactor/outputs/compare_20260725171941_763dac26/group_001_seed_424242/c07858a2_424242_01.png
```

实际抽取：

```text
Default:
  seed: 424242
  action: 20260531_足部特写俯卧

No Character Prompts:
  seed: 424242
  action: 20260505_双女3P纸巾肛塞_3star
```

结论：

- 同一 Compare group 使用相同 seed。
- 两个实际任务分别抽取 Action。
- 单次 Generate 内没有重复 Action。
- 候选数量没有放大 Compare Matrix。
- 两张实际 PNG 均包含各自的 `random_nodes`。
- Default 使用 Character Prompts Auto；No Character Prompts 的 PNG 中没有 Character Prompts metadata，说明 Behavior Compare 仍正常生效。

## 自动化验证

后端：

```text
94 tests passed
```

覆盖 Node Pool、Web API、生成 metadata、Web App、Nodes 和 Batch 回归。

前端：

```text
18 test files passed
87 tests passed
npm run build passed
```

覆盖工作区持久化、随机抽取解析、Compare Matrix、Compare Controller、Custom Studio 和既有节点编辑功能。

## AgentComposer 边界

以下文件在随机节点实现提交范围内无 diff：

```text
src/tags_machine_core/composers/agent.py
src/tags_machine_core/composers/agent_cache.py
src/tags_machine_core/composers/agent_hash.py
```

随机节点在 Composer 前解析为普通 `NodeDocument`。AgentComposer 不接收 `NodePoolSpec`，Hash 不包含 Folder、Collection、Glob、过滤条件或 scan id。

## 验收结论

通过。

- Folder / Collection / Glob 已接入 Web 随机节点。
- Action `classify.yaml` 二次过滤已接入。
- 浏览器工作区持久化已生效，候选扫描结果不持久化。
- Primary、Compare、NT 的随机任务规划链路已打通。
- NovelAI 真实出图成功。
- 实际 PNG 可追溯最终随机节点。
- AgentComposer 稳定链路未修改。
