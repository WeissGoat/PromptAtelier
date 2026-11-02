# Agent 拼接契约（Compose Contract）设计草案 v1

> 状态：草案 r2（已按第一轮反馈修订）。
> 目标：在 Web 现有「脚本式拼接（Custom）」之外，增加「Agent 式拼接」：
> 用户在 Web 选素材节点 + 写定制要求 → Agent 按 Skill 自主组合，产出格式化的**契约** → Web 加载、可视化、生图。

## 0. 已确认的决策

| 问题 | 结论 |
|---|---|
| 契约存放 | 放 PromptAtelier（默认 `contracts/`，可在配置中修改），不放 TagsHub |
| 与 AlbumPlan 的关系 | 完全无关，独立设计。不导入、不兼容 |
| 角色适配 | 不耦合 `selected_keys` 或任何预设分区规则，由 Agent 根据动作和要求自己判断怎么拼 |
| 第一期执行方式 | Web 生成「要求 prompt」，用户复制给任意外部 agent 处理；产物回到 Web（落盘或粘贴导入） |
| 动作组 | `st_*` 与 `stn_*`（分类视图生成的连续故事组） |
| 契约粒度 | 一份契约对应一个动作组；新增帧可以参考任意动作 |
| 多角色 | 选了多个角色且定制要求中有说明时，Agent 可以把角色分配到动作里的不同人物（例如替换 1boy）；否则保留动作原词 |

---

## 1. 可复用的现有能力

| 已有能力 | 位置 | 用途 |
|---|---|---|
| AgentComposer：`composer: agent` + `agent_result` → PromptBundle，画风由 renderer 叠加 | `composers/agent.py`、`services/json_api.py` | **生图通道直接复用**：契约每帧的 positive/negative 作为 `agent_result` 提交，artist 仍由脚本控制 |
| 动作知识库 Catalog（`kb facets/search/show/collections`，基于 `classify.yaml`） | `knowledge_base/`、`动作改2/tools/knowledge_base` | Agent 新增场景时检索参考动作 |
| 动作库 Skill：`action-kb-search`、`novelai-v4-5-syntax` | `动作改2/.agents/skills/` | 检索流程与权重语法直接引用，不重复写 |
| 节点模型：角色分区（hair/eyes/upper_clothes…）、`character_scope`、`clothing.state`、`classify.yaml` | 节点 `meta.yaml` / `classify.yaml` | 作为 Agent 判断的**信息**提供给它，不作为硬规则 |
| tag 归一化、去重、冲突规则 | `policies/rules/tag_normalize.py`、`dedupe.py`、`tag_conflict.py` | 兜底匹配与校验器复用 |
| Web 组件：NodeRoleGroup、RenderParamsPanel、ComfyTargetPanel、GenerationTasksPanel、`compare/tagDiff.ts` | `web/src` | 新页面直接组合 |

core 的原则不变：不绑定 LLM SDK，只产出任务、接收结果。

---

## 2. 总体流程

```text
 Web: 选节点(角色/动作组/服装/背景) + 定制要求
   │
   ├─ 命中历史契约？ ──是──> 加载契约 → 可视化 → 生图
   │
   └─ 新建 ComposeRequest（contracts/requests/<id>/request.yaml）
          │
          ▼
   生成「要求 prompt」（两种形式，见 §7）
          │  用户复制给外部 agent
          ▼
   外部 agent 产出契约
     ├─ 有仓库和工具：用 contract CLI 直接写入 contracts/
     └─ 无工具（纯对话）：输出契约 YAML → 用户粘贴到 Web「导入」
          │
          ▼
   脚本 resolve（展开引用、标注来源、生成 diff）+ validate（按目标格式校验）
          │
          ▼
 Web: 契约可视化（来源着色 / diff / 校验结果）→ 选帧 + 画风 + 参数 → 生图
          │   每帧 = compose request { composer: agent, agent_result, artist 节点 }
          ▼
   现有 generate / job_manager / 出图历史（结果回挂 contract_id + frame_id）
```

