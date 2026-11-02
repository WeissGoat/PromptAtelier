# Agent 拼接契约（Compose Contract）设计草案 v1

> 状态：草案，待确认「待定问题」一节后进入实现计划。
> 目标：在 Web 现有「脚本式拼接（Custom）」之外，增加「Agent 式拼接」：
> 用户在 Web 选素材节点 + 写定制要求 → Agent 按 Skill 产出格式化的**契约** → Web 加载、可视化、生图。

---

## 1. 现状与可复用资产

| 已有能力 | 位置 | 在本方案里的用途 |
|---|---|---|
| AgentComposer：`composer: agent` + `agent_result` → PromptBundle，画风由 renderer 叠加 | `composers/agent.py`、`services/json_api.py` | **生图通道直接复用**：契约里每帧的 positive/negative 作为 `agent_result` 提交，artist 仍由脚本控制 |
| AlbumPlan v1（phase/scene/frame + `action_source` + prompt） | `batch/album_plan.py`、`动作改2/st_rp_*/AlbumPlan.yaml` | 契约的前身。契约 = AlbumPlan + 片段级来源 + 格式 profile + 校验 + 修订链。提供 AlbumPlan → 契约导入 |
| 动作知识库 Catalog（`kb facets/search/show/collections`，基于 `classify.yaml`） | `knowledge_base/`、`动作改2/tools/knowledge_base` | Agent 新增场景时检索参考动作 |
| 动作库 Skill：`action-album-planner`、`action-kb-search`、`novelai-v4-5-syntax`、`auto-tuning-protocol` | `动作改2/.agents/skills/` | 新 Skill 引用它们，不重复写检索与语法规则 |
| 逐动作角色适配记录 `run-prompt-prompt.md`（`selected_keys`：按动作决定带哪些角色分区） | `action-new/<动作>/` | 角色适配规则的现成样本，沉淀为 Skill 规则 + 脚本 |
| 角色分区（hair/eyes/upper_clothes/legwear…）、`character_scope`、服装状态 `clothing.state` | 节点 `meta.yaml`、`nodes/character_scope.py`、`nodes/clothing_overlay.py` | 片段来源标注的「section」粒度；角色适配的判定依据 |
| 动作组：`st_*`（历史分组，按数字前缀有序）、`stn_*`（分类视图生成的连续故事组，源自 `new/`） | `TagsHub/动作改2` | 契约的主输入「动作组」 |
| Web：节点选择（NodeRoleGroup）、出图参数（RenderParamsPanel）、后台任务（GenerationTasksPanel）、tag diff | `web/src` | 新页面直接组合这些组件 |

**设计原则（沿用 core 现有约定）**：core 不绑定 LLM SDK，只产出任务、接收结果；Agent 是外部执行者。

---

## 2. 总体流程

```text
 Web: 选节点(角色/动作组/服装/背景) + 定制要求
   │
   ├─ 命中历史契约？ ──是──> 直接加载契约 → 可视化 → 生图
   │
   └─ 新建 ComposeRequest（request.yaml，状态 pending）
          │
          ▼
   Agent 执行器（manual / claude-cli / api，见 §7）
          │  调用 Skill: compose-contract-author
          │  ├─ contract context   读取节点、动作组成员、角色分区
          │  ├─ contract scaffold  按动作组生成骨架（每帧预填动作原词）
          │  ├─ （编辑：适配角色、改背景/服装、新增场景，kb search/show 查参考）
          │  ├─ contract annotate  脚本计算片段来源 + diff
          │  └─ contract validate  按目标格式 profile 校验，失败则修
          ▼
   contract.yaml（状态 validated）
          │
          ▼
 Web: 契约可视化（来源着色 / diff / 校验结果）→ 选帧 + 画风 + 参数 → 生图
          │   每帧 = compose request { composer: agent, agent_result, artist 节点 }
          ▼
   现有 generate / job_manager / 出图历史（结果回挂 contract_id + frame_id）
```

---

## 3. 三类文件

### 3.1 ComposeRequest（Web → Agent）

