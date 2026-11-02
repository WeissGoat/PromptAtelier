# Agent 拼接契约（Compose Contract）设计草案 v1

> 状态：草案 r3（已按两轮反馈修订）。
> 目标：在 Web 现有「脚本式拼接（Custom）」之外，增加「Agent 式拼接」：
> 用户在 Web 选素材节点 + 写定制要求 → Agent 按 Skill 自主组合，产出格式化的**契约** → Web 加载、可视化、生图。

## 0. 已确认的决策

| 问题 | 结论 |
|---|---|
| 契约存放 | `TagsHub/动作改2/contracts/`（随动作库仓库版本化）；路径可在配置中修改 |
| 与 AlbumPlan 的关系 | 完全无关，独立设计 |
| 角色适配 | 不耦合 `selected_keys` 或任何预设分区规则，由 Agent 根据动作和要求自己判断怎么拼 |
| **来源** | **帧级**：每组提示词来自动作组中的哪个动作 node，或是 Agent 自定义 |
| 提示词标记 | 每个片段标记为角色 / 动作 / 新增等，由 Agent 书写时分块声明，用于着色 |
| 第一期执行方式 | Web 生成「要求 prompt」，用户复制给任意外部 agent 处理；产物回到 Web（落盘或粘贴导入） |
| 动作组 | `st_*` 与 `stn_*`（分类视图生成的连续故事组） |
| 契约粒度 | 一份契约对应一个动作组；新增帧可以参考任意动作 |
| 多角色 | 选了多个角色且定制要求中有说明时，Agent 可以把角色分配到动作中的不同人物；否则保留动作原词 |

---

## 1. 可复用的现有能力

| 已有能力 | 位置 | 用途 |
|---|---|---|
| AgentComposer：`composer: agent` + `agent_result` → PromptBundle，画风由 renderer 叠加 | `composers/agent.py`、`services/json_api.py` | **生图通道直接复用**：契约每帧的 positive/negative 作为 `agent_result` 提交，artist 仍由脚本控制 |
| 动作知识库 Catalog（`kb facets/search/show/collections`，基于 `classify.yaml`） | `knowledge_base/`、`动作改2/tools/knowledge_base` | Agent 新增场景时检索参考动作 |
| 动作库 Skill：`action-kb-search`、`novelai-v4-5-syntax` | `动作改2/.agents/skills/` | 检索流程与权重语法直接引用 |
| 节点信息：角色分区、`character_scope`、`clothing.state`、`classify.yaml` | 节点 `meta.yaml` / `classify.yaml` | 作为 Agent 判断的**信息**，不作为硬规则 |
| tag 归一化、去重、冲突规则 | `policies/rules/` | diff 与校验器复用 |
| Web 组件：NodeRoleGroup、RenderParamsPanel、ComfyTargetPanel、GenerationTasksPanel、`compare/tagDiff.ts` | `web/src` | 新页面直接组合 |

core 的原则不变：不绑定 LLM SDK，只产出任务、接收结果。

---

## 2. 总体流程

```text
 Web: 选节点(角色/动作组/服装/背景) + 定制要求
   │
   ├─ 命中历史契约？ ──是──> 加载契约 → 可视化 → 生图
   │
   └─ 新建 ComposeRequest（动作改2/contracts/requests/<id>/）
          │
          ▼
   生成「要求 prompt」（工具版 / 自包含版，见 §6）
          │  用户复制给外部 agent
          ▼
   外部 agent 产出契约
     ├─ 有仓库和工具：用 contract CLI 直接写入 contracts/
     └─ 纯对话：输出契约 YAML → 用户粘贴到 Web「导入」
          │
          ▼
   脚本 render（拼出最终文本 + 计算 diff）+ validate（按目标格式校验）
          │
          ▼
 Web: 逐帧展示来源、标记着色、diff、校验结果 → 选帧 + 画风 + 参数 → 生图
          │   每帧 = compose request { composer: agent, agent_result, artist 节点 }
          ▼
   现有 generate / job_manager / 出图历史（结果回挂 contract_id + frame_id）
```

---

## 3. 存储布局（`动作改2/contracts/`）

```text
TagsHub/动作改2/contracts/            # config: contract.root
  requests/
    req_20261102_153012_ab12/
      request.yaml                    # Web 提交的请求，不可变
      snapshot.json                   # 请求时的来源快照（角色、动作组各成员的 tags、服装、背景）
      prompt_tools.md                 # 给有工具的 agent 的要求 prompt
      prompt_standalone.md            # 给纯对话 agent 的自包含要求 prompt
  ct_homura_stn_0028/
    rev_001.yaml                      # 契约修订，不可变；任何改动生成新 rev
    rev_002.yaml
PromptAtelier/cache/contract_index.json   # 可重建索引：按节点筛选、列表展示
```