---

## 3. 存储布局（PromptAtelier）

```text
contracts/                       # 路径由 config: contract.root 配置
  requests/
    req_20261102_153012_ab12/
      request.yaml               # Web 提交的请求，不可变
      context.json               # 请求时的来源快照（带 token ID，见 §5）
      prompt_tools.md            # 给有工具的 agent 的要求 prompt
      prompt_standalone.md       # 给纯对话 agent 的自包含要求 prompt
  ct_<id>/
    rev_001.yaml                 # 契约修订，不可变；改动生成新 rev
    rev_002.yaml
    current -> rev_002.yaml      # 或在 index 中记录
cache/contract_index.json        # 可重建索引：用于按节点筛选、列表展示
```

`context.json` 保存请求时的来源内容，保证即使素材库之后改了，契约仍可复现与着色；`content_hash` 用来提示「来源已更新」。

---

## 4. 文件格式

### 4.1 ComposeRequest（Web → Agent）

```yaml
schema: tags-machine.compose-request/v1
id: req_20261102_153012_ab12
created_at: 2026-11-02T15:30:12+08:00
target_format: nai-v4.5          # 见 §6
nodes:
  characters:                    # 可多个
    - key: c1
      ref: danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女
      content_hash: sha256:...
  action_group:
    ref: stn_20260922_0028       # st_* / stn_*
    members_hash: sha256:...
  clothing:   { key: cl, ref: 服装/xxx, content_hash: sha256:... }    # 可选
  background: { key: bg, ref: 背景/simple_room, content_hash: sha256:... }  # 可选
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
parent_contract: null            # 基于历史契约修改时填 {id, revision}
```

### 4.2 Contract（Agent → Web，唯一事实源）

Agent 写的部分（**作者层**）：

```yaml
schema: tags-machine.compose-contract/v1
id: ct_homura_stn_0028
revision: 2
parent_revision: 1
request_id: req_20261102_153012_ab12
target_format: { id: nai-v4.5, version: 1 }
author: { kind: agent, name: "<外部 agent / 模型>", note: "" }   # 手工微调时 kind: manual
summary: 背景改夜晚教室；服装连续；新增 1 个过渡镜头

frames:
  - id: f01
    source: { type: action, member: 1 }      # 动作组第 1 个成员；action | custom
    character_refs: [c1]
    title: 俯身吐舌
    positive:
      - c1.character.1                       # 引用：原样带入
      - c1.copyright.1
      - c1.hair.1
      - a.3
      - { ref: a.7, text: "1.2::bent over::" }   # 引用 + 改写 → modified
      - { add: night classroom, reason: 背景覆盖为夜晚教室 }
    negative:
      - c1.neg.1
    removed_reasons:                         # 可选：解释删掉了哪些来源词
      - { refs: [a.12, a.13], reason: 白底与背景覆盖冲突 }
    notes: 外层上衣与动作的裸露状态冲突，未带入 upper_clothes。

  - id: f03b
    source: { type: custom, inspired_by: [r1] }   # r1 = kb show 读到的参考动作
    character_refs: [c1]
    positive:
      - c1.character.1
      - { ref: r1.4 }                         # 也可以引用参考动作的词
      - { add: looking back, reason: 过渡镜头 }
```

脚本生成的部分（**解析层**，`contract resolve` 写入，只读）：

```yaml
    resolved:
      positive_segments:
        - { text: akemi_homura, origin: character, owner: c1, section: character, id: c1.character.1 }
        - { text: "1.2::bent over::", origin: modified, from: bent over, id: a.7 }
        - { text: night classroom, origin: added, reason: 背景覆盖为夜晚教室 }
        - { text: 1girl, origin: action, id: a.1, also_in: [c1.base.1] }   # 多处存在，仅提示
      removed:                       # 本帧动作原词中未被引用的
        - { text: white background, origin: action, id: a.12, reason: 白底与背景覆盖冲突 }
      omitted_sections:              # 角色未带入的分区（分区级展示，不逐词列出）
        c1: [upper_clothes, weapons]
      rendered: { positive: "akemi_homura, ...", negative: "red_glasses" }
      validation: { status: pass, issues: [] }
```