```yaml
schema: tags-machine.compose-request/v1
id: req_20261102_153012_ab12
created_at: 2026-11-02T15:30:12+08:00
status: pending            # pending | running | done | failed | cancelled
target_format: nai-v4.5    # 见 §5；决定权重语法、长度上限、是否允许中文
nodes:
  characters:
    - ref: danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女
      content_hash: sha256:...
  action_group:
    ref: stn_20260922_0028          # st_* / stn_*；也允许单个动作 ref
    content_hash: sha256:...        # 组内成员 hash 的聚合
    members_hash: sha256:...
  clothing:   { ref: 服装/xxx, content_hash: sha256:... }   # 可选
  background: { ref: 背景/simple_room, content_hash: sha256:... }  # 可选
requirements:
  text: |
    背景统一改为夜晚教室，保持服装连续；第 3 帧之后加一个窗边回头的过渡镜头。
  # 结构化开关（Web 表单），减少 Agent 误读
  background_override: night classroom
  clothing_policy: keep_character      # keep_character | follow_action | override
  keep_order: true
  allow_new_frames: true
  max_new_frames: 2
  exclude_members: []                   # 跳过动作组中的某些成员
  extra_negative: ""
agent:
  model: null                           # 执行器回填
  skill: compose-contract-author@1
parent_contract: null                   # 基于某个历史契约修改时填写
```

Agent 只读 request，不读 Web 状态；request 落盘后不可变（修改 = 新 request）。

### 3.2 Contract（Agent → Web，唯一事实源）

```yaml
schema: tags-machine.compose-contract/v1
id: ct_homura_stn_0028
revision: 3
parent_revision: 2                # 修订链；手工微调也产生新 revision
status: validated                 # draft | validated | invalid | archived
created_at: ...
request_id: req_20261102_153012_ab12
target_format: { id: nai-v4.5, version: 1 }
agent: { executor: claude-cli, model: ..., skill: compose-contract-author@1 }

nodes:                            # 生成时的节点快照指针（内容 hash 用于过期检测）
  characters:
    - key: c1
      ref: danbooru_mahou_shoujo_madoka_magica/...
      content_hash: sha256:...
  action_group: { ref: stn_20260922_0028, members_hash: sha256:... }
  background: null
  clothing: null

requirements_digest: "背景改夜晚教室；服装连续；新增 1 个过渡镜头"   # 便于列表展示

frames:
  - id: f01
    order: 1
    phase: start                  # 来自 classify.yaml，可被 Agent 调整
    title: 俯身吐舌
    source:
      type: action                # action | custom | derived
      ref: new/20260922_0028_01_俯身吐舌露乳牛仔短裤
      collection_ref: stn_20260922_0028
      collection_order: 1
      content_hash: sha256:...
    character_scope: default
    character_refs: [c1]
    segments:                     # 有序；最终 prompt 由 segments 渲染，不手写第二份
      - text: akemi_homura
        origin: character         # character | action | clothing | background | added | modified
        origin_ref: c1
        section: character        # 角色分区 / 动作 section
      - text: leaning forward
        origin: action
      - text: "1.2::night classroom::"
        origin: added
        reason: 需求：背景改夜晚教室
      - text: bent over
        origin: modified
        from: "{bent over}"
        reason: 统一为 v4.5 数值权重
    removed:                      # 从来源里删掉的词，diff 用
      - text: white background
        origin: action
        reason: 与背景覆盖冲突
      - text: purple_capelet
        origin: character
        section: upper_clothes
        reason: 动作为 breasts out，上衣外层不带
    negative_segments:
      - { text: red_glasses, origin: character, origin_ref: c1 }
    character_prompts: []         # 多角色且 profile 支持时：每个角色一组 segments（NAI v4+ char_captions）
    rendered:                     # annotate 生成，只读；Web 直接展示/提交
      positive: "akemi_homura, leaning forward, 1.2::night classroom::, ..."
      negative: "red_glasses"
    validation:
      status: pass                # pass | warn | fail
      issues: []
    notes: 保留俯身构图；按动作裸露状态去掉外层上衣。

  - id: f03b
    order: 4
    source:
      type: custom                # Web 显示「自定义」
      inspired_by: [new/2025-...窗边回头]   # 可选：kb 检索到的参考动作
    ...

validation_summary: { pass: 9, warn: 1, fail: 0, profile: nai-v4.5 }
```

要点：