- 契约随动作库仓库（`tags_machine_node_story`）提交与同步。
- `snapshot.json` 保证素材库以后改了，旧契约的 diff 仍然可复现；各节点 `content_hash` 用来提示「来源已更新」。
- 不影响现有工具：KB 只扫描 `new/` 与 `st_*`，分类视图只管理 `pn_*` / `stn_*`，`contracts/` 都不会被触及。

---

## 4. 文件格式

### 4.1 ComposeRequest（Web → Agent）

```yaml
schema: tags-machine.compose-request/v1
id: req_20261102_153012_ab12
created_at: 2026-11-02T15:30:12+08:00
target_format: nai-v4.5               # 见 §5
nodes:
  characters:                         # 可多个，c1/c2 为契约内的简称
    - key: c1
      ref: danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女
      content_hash: sha256:...
  action_group:
    ref: stn_20260922_0028            # st_* / stn_*
    members:                          # 按组内顺序
      - { order: 1, ref: new/20260922_0028_01_俯身吐舌露乳牛仔短裤, content_hash: sha256:... }
      - { order: 2, ref: new/..., content_hash: sha256:... }
  clothing:   { ref: 服装/xxx, content_hash: sha256:... }       # 可选
  background: { ref: 背景/simple_room, content_hash: sha256:... }  # 可选
requirements:
  text: |
    背景统一改为夜晚教室，保持服装连续；第 3 帧之后加一个窗边回头的过渡镜头。
    动作里的男性由 c2 扮演。
  # 结构化开关（Web 表单），减少 Agent 误读；都可选
  keep_order: true
  allow_new_frames: true
  max_new_frames: 2
  exclude_members: []
  extra_negative: ""
parent_contract: null                 # 基于历史契约修改时填 {id, revision}
```

### 4.2 Contract（Agent → Web，唯一事实源）

```yaml
schema: tags-machine.compose-contract/v1
id: ct_homura_stn_0028
revision: 2
parent_revision: 1
request_id: req_20261102_153012_ab12
target_format: { id: nai-v4.5, version: 1 }
author: { kind: agent, name: "<外部 agent / 模型>" }   # 手工微调时 kind: manual
summary: 背景改夜晚教室；服装连续；新增 1 个过渡镜头

frames:
  - id: f01
    title: 俯身吐舌
    source:                                   # 帧级来源
      type: action                            # action | custom
      ref: new/20260922_0028_01_俯身吐舌露乳牛仔短裤
      order: 1                                # 在动作组中的位置
    character_refs: [c1]
    positive:                                 # 有序片段，kind 由 Agent 声明
      - kind: character
        who: c1
        tags: [akemi_homura, mahou_shoujo_madoka_magica, black_hair, purple_eyes]
      - kind: action
        tags: [1girl, solo, tongue out, ";p", "1.2::leaning forward::", bent over, cowboy shot]
      - kind: added
        tags: [night, classroom, window]
        reason: 背景覆盖为夜晚教室
    negative:
      - kind: character
        who: c1
        tags: [red_glasses]
    notes: 动作为 breasts out，外层上衣不带。

  - id: f03b
    title: 窗边回头
    source:
      type: custom                            # Web 显示「自定义」
      inspired_by: [new/2025-..._窗边回头]    # 可选：参考过的动作
    character_refs: [c1]
    positive:
      - { kind: character, who: c1, tags: [akemi_homura, black_hair] }
      - { kind: added, tags: [looking back, standing, by window], reason: 过渡镜头 }
```

**片段 kind**

| kind | 含义 | 附加字段 |
|---|---|---|
| `character` | 角色提示词 | `who: c1` |
| `action` | 动作提示词（来自本帧来源动作，可调权重或改写） | — |
| `clothing` | 服装节点内容 | — |
| `background` | 背景节点内容 | — |
| `added` | Agent 新增 | `reason`（建议填写） |

- 片段有序，可以交错（例如角色 → 动作 → 新增 → 动作），最终文本按片段顺序拼接。
- 不含 artist、质量前缀、尺寸、种子等生图参数。
- 多角色且 profile 支持分角色提示词时（NAI v4+ `char_captions`），帧可增加 `characters: [{who: c1, positive: [...], negative: [...]}]`，结构与上面相同。

### 4.3 脚本生成的部分（`contract render` 写入，只读）

```yaml
    rendered:
      positive: "akemi_homura, mahou_shoujo_madoka_magica, ..., night, classroom, window"
      negative: "red_glasses"
    diff:                                     # 最终提示词 vs 来源动作 node 的正向词
      kept:     [1girl, solo, tongue out, ";p", bent over, cowboy shot]
      modified: [{ from: leaning forward, to: "1.2::leaning forward::" }]
      removed:  [white background, simple background, transparent background, ...]
      added:    [akemi_homura, ..., night, classroom, window]   # 不在来源动作里的词，带上其片段 kind
    validation: { status: pass, issues: [] }
```