- `origin` 取值：`character | action | clothing | background | reference | added | modified | ambiguous`，决定 Web 底色。
- 不含 artist、质量前缀、尺寸、种子等生图参数。
- 多角色且 profile 支持分角色提示词时（NAI v4+ `char_captions`），帧可写 `characters: [{ref: c1, positive: [...]}, ...]`，结构与 `positive` 相同。

---

## 5. 来源标注：引用式写法

### 5.1 原则：来源在书写时确定，不靠事后匹配

`contract context` 给每个来源词分配稳定的短 ID：

| 前缀 | 来源 | 示例 |
|---|---|---|
| `cN.<section>.<i>` | 第 N 个角色的某分区 | `c1.hair.1 = black_hair` |
| `cN.neg.<i>` | 角色负面词 | `c1.neg.1 = red_glasses` |
| `a.<i>` | **本帧**对应动作成员的正向词 | `a.3 = leaning forward` |
| `a.neg.<i>` | 本帧动作负面词 | |
| `cl.<i>` / `bg.<i>` | 服装 / 背景节点 | `bg.1 = classroom` |
| `rN.<i>` | Agent 通过 `kb show` 引入的参考动作 | `r1.4 = looking back` |

Agent 写帧时用三种写法：

| 写法 | 含义 | origin |
|---|---|---|
| `a.3` | 原样带入 | 由 ID 前缀决定 |
| `{ref: a.7, text: "..."}` | 基于来源词改写（权重、同义替换、细化） | `modified`，记录 `from` |
| `{add: "...", reason: "..."}` | 新增 | `added` |

脚本只做展开，来源**由构造保证**，不存在猜测。Agent 拼什么、带哪些分区、怎么改，完全由 Agent 决定。

### 5.2 兜底：Agent 写了纯文本

外部 agent 不方便用 ID，或直接输出了一行 prompt 时，`resolve` 兜底匹配：

1. 规范化：去权重（`{}` `[]` `1.2::x::` `(x:1.2)`）、下划线/空格、大小写、转义括号。
2. 在**本帧可见来源**（本帧动作成员 + 选中角色 + 服装 + 背景 + 已声明的参考）中查找：
   - 0 命中 → `added`（没有 reason 时校验给 warn）。
   - 1 命中 → 归到该来源；文本与原文不同 → `modified`。
   - 多命中 → `ambiguous`，记录 `candidates`。校验给 warn，要求改成引用写法；Web 显示虚线、多色。
3. 不做「优先级猜测」，也不做语义匹配：如 `bare shoulders → off shoulder` 未用引用表达，就如实显示为「删除 + 新增」。

### 5.3 多处存在但已用引用选定

例如 `1girl` 同时出现在动作和角色中，Agent 引用了 `a.1`，就按动作着色，`also_in` 列出其他出处，Web 悬停时提示。这不算问题，不发 warn。

### 5.4 removed 的范围

- 动作词：本帧动作成员中未被引用的正向词，逐词列出（可由 `removed_reasons` 批量补理由，不强制）。
- 角色词：按**分区**展示「未带入的分区」，不逐词列出，避免噪声。
- 服装 / 背景：同角色，按节点或分区展示。

---

## 6. 目标格式 Profile + 可扩展校验器

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
             unresolved_refs, ambiguous_origin, added_reason]
```

起步内置：`nai-v3`、`nai-v4`、`nai-v4.5`、`nai-v5`、`sdxl-danbooru`（`(tag:1.2)` 语法、CLIP 75 token 分块）、`natural-language`（允许中文和句子，给 ComfyUI 的自然语言模型预留）。各模型的 token 上限、权重范围都只写在 profile 里，不写死在代码中。

**校验器接口**（注册表 + entry point，项目内或插件包都能扩展）：

```python
class ContractValidator(Protocol):
    id: str
    def validate(self, frame: ResolvedFrame, profile: FormatProfile, ctx: ValidationContext) -> list[Issue]: ...