- **segments 是唯一真相**，`rendered` 由脚本渲染。避免「来源标注」和「最终 prompt」两份对不上。
- `origin` 六类决定 Web 底色；`modified` 带 `from`，`removed` 单列，三者合起来即可生成 diff。
- `source.type`：`action`（来自动作组成员）、`custom`（Agent 新增）、`derived`（基于某成员大改，保留 ref 但标记为派生）。
- 不含 artist、quality 前缀、尺寸、种子等生图参数（这些仍由 Web/脚本控制）。

### 3.3 契约索引（缓存，可重建）

`cache/contract_index.json`：每个契约一行 `{id, revision, status, node_refs[], action_group, target_format, created_at, frame_count, stale}`。Web 用它做「按节点筛选历史契约」。由 `contract index` 扫描重建，契约文件才是事实源。

---

## 4. 片段来源标注（重点：别让 Agent 自己报来源）

让 Agent 手工给每个词标来源，成本高且容易错。建议**脚本推断 + Agent 只补理由**：

1. `contract scaffold`：按动作组生成骨架，每帧 `segments` 预填动作原词（origin=action），按 `selected_keys` 规则预填角色分区（origin=character, section=…）。
2. Agent 只做编辑（删 / 改 / 加），可直接写最终 tag 列表。
3. `contract annotate`：把 Agent 写的最终 tag 列表与来源节点做归一化匹配（去权重、下划线/空格、大小写，复用 `policies/rules/tag_normalize.py`）：
   - 命中角色节点某分区 → `character` + section
   - 命中动作原词 → `action`
   - 命中服装/背景节点 → `clothing` / `background`
   - 与来源同词不同权重/写法 → `modified`（记 `from`）
   - 都不命中 → `added`（缺 `reason` 时校验给 warn，提示 Agent 补理由）
   - 来源中有而结果中没有 → 写入 `removed`
4. Agent 回填 `reason`，再跑 `validate`。

这样「来源」由脚本保证，Agent 的自由度只在内容本身。

---

## 5. 目标格式 Profile + 可扩展校验器

`configs/prompt_formats/<id>.yaml`，契约记录 `target_format.id + version`：

```yaml
id: nai-v4.5
version: 1
family: novelai
models: [nai-diffusion-4-5-full, nai-diffusion-4-5-curated]
separator: ", "
tag_style: { underscore: allow, case: lower }
weight:
  syntaxes: [brace, numeric]       # brace: {tag}/[tag]；numeric: 1.2::tag::
  preferred: numeric
  range: [0.0, 3.0]
language: { allow_cjk: false }      # 是否允许中文
length:
  tokenizer: t5                     # clip | t5 | approx
  max_tokens: 512                   # 以官方/实测为准，可在 profile 调整
multi_character: { supported: true, max: 6, mode: char_captions }
forbid:
  artist_tags: true                 # artist 由脚本叠加，契约里禁止出现
  quality_tags: renderer            # renderer 已加质量词时禁止重复
validators:
  - weight_syntax
  - bracket_balance
  - token_length
  - language
  - forbidden_tags
  - duplicate_tags
  - tag_conflict
  - character_count
  - scope_consistency
```

内置 profile 起步：`nai-v3`、`nai-v4`、`nai-v4.5`、`nai-v5`、`sdxl-danbooru`（`(tag:1.2)` 语法、CLIP 75 token 分块、空格风格）、`natural-language`（允许中文/句子，给 Flux/Qwen 类 ComfyUI 工作流预留）。各模型的 token 上限、权重范围写在 profile 里，实现前按官方文档和实测核对，不写死在代码里。

**校验器接口**（Python，注册表 + entry point，可放在项目内或插件包）：

```python
class ContractValidator(Protocol):
    id: str
    def validate(self, frame: ContractFrame, profile: FormatProfile, ctx: ValidationContext) -> list[Issue]: ...
# Issue: { validator, severity: error|warn|info, segment_index?, message, fix_hint? }
```

| 校验器 | 说明 |
|---|---|
| `weight_syntax` | 只允许 profile 声明的语法（例如 v4.5 禁止 SD 的 `(tag:1.2)`） |
| `bracket_balance` | `{}` `[]` `()` `::` 配平 |
| `token_length` | 按 profile tokenizer 计数，多角色时 base + 各角色分别计数 |
| `language` | 不允许中文时检出 CJK 片段 |
| `forbidden_tags` | artist 名、质量词、尺寸词等由脚本负责的内容 |
| `duplicate_tags` / `tag_conflict` | 复用 `policies/rules/dedupe.py`、`tag_conflict.py` |
| `character_count` | `1girl/2girls/1boy` 等与 `character_refs`、动作 `cast` 一致 |
| `scope_consistency` | `character_scope=foot_detail` 等局部镜头不带脸部/发型分区（复用 `character_section_filter`） |