- diff 按 tag 归一化（权重、下划线/空格、大小写、转义括号）后比较；只是同一个词换了写法或权重时记为 `modified`。
- `custom` 帧没有来源动作，diff 只显示全部新增；有 `inspired_by` 时可选择相对参考动作做 diff。
- 片段 kind 由 Agent 声明，脚本不推断。校验器只做轻量提示：`action` 片段里出现来源动作中没有的词时给 info（可能是新增，却写进了动作片段）。

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
language: { allow_cjk: false }
length:
  tokenizer: t5                     # clip | t5 | approx
  max_tokens: 512                   # 实现前按官方文档/实测核对
multi_character: { supported: true, max: 6, mode: char_captions }
forbid:
  artist_tags: true                 # artist 由脚本叠加
  quality_tags: renderer            # renderer 已加质量词时禁止重复
validators: [weight_syntax, bracket_balance, token_length, language,
             forbidden_tags, duplicate_tags, tag_conflict, character_count,
             source_exists, action_kind_hint]
```

起步内置：`nai-v3`、`nai-v4`、`nai-v4.5`、`nai-v5`、`sdxl-danbooru`（`(tag:1.2)` 语法、CLIP 75 token 分块）、`natural-language`（允许中文和句子）。各模型的 token 上限、权重范围都只写在 profile 里，不写死在代码中。

**校验器接口**（注册表 + entry point，项目内或插件包都能扩展）：

```python
class ContractValidator(Protocol):
    id: str
    def validate(self, frame: RenderedFrame, profile: FormatProfile, ctx: ValidationContext) -> list[Issue]: ...