# Issue: { validator, severity: error|warn|info, segment_index?, message, fix_hint? }
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
| `unresolved_refs` | 引用了不存在的 ID（error） |
| `ambiguous_origin` | 兜底匹配出现多来源（warn） |
| `added_reason` | 新增词缺少理由（warn） |

---

## 7. 「要求 prompt」与 Agent 执行

### 7.1 第一期：复制给外部 agent

Web 提交请求后生成两份 prompt，界面上提供「复制」按钮：

| 形式 | 内容 | 产物回传 |
|---|---|---|
| **工具版** `prompt_tools.md` | 请求 ID、要做什么、要使用的 Skill（`compose-contract-author`）、CLI 命令清单、完成标准 | agent 在仓库中运行 `contract …` 命令，直接写入 `contracts/`；Web 轮询到后刷新 |
| **自包含版** `prompt_standalone.md` | 把 `context.json` 精简后内嵌（带 token ID 的来源词表）+ 契约作者层的格式说明 + 规则 + 目标格式要点 | agent 输出契约 YAML，用户在 Web「导入契约」中粘贴；Web 调用 resolve + validate，有问题时把校验结果显示出来，可以再复制给 agent 修 |

自包含版要控制长度：动作组每个成员只给正向词、classify 摘要、`clothing.state`、`character_scope`；角色只给分区词表。

### 7.2 后续：一键执行（P2）

`contract.runner: manual | claude-cli | api`。后端用 job_manager 启动 headless agent 执行同一份工具版 prompt，产物与第一期一致。

---

## 8. Skill：`compose-contract-author`

放在 `.agents/skills/compose-contract-author/`（同步到 `.claude/skills`）。

### 8.1 工具（`tags_machine_core contract …`，均输出 JSON）

| 命令 | 作用 |
|---|---|
| `contract request show <req>` | 请求内容、目标格式摘要 |
| `contract context <req> [--frame N]` | 带 token ID 的来源词表（角色分区、各动作成员、服装、背景），可按帧取 |
| `contract new <req>` | 创建空契约（只有帧列表和 source，**不预填 tag**，避免诱导 Agent 照搬） |
| `contract set-frame <ct> <frame> --file frame.yaml` | 写入一帧（作者层） |
| `contract add-frame <ct> --after f03 [--inspired-by <kb ref>]` | 新增自定义帧，参考动作自动注册为 `rN` |
| `contract resolve <ct>` | 展开引用、兜底匹配、生成 removed / diff / rendered |
| `contract validate <ct>` | 跑 profile 校验器 |
| `contract finalize <ct>` | 通过校验后写入新 revision 并更新索引 |
| `contract import <file> --request <req>` | 导入纯文本 agent 的产物（Web「导入」也调用它） |
| `kb facets/search/show` | 已有，新增场景时检索 |

### 8.2 Skill 给 Agent 的指引（原则，不是硬规则）

- 理解要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 每帧自主判断角色要带哪些内容：身份词通常保留；服装、发型、配饰等结合动作的裸露状态、镜头范围（`character_scope`）、构图和要求来取舍。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词、混入的角色/画风词去掉。
- 多角色：只有选了多个角色且要求中说明了分配方式时，才替换动作中的人物；否则保留动作原词。
- 连续性：同一组中的服装和场景保持一致，除非要求变化。
- 新增帧：用 `kb search` 找参考，`kb show` 读内容，用 `rN.*` 引用参考词。
- 尽量用引用写法；新增词写 reason；`validate` 的 error 必须修。
- 禁止：写画师名、质量前缀、生图参数；修改素材库源节点。
- 权重语法遵循目标格式（NAI 4.5 参考 `novelai-v4-5-syntax`）。