**格式转换**（P2）：`contract convert --to sdxl-danbooru` 按 profile 换权重语法和分隔符，生成新 revision，复用来源标注。

---

## 6. Agent Skill：`compose-contract-author`

放在 `.agents/skills/compose-contract-author/`（与 `.claude/skills` 同步，沿用项目现有做法）。

### 6.1 工具脚本（`tags_machine_core contract …`，全部输出 JSON，便于 Agent 读取）

| 命令 | 作用 |
|---|---|
| `contract request show <req>` | 读取请求，列出节点、要求、目标格式 |
| `contract context <req>` | 一次性给出 Agent 需要的上下文：角色分区（按 section）、动作组成员（顺序、classify、`tags.action`、`clothing.state`、`character_scope`）、服装/背景节点，以及目标 profile 摘要；输出精简版，控制 token |
| `contract scaffold <req>` | 生成骨架 contract（每帧预填 segments），状态 draft |
| `contract set-frame <ct> <frame> --tags-file …` | 写入某帧最终 tag 列表（Agent 不必手改大 YAML） |
| `contract add-frame <ct> --after f03 --inspired-by <ref>` | 新增自定义帧 |
| `contract annotate <ct>` | §4 来源推断 + diff + 渲染 `rendered` |
| `contract validate <ct>` | 跑 profile 校验器，输出 issues |
| `contract finalize <ct>` | 校验通过后置为 validated，写索引，更新 request 状态 |
| `kb facets/search/show/collections` | 已有，新增场景时检索参考 |

### 6.2 Skill 工作流

1. `request show` → `context`；理解要求，拆成「全局改动」（背景、服装策略）与「逐帧改动」。
2. `scaffold`。
3. 逐帧适配：
   - 角色：按动作的裸露 / 服装状态 / `character_scope` 决定带哪些分区（沉淀 `run-prompt-prompt.md` 的 `selected_keys` 判定规则）；保留身份词（character / copyright）。
   - 动作：保留姿势、构图、表情等核心词；删除与覆盖要求冲突的环境词。
   - 要求：背景 / 服装覆盖、连续性（同一 scene 内服装和环境一致）。
4. 新增场景（仅当 `allow_new_frames`）：用 `kb search` 按 `classify` 维度检索参考动作，`show` 读内容，写成 `custom` 帧并记 `inspired_by`。
5. `annotate` → 补 `added` / `removed` 的 reason → `validate`；有 error 必须修，warn 写进 notes。
6. `finalize`。
7. 禁止：写 artist / 画师名、质量前缀、生图参数；修改素材库源节点；跳过 validate。

权重语法规则直接引用 `novelai-v4-5-syntax` 等 Skill，不重复写。

---

## 7. Agent 执行器（谁来跑 Agent）

| 模式 | 方式 | 适用 |
|---|---|---|
| `manual`（P0 默认） | Web 写 `request.yaml`，显示「等待 Agent」；用户在 Claude Code（本机或云端）执行 `/compose-contract` 处理待办请求；Web 轮询到 contract 后刷新 | 零耦合，先跑通契约与 UI |
| `claude-cli`（P1） | 后端 job_manager 启动 headless `claude -p`，带 Skill 与工作目录，日志转成任务进度 | 一键全自动 |
| `api`（可选） | 走 Agent SDK / API | 云端服务器无 CLI 时 |

在配置中通过 `contract.runner` 切换；三种模式产物一致，都是 contract 文件。

---

## 8. Web：Agent Studio

新页面（与 Custom / Compare / History 并列），三栏：

**左栏：请求与历史**
- 节点选择：角色（可多选）、动作组（只列 `st_*` / `stn_*` 集合，显示成员数与首图）、服装、背景。复用 NodeRoleGroup 和选择器。
- 历史契约列表：按当前所选节点筛选，标注匹配程度（完全匹配 / 部分匹配），显示状态、格式、帧数、要求摘要，以及「来源已更新」（hash 变化）。
- 定制要求：自由文本 + 结构化开关（背景覆盖、服装策略、保持顺序、允许新增 N 帧、排除成员、目标格式）。
- 按钮：「新建契约」/「基于此契约修改」（带 `parent_contract`）。