# Issue: { validator, severity: error|warn|info, segment_index?, tag?, message, fix_hint? }
```

| 校验器 | 说明 |
|---|---|
| `weight_syntax` | 只允许 profile 声明的语法 |
| `bracket_balance` | `{}` `[]` `()` `::` 配平 |
| `token_length` | 按 profile tokenizer 计数；多角色时 base 与各角色分别计数 |
| `language` | 不允许中文时检出 CJK 片段 |
| `forbidden_tags` | 画师名、质量词等由脚本负责的内容 |
| `duplicate_tags` / `tag_conflict` | 复用现有 policies 规则 |
| `character_count` | `1girl/2girls/1boy` 等与 `character_refs` 及动作 `cast` 一致 |
| `source_exists` | `source.ref` 属于本动作组（`custom` 帧的 `inspired_by` 存在） |
| `action_kind_hint` | `action` 片段中出现来源动作没有的词（info） |

---

## 6. 「要求 prompt」与 Agent 执行

### 6.1 第一期：复制给外部 agent

Web 提交请求后生成两份 prompt，界面上提供「复制」按钮：

| 形式 | 内容 | 产物回传 |
|---|---|---|
| **工具版** `prompt_tools.md` | 请求 ID、任务、要使用的 Skill（`compose-contract-author`）、CLI 命令清单、完成标准 | agent 在仓库中运行 `contract …` 命令，直接写入 `contracts/`；Web 轮询到后刷新 |
| **自包含版** `prompt_standalone.md` | 精简后的快照内嵌（角色分区词表、动作组各成员的正向词 + classify 摘要 + `clothing.state` + `character_scope`）+ 契约格式说明 + 原则 + 目标格式要点 | agent 输出契约 YAML，用户在 Web「导入契约」中粘贴；Web 调用 render + validate，有问题时显示校验结果，可以再复制给 agent 修 |

### 6.2 后续：一键执行（P2）

`contract.runner: manual | claude-cli | api`。后端用 job_manager 启动 headless agent 执行同一份工具版 prompt，产物与第一期一致。

---

## 7. Skill：`compose-contract-author`

放在 `.agents/skills/compose-contract-author/`（同步到 `.claude/skills`）。

### 7.1 工具（`tags_machine_core contract …`，均输出 JSON）

| 命令 | 作用 |
|---|---|
| `contract request show <req>` | 请求内容、目标格式摘要 |
| `contract context <req> [--member N]` | 角色分区词表、动作组各成员内容、服装、背景；可只取单个成员，控制上下文长度 |
| `contract new <req>` | 创建空契约（只有帧列表和来源，**不预填 tag**，避免诱导 Agent 照搬） |
| `contract set-frame <ct> <frame> --file frame.yaml` | 写入一帧 |
| `contract add-frame <ct> --after f03 [--inspired-by <ref>]` | 新增自定义帧 |
| `contract render <ct>` | 拼出最终文本、计算 diff |
| `contract validate <ct>` | 跑 profile 校验器 |
| `contract finalize <ct>` | 通过校验后写入新 revision 并更新索引 |
| `contract import <file> --request <req>` | 导入纯对话 agent 的产物（Web「导入」也调用它） |
| `kb facets/search/show` | 已有，新增场景时检索 |

### 7.2 Skill 给 Agent 的指引（原则，不是硬规则）

- 理解要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 每帧自主判断角色要带哪些内容：身份词通常保留；服装、发型、配饰等结合动作的裸露状态、镜头范围、构图和要求来取舍。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词、混入的角色/画风词去掉。
- 按真实意图声明片段 kind：来自本帧动作的写 `action`，自己加的写 `added` 并给理由。
- 多角色：只有选了多个角色且要求中说明了分配方式时，才替换动作中的人物；否则保留动作原词。
- 连续性：同一组中的服装和场景保持一致，除非要求变化。
- 新增帧：用 `kb search` 找参考、`kb show` 读内容，`source.type: custom`，参考过的写进 `inspired_by`。
- `validate` 的 error 必须修。
- 禁止：写画师名、质量前缀、生图参数；修改素材库源节点。
- 权重语法遵循目标格式（NAI 4.5 参考 `novelai-v4-5-syntax`）。

---

## 8. Web：Agent Studio

新页面，与 Custom / Compare / History 并列，三栏：

**左栏：请求与历史**
- 节点选择：角色（可多选，显示 c1/c2）、动作组（只列 `st_*` / `stn_*`，显示成员数和首图）、服装、背景。
- 历史契约：按当前所选节点筛选，标注匹配程度（完全 / 部分），显示格式、帧数、摘要，以及「来源已更新」。
- 定制要求：自由文本 + 结构化开关 + 目标格式。
- 操作：「生成要求」（显示两份 prompt，可复制）、「导入契约」（粘贴 YAML）、「基于此契约修改」。
- 请求列表：待处理的请求，显示是否已有产物。

**中栏：契约查看**
- 头部：格式 profile、校验汇总、revision 切换与两版对比。
- 帧列表：每帧显示**来源**：动作 node 名、在组内的序号、缩略图；自定义帧显示「自定义」和参考动作。
- 每帧三种视图：
  - **标记**：tag chip 按片段 kind 着色。参考配色：角色 = 蓝（多角色按 c1/c2 区分色相）、动作 = 中性灰、服装 = 紫、背景 = 青、新增 = 琥珀；悬停显示 kind、who、reason。
  - **Diff**：最终提示词相对来源动作 node 的正向词。保留、修改（from → to）、删除（删除线）、新增（带 kind 颜色）。
  - **原文**：rendered 文本，可复制。
- 校验问题标在对应 chip 上。
- 手工微调：编辑 chip、改 kind、增删 → 保存为新 revision，`author.kind: manual`。

**右栏：生图**
- 画风（不进契约）、出图参数、ComfyUI 目标（复用现有组件）。
- 选帧（全选 / 勾选），可选「帧 × 画风」对比。
- 提交：每帧构造 `{composer: "agent", agent_result: {positive, negative, character_scope}, character 节点, artist 节点, contract: {id, revision, frame_id}}`，走现有后台批量任务。
- 结果按帧回挂；History 页可按契约筛选。

---

## 9. 后端改动清单

- 新模块 `contracts/`：pydantic 模型（Request / Contract / Frame / Segment / Rendered）、快照构建、render 与 diff、validators 注册表、profile 加载、存储与索引、两种要求 prompt 的模板渲染。
- CLI：`contract …` 子命令（§7.1）。
- API：
  - `GET /contracts?node=&format=`
  - `GET /contracts/{id}?revision=`
  - `POST /contracts/requests`
  - `GET /contracts/requests/{id}`（含两份 prompt）
  - `POST /contracts/import`
  - `POST /contracts/{id}/revisions`
  - `GET /formats`
- 生图：compose request 增加 `contract` 追溯字段，写入 `PromptBundle.meta.extra.contract` 与结果索引；AgentComposer 核心不改。
- 配置：`contract.root`（默认 `<design_root>/动作改2/contracts`）、`contract.runner`。

---

## 10. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | schema、快照、render/diff、核心校验器、profiles（nai-v4.5、nai-v4、sdxl-danbooru）、CLI、Skill、两份要求 prompt；Web 请求表单 + 复制 prompt + 导入 + 只读查看器（来源 / 标记 / diff）+ 按帧生图 | 一个 `stn_` 组 + 一个角色：外部 agent 产出契约，导入后来源、着色、diff 正确，校验通过并能出图 |
| P1 | 历史筛选、来源过期提示、手工微调 revision、revision 对比、多角色分角色提示词 | — |
| P2 | 一键执行（claude-cli / api）、格式转换（换 profile 重写权重语法）、更多校验器（tag 词典存在性） | — |