---

## 9. Web：Agent Studio

新页面，与 Custom / Compare / History 并列，三栏：

**左栏：请求与历史**
- 节点选择：角色（可多选，显示 c1/c2 标号）、动作组（只列 `st_*` / `stn_*`，显示成员数和首图）、服装、背景。
- 历史契约：按当前所选节点筛选，标注匹配程度（完全 / 部分），显示状态、格式、帧数、摘要，以及「来源已更新」。
- 定制要求：自由文本 + 结构化开关 + 目标格式。
- 操作：「生成要求」（显示两份 prompt，可复制）、「导入契约」（粘贴 YAML）、「基于此契约修改」。
- 请求列表：待处理的请求，显示是否已有产物。

**中栏：契约查看**
- 头部：格式 profile、校验汇总、revision 切换与两版对比。
- 帧列表：来源动作名和缩略图（自定义帧显示「自定义」+ 参考来源）、phase、scope、character_refs。
- 每帧三种视图：
  - **最终**：tag chip 按 origin 着色。参考配色：角色 = 蓝（多角色按 c1/c2 区分色相）、动作 = 中性灰、服装 = 紫、背景 = 青、参考动作 = 靛、新增 = 琥珀、修改 = 橙描边、歧义 = 虚线；悬停显示 ID、section、reason、also_in。
  - **Diff**：相对本帧动作原词。removed 删除线、added 高亮、modified 显示 from → to；角色「未带入的分区」单独一行。
  - **原文**：rendered 文本，可复制。
- 校验问题标在对应 chip 上。
- 手工微调：编辑 chip（引用 / 改写 / 新增）→ 保存为新 revision，`author.kind: manual`。

**右栏：生图**
- 画风（不进契约）、出图参数、ComfyUI 目标（复用现有组件）。
- 选帧（全选 / 勾选），可选「帧 × 画风」对比。
- 提交：每帧构造 `{composer: "agent", agent_result: {positive, negative, character_scope}, character 节点, artist 节点, contract: {id, revision, frame_id}}`，走现有后台批量任务。
- 结果按帧回挂；History 页可按契约筛选。

---

## 10. 后端改动清单

- 新模块 `contracts/`：pydantic 模型（Request / Contract / Frame / 作者层条目 / Resolved）、context 构建与 token ID 分配、resolve、validators 注册表、profile 加载、存储与索引、两种要求 prompt 的模板渲染。
- CLI：`contract …` 子命令（§8.1）。
- API：
  - `GET /contracts?node=&status=&format=`
  - `GET /contracts/{id}?revision=`
  - `POST /contracts/requests`
  - `GET /contracts/requests/{id}`（含两份 prompt）
  - `POST /contracts/import`
  - `POST /contracts/{id}/revisions`
  - `GET /formats`
- 生图：compose request 增加 `contract` 追溯字段，写入 `PromptBundle.meta.extra.contract` 与结果索引；AgentComposer 核心不改。
- 配置：`contract.root`、`contract.runner`。

---

## 11. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | schema、context/token ID、resolve、校验器（核心几项）、profiles（nai-v4.5、nai-v4、sdxl-danbooru）、CLI、Skill、两份要求 prompt；Web 请求表单 + 复制 prompt + 导入 + 只读查看器（着色 / diff）+ 按帧生图 | 一个 `stn_` 组 + 一个角色：外部 agent 产出契约，导入后着色正确、校验通过并能出图 |
| P1 | 历史筛选、来源过期提示、手工微调 revision、revision 对比、多角色分角色提示词 | — |
| P2 | 一键执行（claude-cli / api）、格式转换（换 profile 重写权重语法）、更多校验器（tag 词典存在性） | — |

---

## 12. 剩余待定

1. `contracts/` 目录是否纳入 git？倾向入库，方便追溯与跨机器共享；如果契约量大或含敏感内容，可以改为忽略。