**中栏：契约查看**
- 头部：状态、格式 profile、校验汇总、revision 切换（可对比两个 revision）。
- 帧列表（时间线 / 卡片）：来源动作名与缩略图（自定义帧显示「自定义」+ 参考来源）、phase、scope。
- 每帧三种视图：
  - **最终**：tag chip 按来源着色。参考配色：角色 = 蓝、动作 = 中性灰、服装 = 紫、背景 = 青、新增 = 琥珀、修改 = 橙色描边；鼠标悬停显示 section、origin_ref、reason。
  - **Diff**：相对来源动作原词，`removed` 删除线、`added` 高亮、`modified` 显示 from → to（复用 `compare/tagDiff.ts`）。
  - **原文**：`rendered.positive/negative` 文本，可复制。
- 校验问题标在对应 chip 上。
- 手工微调：编辑 chip → 保存为新 revision（origin 记为 `manual`）。

**右栏：生图**
- 画风（artist，由脚本叠加，不进契约）、出图参数（复用 RenderParamsPanel、ComfyTargetPanel）。
- 选帧（全选 / 勾选），可选「每帧 × 画风对比」。
- 提交：每帧构造 compose request `{composer: "agent", agent_result: {positive, negative, character_scope}, character 节点, artist 节点}` + `contract: {id, revision, frame_id}`，走现有后台批量任务。
- 结果按帧回挂，历史页可按契约查看。

---

## 9. 后端改动清单

- `contracts/`（新模块）：pydantic 模型（Request / Contract / Frame / Segment）、存储与索引、annotate、validators 注册表、profiles 加载。
- CLI：`contract …` 子命令（§6.1）。
- API：
  - `GET /contracts?node=…&status=…`
  - `GET /contracts/{id}?revision=`
  - `POST /contracts/requests`
  - `GET /contracts/requests/{id}`
  - `POST /contracts/{id}/revisions`（手工微调）
  - `POST /contracts/{id}/validate`
  - `GET /formats`
- 生图：compose request 增加 `contract` 追溯字段，写入 `PromptBundle.meta.extra.contract` 与结果索引；不改 AgentComposer 核心逻辑。
- 迁移：`contract import-album-plan`，把现有 `AlbumPlan.yaml` 导入为契约（来源可由 annotate 推断），作为历史。

---

## 10. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 契约 / 请求 schema、profiles（nai-v4.5、nai-v4、sdxl-danbooru）、核心校验器、`contract` CLI、Skill、manual 执行器；Web 只读查看器（着色 / diff）+ 按帧生图 | 用一个 `stn_` 组 + 一个角色，Agent 产出契约，Web 着色正确并能出图 |
| P1 | Web 请求表单、历史筛选、过期检测、手工微调 revision、claude-cli 执行器 | Web 一键提交，自动跑完 Agent 并刷新 |
| P2 | 格式转换、AlbumPlan 导入、更多校验器（tag 词典存在性）、出图后接 `auto-tuning-protocol` 的看图反馈回写契约 | — |

---

## 11. 待定问题

1. **契约存放位置**：
   - 放 TagsHub（例如 `TagsHub/契约/`，有版本、可跨机器共享，和现有 AlbumPlan 放在素材库的做法一致）；
   - 或放 PromptAtelier 的 `runtime/`（不入库）。
   - 倾向 TagsHub。
2. **与 AlbumPlan 的关系**：契约取代 AlbumPlan 作为正式格式（AlbumPlan 只做导入），还是两者并存？倾向取代，`action-album-planner` 后续改为产出契约。
3. **Agent 执行器**：P0 先用 manual（在 Claude Code 里跑 Skill）可以接受吗？还是一开始就要 Web 一键触发？
4. 需求里的 `nst_` 是否就是分类视图生成的 `stn_*`（来自 `new/` 的连续故事组）？
5. 一份契约是否只对应「一个动作组」？还是允许多个动作组拼成一个图集？倾向一个契约一个主动作组，新增帧可来自任意动作。
6. 多角色动作（1boy1girl、2girls）：男性角色是否也从角色库选？还是保持动作原词？
