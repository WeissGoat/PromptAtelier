# Agent 拼接契约（Compose Contract）设计 v1

> 状态：第一期（P0）已实现，部分 P1 一并完成，实现情况见 §12。
> UI 原型：https://claude.ai/artifact/3EwBb7NEkrBoeEL9ZSwzuq （主界面、要求 prompt / 导入、按帧编辑、结果故事板、动作组参考）
> 目标：在 Web 现有「脚本式拼接（Custom）」之外，增加「Agent 式拼接」：
> 用户在 Web 选素材节点 + 写定制要求 → Agent 自主拼出每一帧的完整提示词，写进契约文件 → Web 加载、解析、可视化、生图。

## 0. 已确认的决策

| 问题 | 结论 |
|---|---|
| 分工 | **Agent 只写完整提示词**（自由文本，可换行）；提示词全部由 Agent 拼接，脚本不生成提示词内容 |
| 标记与 diff | 角色 / 动作 / 新增标记和 diff 由 **Web 实时解析**，不写进契约文件 |
| 来源 | 帧级：每帧来自动作组中的哪个动作 node，或是 Agent 自定义 |
| 文件格式 | Markdown + YAML front matter，每帧提示词放在代码块中（§4） |
| 存放 | `TagsHub/动作改2/contracts/`，平铺，一个任务一个文件；历史由动作库仓库的 git 记录 |
| 修改 | Web 按帧编辑，直接保存回原文件，不生成修订文件 |
| 与 AlbumPlan 的关系 | 完全无关 |
| 角色适配 | 不耦合 `selected_keys` 或预设规则，由 Agent 自己判断 |
| 第一期执行方式 | Web 生成「要求 prompt」，用户复制给任意外部 agent 处理 |
| 动作组 | `st_*` 与 `stn_*` |
| 契约粒度 | 一份契约对应一个动作组；新增帧可以参考任意动作 |
| 多角色 | 选了多个角色且要求中有说明时，Agent 可以把角色分配到动作中的不同人物；否则保留动作原词 |
| 动作内容读取 | 沿用现有 `NodeReader`，不改：`stn_*`（全部有 `meta.yaml`）正面取 `tags.action`、负面取 `negative_prompt`；`st_*`（只有 `tags.txt`）正面取 `=` 之前的行，负面为空，`=` 之后的扩展行（`uc` / `origin_uc` / `origin_clear` / `node_background` 等）不解析 |
| 采用 | 每帧可采用多张，记录存在 PromptAtelier 出图目录，不写进契约 |

---

## 1. 可复用的现有能力

| 已有能力 | 位置 | 用途 |
|---|---|---|
| AgentComposer：`composer: agent` + `agent_result` → PromptBundle，画风由 renderer 叠加 | `composers/agent.py`、`services/json_api.py` | **生图通道直接复用**：每帧的 positive/negative 作为 `agent_result` 提交，artist 仍由脚本控制 |
| 动作知识库 Catalog（`kb facets/search/show`，基于 `classify.yaml`） | `knowledge_base/`、`动作改2/tools/knowledge_base` | Agent 新增场景时检索参考动作 |
| 动作库 Skill：`action-kb-search`、`novelai-v4-5-syntax` | `动作改2/.agents/skills/` | 检索流程与权重语法直接引用 |
| 节点信息：角色分区、`character_scope`、`clothing.state`、`classify.yaml` | 节点 `meta.yaml` / `classify.yaml` | 作为 Agent 判断的信息 |
| tag 归一化、去重、冲突规则 | `policies/rules/` | 校验器复用；Web 解析的归一化规则与之保持一致 |
| Web 组件：NodeRoleGroup、RenderParamsPanel、ComfyTargetPanel、GenerationTasksPanel、`compare/tagDiff.ts` | `web/src` | 新页面直接组合 |

---

## 2. 总体流程

```text
 Web: 选节点(角色/动作组/服装/背景) + 定制要求
   │
   ├─ 命中历史契约？ ──是──> 加载 → 解析 → 可视化 → 生图
   │
   └─ 新建契约文件（status: pending，只有 front matter）
          │
          ▼
   Web 生成「要求 prompt」（工具版 / 自包含版，见 §6）→ 用户复制给外部 agent
          │
          ▼
   外部 agent 写每一帧的完整提示词
     ├─ 有仓库和工具：直接编辑契约文件，用 `contract check` 自检
     └─ 纯对话：输出帧内容 → 用户粘贴到 Web「导入」
          │
          ▼
 Web: 解析（标记着色 + diff）+ 后端校验 → 按帧微调（写回文件）→ 选帧 + 画风 + 参数 → 生图
          │   每帧 = compose request { composer: agent, agent_result, artist 节点 }
          ▼
   现有 generate / job_manager / 出图历史（结果回挂 contract_id + frame_id）
```

---

## 3. 存储

```text
TagsHub/动作改2/contracts/            # config: contract.root
  20261102-1530_stn_20260922_0028.md
  20261103-0912_st_body_bath.md
PromptAtelier/cache/contract_index.json   # 可重建索引：按节点筛选、列表展示
```

- 文件名即 `id`：Web 创建时按「创建时间 + 动作组 ref」生成，重名时加短后缀。保留中日文等字母数字（如 `20261104-0238_stn_铃兰x忍冬`），空格、斜杠等其他字符换成 `_`。人可读的名称放在 `title` 中，由 Agent 选填。
- 一个任务一个文件，请求信息和产物在同一个文件里；「要求 prompt」由 Web 按需生成，不落盘。
- 历史与回滚依赖动作库仓库（`tags_machine_node_story`）的 git。
- 不影响现有工具：KB 只扫描 `new/` 与 `st_*`，分类视图只管理 `pn_*` / `stn_*`。

---

## 4. 文件格式

### 4.1 为什么用 Markdown

| 方案 | 问题 |
|---|---|
| YAML | 提示词里常有 `{` `[` `:` `::` `#`，Agent 容易写坏引号或缩进；多行字符串的缩进要求严格 |
| JSON | 换行必须写成 `\n`，人工阅读和编辑都很差 |
| **Markdown + front matter** | 元数据放 front matter；每帧提示词放在代码块里，内容原样保留，不需要转义，可以随意换行；LLM 写 Markdown 最稳定；GitHub 上直接可读 |

### 4.2 示例

````markdown
---
schema: tags-machine.compose-contract/v1
id: 20261102-1530_stn_20260922_0028
title: Homura · 夜晚教室            # Agent 选填
status: done                        # pending | done
created_at: 2026-11-02T15:30:12+08:00
target_format: nai-v4.5
nodes:
  characters:
    c1: { ref: "danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女", content_hash: "sha256:..." }
  action_group: { ref: stn_20260922_0028, content_hash: "sha256:..." }
  clothing: null
  background: null
requirements: |
  背景统一改为夜晚教室，保持服装连续；第 3 帧之后加一个窗边回头的过渡镜头。
options: { keep_order: true, allow_new_frames: true, max_new_frames: 2 }
author: "<外部 agent / 模型>"       # Agent 选填
---

## f01 俯身吐舌
source: new/20260922_0028_01_俯身吐舌露乳牛仔短裤
characters: c1
size: portrait

```positive
akemi_homura, mahou_shoujo_madoka_magica,
black_hair, purple_eyes,

1girl, solo, tongue out, ;p, 1.2::leaning forward::, bent over, cowboy shot,
night, classroom, window
```

```negative
red_glasses
```

动作为 breasts out，外层上衣不带。

## f03b 窗边回头
source: custom
inspired_by: new/2025-xx-xx_窗边回头
characters: c1

```positive
akemi_homura, black_hair,
looking back, standing, by window, night, classroom
```
````

### 4.3 解析规则

- front matter：YAML，由 Web 创建；Agent 只填 `title`、`author`，以及完成后把 `status` 改为 `done`。
- 帧：每个 `## <帧id> <标题>` 开始一帧。帧 id 用于回挂出图结果，修改提示词时保持不变。
- 帧元数据：标题下方 `key: value` 行，目前有：
  - `source`：动作 ref，或 `custom`
  - `inspired_by`：可选，多个用逗号分隔
  - `characters`：本帧出现的角色，如 `c1, c2`
  - `size`：可选，本帧分辨率方向，取 `portrait`（竖）/ `landscape`（横）/ `square`（方）。只写方向，具体像素由所选画风的尺寸预设决定（与 Custom 的尺寸选项一致）；不写表示由生图时决定
- 提示词：
  - ```` ```positive ```` / ```` ```negative ```` 是本帧主提示词。
  - 多角色且格式支持分角色提示词时，用 ```` ```positive c1 ```` / ```` ```positive c2 ````（及可选的 ```` ```negative cN ````）。分工见 §4.4。
- 其他文字：都视为该帧备注，Web 原样展示。
- 换行和空行：Agent 可以随意用来分组排版。提交生图时如何处理由格式 profile 决定（`newline: separator`：换行视为分隔符，默认值；或 `newline: keep`）。

### 4.4 多角色

契约里多角色只用一种写法：分角色代码块。

| 代码块 | 内容 |
|---|---|
| ```` ```positive ```` | 画面共用：人数 tag、互动、构图镜头、背景环境 |
| ```` ```positive cN ```` | 角色 cN 自己的全部内容：性别词、身份词、服装、动作里属于这个人的部分 |
| ```` ```negative cN ```` | 可选，只对 cN 生效的负面词 |

- 帧的 `characters:` 中每个角色都应有 ```` ```positive cN ````；单人帧可以只写主提示词。
- 动作库里的行内写法 `::character A: … ::` 由 Agent 转写成 cN 块（默认 A→c1、B→c2，定制要求优先），不与 cN 块混用。只有行内块、没有 cN 块的帧仍可出图（走 Character Prompts 的 Auto 拆分），校验器给 info 提示改写。
- 出图：
  - NovelAI 画风、Character Prompts 开着：cN 块按 c1、c2… 的顺序作为角色提示词提交（`character_prompts: {mode: explicit}`），主提示词不拆分；没有 cN 块的帧仍用 Auto。
  - 画风模型不支持分角色（V3）：renderer 把 cN 块并进主提示词（`unsupported: merge`）。
  - ComfyUI 画风或关掉 Character Prompts：前端把 cN 块并进主提示词。
- `prompt_hash` 包含各 cN 块；没有 cN 块时与只算主提示词的结果相同。

---

## 5. Web 解析：标记与 diff（不落盘）

在 Web 中实时计算，放在共享 TS 模块（例如 `web/src/contracts/analysis.ts`）中，有单元测试。

### 5.1 分词

按 profile 的分隔符（逗号）和换行切分，记录每个 tag 在原文中的位置，展示时保留 Agent 的换行排版。权重写法（`{x}` `[x]` `1.2::x::` `(x:1.2)`）在分词后剥离，归一化成「裸 tag + 权重」。

### 5.2 标记：这个词属于谁

拿本帧的可见来源做对照：

| 来源 | 内容 |
|---|---|
| 角色 c1/c2… | 角色节点各分区的词（记下 section） |
| 动作 | 本帧 `source` 动作 node 的正向 / 负面词 |
| 服装 / 背景 | 选中的服装、背景节点 |
| 参考 | `inspired_by` 中的动作（仅自定义帧） |

归一化规则：去权重、下划线↔空格、大小写、转义括号；与 `policies/rules/tag_normalize.py` 保持一致。

| 匹配结果 | 显示 |
|---|---|
| 0 个来源 | **新增**（琥珀色） |
| 1 个来源 | 该来源的颜色；与原文写法或权重不同时加「改写」描边，悬停显示原文 |
| 多个来源 | 多色 chip（例如左右分色或底部色条），悬停列出全部来源。**不做优先级猜测**；diff 不受影响 |

参考配色：角色 = 蓝（c1/c2 区分色相）、动作 = 中性灰、服装 = 紫、背景 = 青、参考 = 靛、新增 = 琥珀。

已知限制：只做字面匹配。像 `bare shoulders → off shoulder` 这种语义替换会显示为「删除 + 新增」，这是如实的结果。自然语言类格式（整句提示词）无法按 tag 切分，只做短语级高亮或不标记。

### 5.3 Diff：相对来源动作

- 对比对象：本帧最终正向提示词 vs 来源动作 node 的正向词（按 `NodeReader` 读取：`meta.yaml` 的 `tags.action`，或 `tags.txt` 中 `=` 之前的行）。
- 只列三类：改写（同词不同写法/权重，显示 from → to）、删除（删除线）、新增（带标记颜色）。保留的词不单独列出。
- 自定义帧没有来源动作：全部显示为新增；有 `inspired_by` 时可以切换为相对参考动作做 diff。
- 复用 `compare/tagDiff.ts` 的思路与样式。

### 5.4 来源过期

front matter 中记录了各节点的 `content_hash`。加载时与当前节点比对，不一致则提示「来源已更新」。此时标记和 diff 用的是当前节点内容。

### 5.5 刷新：Agent 写完后 Web 怎么知道

不让 Agent 的工具调用直接通知前端：Agent 可能在另一台机器上，通过 git 同步动作库；Web 也不一定在运行。改由 Web 自己发现变化：

- **自动检查**：Agent Studio 页面打开时，每 5 秒请求一次 `GET /contracts/index?since=<上次时间>`。后端只比较 `contracts/` 下文件的修改时间，有变化才重新解析，开销很小。
- **pending → done**：显示「Agent 已完成」提示条，点「打开」再载入，不会打断正在看的内容。如果当前正在看的就是这份 pending 契约，则直接载入。
- **正在看的契约被外部修改**：显示「文件已更新，重新载入」；如果正在编辑这一帧，保存时按 §9 的冲突检测处理。
- **手动刷新按钮**：立即重新扫描。Agent 在别的机器上、结果要靠 git 同步时，按住 Shift 点击会先对动作库执行 `git pull --ff-only`，复用 Web 启动时拉取动作库的逻辑。

---

## 6. 「要求 prompt」与 Agent 执行

### 6.1 第一期：复制给外部 agent

Web 对 pending 契约生成两种 prompt，提供「复制」按钮：

| 形式 | 内容 | 产物回传 |
|---|---|---|
| **工具版** | 契约文件路径、任务说明、Skill（`compose-contract-author`）、可用命令、完成标准 | agent 在仓库中直接编辑契约文件，`contract check` 自检；Web 轮询到 `status: done` 后刷新 |
| **自包含版** | 内嵌精简后的素材内容（角色分区词表；动作组各成员的正向词、classify 摘要、`clothing.state`、`character_scope`；服装 / 背景）+ 帧格式说明 + 原则 + 目标格式要点 | agent 按 §4.2 的帧格式输出；用户在 Web「导入」中粘贴，Web 写回文件并校验；有问题时显示校验结果，可以再复制给 agent 修 |

### 6.2 后续：一键执行（P2）

`contract.runner: manual | claude-cli | api`。后端启动 headless agent 执行同一份工具版 prompt。

---

## 7. 格式 Profile + 可扩展校验器

`configs/prompt_formats/<id>.yaml`：

```yaml
id: nai-v4.5
version: 1
family: novelai
models: [nai-diffusion-4-5-full, nai-diffusion-4-5-curated]
separator: ","
newline: separator                  # separator | keep
weight:
  syntaxes: [brace, numeric]        # brace: {tag}/[tag]；numeric: 1.2::tag::
  preferred: numeric
  range: [0.0, 3.0]
language: { allow_cjk: false }
length:
  tokenizer: t5                     # clip | t5 | qwen | approx
  max_tokens: 512                   # 与 NovelAI 官网一致，见 §12.1
  shared_with_characters: true      # 主提示词和各角色提示词共用上限
multi_character: { supported: true, max: 6 }
forbid:
  artist_tags: true                 # artist 由脚本叠加
  quality_tags: renderer
validators: [frame_structure, weight_syntax, bracket_balance, token_length,
             language, forbidden_tags, duplicate_tags, tag_conflict,
             character_count, source_exists, coverage]
```

起步内置：`nai-v3`、`nai-v4`、`nai-v4.5`、`nai-v5`、`sdxl-danbooru`、`natural-language`。各模型的具体数值只写在 profile 里。

校验在后端（Python）执行，Web 加载或保存时调用 API 取结果，Agent 用 `contract check` 调用同一套代码。结果不写进契约文件。

```python
class ContractValidator(Protocol):
    id: str
    def validate(self, frame: ParsedFrame, profile: FormatProfile, ctx: ValidationContext) -> list[Issue]: ...
# Issue: { validator, severity: error|warn|info, frame_id, tag?, message, fix_hint? }
```

| 校验器 | 说明 |
|---|---|
| `frame_structure` | 帧标题、`source`、positive 代码块齐全；帧 id 不重复 |
| `weight_syntax` | 只允许 profile 声明的权重语法 |
| `bracket_balance` | `{}` `[]` `()` `::` 配平 |
| `token_length` | 按 profile tokenizer 计数（与 NovelAI 官网一致）；V4+ 主提示词和角色提示词合计 |
| `language` | 不允许中文时检出 CJK |
| `forbidden_tags` | 画师名、质量词等由脚本负责的内容 |
| `duplicate_tags` / `tag_conflict` | 复用现有 policies 规则 |
| `character_count` | `1girl/2girls/1boy` 与 `characters`、动作 `cast` 一致（主提示词没写人数 tag 时按各角色块加总） |
| `character_blocks` | 分角色（§4.4）：`characters` 中的角色都有 cN 块；行内 `::character X:` 与 cN 块混用（error）；cN 块里写了其他角色的词、分角色时角色词留在主提示词（warn）。作品名、role 分区不参与判断 |
| `source_exists` | `source` 属于本动作组；`inspired_by` 存在 |
| `coverage` | 动作组中没有被任何帧使用的成员（warn） |

---

## 8. Skill：`compose-contract-author`

放在 `.agents/skills/compose-contract-author/`（同步到 `.claude/skills`）。

### 8.1 工具（`tags_machine_core contract …`）

| 命令 | 作用 |
|---|---|
| `contract show <id>` | 契约的请求部分、目标格式摘要、已写的帧 |
| `contract context <id> [--member N]` | 角色分区词表、动作组各成员内容、服装、背景；可以只取单个成员，控制上下文长度 |
| `contract check <id>` | 解析 + 校验，输出 issues（JSON） |
| `kb facets/search/show` | 已有，新增场景时检索 |

Agent 直接编辑契约文件，不需要额外的写入命令。

### 8.2 给 Agent 的指引（原则，不是硬规则）

- 理解要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 每帧自主拼出完整提示词。角色的身份词通常保留；服装、发型、配饰等结合动作的裸露状态、镜头范围、构图和要求来取舍。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词、混入的角色/画风词去掉。
- 尽量沿用素材里的原词写法（便于 Web 标记来源）；需要调整时可以改权重或替换。
- 多角色：按 §4.4 分块写；动作中的人物怎么对应以要求为准，默认行内块 A→c1、B→c2。
- 连续性：同一组中的服装和场景保持一致，除非要求变化。
- 新增帧：用 `kb search` 找参考、`kb show` 读内容；`source: custom`，参考过的写进 `inspired_by`。
- 排版自由，可以换行分组；备注写在帧的代码块之外。
- 完成后 `contract check` 无 error，再把 `status` 改为 `done`。
- 禁止：写画师名、质量前缀、生图参数；修改素材库源节点；修改 front matter 中的请求部分。

---

## 9. Web：Agent Studio

新页面，与 Custom / Compare / History 并列，三栏：

**左栏：请求与历史**
- 节点选择：角色（可多选，显示 c1/c2）、动作组（只列 `st_*` / `stn_*`，显示成员数和首图）、服装、背景。
- 历史契约：按当前所选节点筛选，标注匹配程度（完全 / 部分），显示标题、状态、格式、帧数，以及「来源已更新」。
- 定制要求：自由文本 + 结构化开关 + 目标格式。
- 操作：「新建并生成要求」（复制工具版 / 自包含版 prompt）、「导入」（粘贴帧内容）、「基于此契约新建」（复制请求部分作为新契约的起点）。

**中栏：契约查看**
- 头部：标题、格式、校验汇总、来源过期提示。
- **动作组覆盖**：契约头部状态标签旁一个紧凑按钮「动作组 N +新增数 −缺少数」（新增绿色、缺少红色）。点击直接打开「动作组参考」抽屉，在抽屉里看每个成员是否被使用。数据来自 `coverage` 校验器。
- 帧列表：每帧显示**来源**：动作 node 名、组内序号，以及**来源动作的预览图**（自定义帧显示参考动作的预览图），点击看大图。预览图取动作节点目录里直接放的图片，复用 `web/services/node_previews.py`；没有图片时显示占位（注意：云端的 action-new 只有文本，图片只在 Drive 上）。生成的图显示在帧下方的「结果」一行。
- 每帧三种视图（顶部切换）：
  - **标记**：保留 Agent 的换行排版，tag 按 §5.2 着色，悬停显示来源与原文。
  - **原文**：代码块原文，可复制。
  - **来源原文**：来源动作 node 的原始正向 / 负面提示词，标明读取自哪个文件（`meta.yaml` 或 `tags.txt`）；`st_*` 动作的负面为空。自定义帧显示参考动作的原始提示词。
- Diff 不单独占视图，显示在每帧内容下方（§5.3，只含改写 / 删除 / 新增）；顶部「显示 Diff」开关控制，默认打开。
- 翻译：顶部提供「翻译来源」（谷歌翻译 / AI 翻译）和「译文 开/关」，打开后在标记视图和 Diff 中每个 tag 后显示〔中文〕。直接复用画风工坊的翻译能力：后端 `POST /translate`（`llm/translate.py`、`google_translate`，带缓存），前端 `styleLab/translations.ts` 的 `translationStore` / `useTranslations`（请求合并、失败不重复请求）。实现时把这两个前端模块从 `styleLab/` 挪到公共目录，供两个页面共用。
- 校验问题标在对应 tag 或帧上。
- 按帧编辑：直接编辑该帧文本，保存时只替换文件中该帧的代码块并重新校验；如果文件在此期间被外部修改（mtime/hash 变化），提示冲突。

**动作组参考（抽屉）**
- 点击契约头部的「动作组 N +x −y」按钮打开，覆盖在右侧，不离开当前契约。
- 按组内顺序列出全部成员：预览图、序号和名称、ref、classify 摘要（phase / cast / pose / environment / clothing / scope）、原始提示词。
- 每个成员标明「用于 f01」或「未使用」；可筛选「未使用」。可「定位到帧」「复制 ref」「复制原始提示词」。
- 底部列出自定义帧引用的参考动作（`inspired_by`）。

**右栏：生图**
- 画风（不进契约）、出图参数（Negative、尺寸、Width/Height、NT、N、Seed、ComfyUI 运行位置，复用 Custom 的组件）。
- 尺寸多一个选项「契约默认」，并设为默认值：用每帧的 `size`，帧没写时随机（同 Custom 的随机）；画风没有该方向的预设时也退回随机，并在任务标签中注明。其余选项（随机 / 竖 / 横 / 方 / 自定义）会覆盖所有帧。
- 提示词行为：Primary / Compare 方案、Character Prompts（Auto / Off + Add male caption）。不提供 Identity Minimal Sections（契约里带哪些角色词由 Agent 决定）。
- Policy Rules：与 agent composer 一致，默认跳过（`apply_to.agent: false`），区域默认隐藏；勾选「对契约提示词启用 Policy Rules」后才展开规则列表，由用户自己决定。
- 选帧（全选 / 勾选），可选「帧 × 画风」对比。
- 提交：每帧构造 `{composer: "agent", agent_result: {positive, negative}, character 节点, artist 节点, contract: {id, frame_id}}`，走现有后台批量任务。
- 结果按帧回挂（见下）。

**生图结果**

每张图的生成元数据记录 `contract: {id, frame_id, prompt_hash}`。`prompt_hash` 是生成时该帧 positive + negative 的 hash，用来判断图是不是用当前版本的提示词出的。结果在三个地方看：

1. **主界面每帧下方**：缩略图条 + 「N 张 · M 轮」摘要 + 「查看全部」。
2. **结果故事板**（契约级页面）：
   - 每帧一行，按帧顺序排，连起来看整组的连贯性；每行左侧是帧信息和提示词摘要，右侧按「画风 · 时间 · seed」分组列出各轮结果。
   - 用旧版提示词生成的图半透明，并标「提示词已改」；可勾选「只看当前提示词的结果」。
   - 可按画风筛选。
   - 每帧可以「采用」任意多张（蓝框）；可筛选「只看已采用」。
   - 采用记录不写进契约文件，存在 PromptAtelier 的出图索引里：`<output_dir>/.contract_picks/<契约 id>.json`，内容为 `{frame_id: [图片路径, ...]}`。与出图结果放在一起、同样不入 git；出图历史扫描会跳过以 `.` 开头的目录。
   - 未出图的帧显示「生成此帧」。
3. **出图历史**：新增「契约」筛选类型，批次标签显示契约标题 + 帧。

点击任意图片都打开现有的图片详情对话框（大图、生成参数、两张图的提示词对比、卷帘 / 闪烁对比）。

---

## 10. 后端改动清单

- 新模块 `contracts/`：
  - Markdown 契约解析与按帧写回（只替换目标帧的代码块，保留其余文本）
  - 创建契约文件
  - 来源节点加载与 `content_hash`
  - validators 注册表与 profile 加载
  - 索引
  - 两种要求 prompt 的模板渲染
- CLI：`contract show / context / check`。
- API：
  - `GET /contracts?node=&format=&status=`
  - `GET /contracts/index?since=`：按修改时间返回有变化的契约（§5.5）
  - `POST /contracts/refresh?pull=1`：重新扫描，可选先 git pull 动作库
  - `GET /contracts/{id}`：解析结果 + 校验结果 + 各帧来源节点内容（供 Web 做标记与 diff）
  - `POST /contracts`：创建
  - `GET /contracts/{id}/prompt?kind=tools|standalone`
  - `PUT /contracts/{id}/frames/{frame_id}`：带文件 hash 做冲突检测
  - `GET /contracts/{id}/results`：按帧分组的出图结果（含 prompt_hash 是否为当前版本）
  - `PUT /contracts/{id}/picks`：增删某帧的采用图片（每帧可多张）
  - `POST /contracts/{id}/import`
  - `GET /formats`
- 生图：compose request 增加 `contract` 追溯字段，写入 `PromptBundle.meta.extra.contract` 与结果索引；AgentComposer 核心不改。
- 配置：`contract.root`（默认 `<design_root>/动作改2/contracts`）、`contract.runner`。

---

## 11. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 契约格式与解析、创建、核心校验器、profiles（nai-v4.5、nai-v4、sdxl-danbooru）、CLI、Skill、两种要求 prompt；Web 新建 + 复制 prompt + 导入 + 查看（来源 / 标记 / diff）+ 按帧生图 | 一个 `stn_` 组 + 一个角色：外部 agent 写完契约，Web 来源、着色、diff 正确，校验通过并能出图 |
| P1 | 历史筛选与索引、来源过期提示、按帧编辑写回、多角色分角色提示词 | — |
| P2 | 一键执行（claude-cli / api）、更多校验器（tag 词典存在性）、自然语言格式的短语级标记 | — |

---

## 12. 实现情况（P0）

| 部分 | 位置 | 说明 |
|---|---|---|
| 契约解析 / 写回 / 创建 / 索引 | `src/tags_machine_core/compose_contracts/`（`parser.py`、`store.py`、`service.py`） | 包名用 `compose_contracts`，因为 `contracts.py` 已是 PromptBundle 等数据模型 |
| 动作组与来源节点 | `compose_contracts/sources.py` | 沿用 `NodeReader`；成员 ref 取链接指向的 `new/<id>`：Linux 是相对符号链接 `../new/<id>`，Windows 上成员和 `new` 都是指向同一外部目录（如 `G:/GoogleDrive/action`）的 junction，按 `new` 的指向换算，两边得到同样的 ref 和组 hash。也接受 `stn_x/01_...`、成员目录名、`#N`；本机换算不出 `new/` 时按最后一段（链接目标目录名）匹配 |
| 格式 profile | `configs/prompt_formats/`（nai-v3、nai-v4、nai-v4.5、nai-v5、nai-v5-curated、sdxl-danbooru） | `contract.formats_dir` 可改目录 |
| 校验器 | `compose_contracts/validators.py` | §7 的 11 个全部实现，另加 `character_blocks`（§4.4）；`token_length` 用真实分词器，见 §12.1 |
| token 计数 | `src/tags_machine_core/prompt_tokens.py` | 契约帧、`contract check` 的 `tokens`、`/compose-preview` 的 `token_usage` 共用 |
| 要求 prompt | `compose_contracts/prompts.py` | 工具版 / 自包含版 |
| CLI | `tm-core contract show / context [--member N] / check / prompt` | `check` 有 error 时退出码 1 |
| Skill | `.agents/skills/compose-contract-author/`（`.claude/skills` 指向它） | |
| API | `web/routes/contracts.py` | §10 全部接口；另有 `GET /contracts/action-groups`、`/contracts/action-groups/detail`、`PUT /contracts/{id}/fields` |
| 生图追溯 | `services/json_api.py`、`renderers/common.py`、`renderers/novelai.py`、`execution.py` | compose 请求的 `contract` → `PromptBundle.meta.extra.contract` → render meta → PNG `tags_machine_core.contract` |
| 结果与采用 | `ContractService.results / update_picks` | 契约批次输出到 `outputs/compares/contract_<时间>_<随机>/<帧id>/`，出图历史里归为「契约」类型 |
| Web 解析 | `web/src/contracts/analysis.ts`（有单测） | 分词、标记、diff，与后端分词规则一致 |
| Web 页面 | `web/src/pages/AgentStudio.tsx`、`web/src/contracts/*` | 侧栏「Agent 拼接」 |
| 配置 | `contract.root`（默认 `<design_root>/动作改2/contracts`）、`contract.formats_dir`、`contract.runner: manual` | |

提前完成的 P1：历史契约按所选节点筛选（完全 / 部分匹配）、来源过期提示、按帧编辑写回（带 hash 冲突检测）、5 秒轮询与 Shift+刷新先 `git pull`、多角色分角色提示词（§4.4：生图按角色提交；帧卡片按 主→c1→c2 排列并标角色色，角色词写错块时波浪线标出，Diff 合并各角色块对比，编辑时可添加角色块）、结果故事板（契约头部「结果故事板」或帧下方「查看全部」进入，不是单独路由，而是契约页的一个视图：左栏让给故事板，右栏生图面板保留，「生成此帧」可直接用；每帧一行，按「结果目录 + 画风」分轮，可按画风、当前提示词、已采用筛选）、刷新后保留页面状态（左栏请求、生图设置含画风、视图开关、故事板与筛选、每份契约勾选的帧，存在浏览器 localStorage，`web/src/contracts/persist.ts`）。

还没做：
- 「帧 × 画风」对比、「基于此契约新建」。
- 右栏的 Policy Rules 开关：第一期保持与 agent composer 一致的默认跳过，没有放开关。
- 翻译模块仍在 `styleLab/translations.ts`，Agent Studio 直接引用，没有挪到公共目录。
- 一键执行（P2）。

### 12.1 token 计数

规则取自 NovelAI 官网图片页（novelai.net/image）的前端代码：

| 模型 | 分词器 | 上限 | 角色提示词 |
|---|---|---|---|
| V3 及更早（含 Furry V3） | CLIP | 225 | 无 |
| V4、V4.5（Full / Curated） | T5 | 512 | 和主提示词合计 |
| V5 Full（含 Medium） | Qwen 3.5 | 1471 | 和主提示词合计 |
| V5 Curated | Qwen 3.5 | 703 | 和主提示词合计 |

计数前的预处理：
- CLIP：`[]{}` 换成空格，HTML 实体解码两次，合并空白，转小写；不计开始 / 结束符。
- T5：删掉 `[]{}` 和 `1.2::` / `::`；不做 Precompiled 归一化；末尾 +1 结束符。
- Qwen：NFC，字节级 BPE；不删权重记号。

官网的词表文件（`/tokenizer/compressed/*.def`，raw deflate 压缩的 JSON）和公开词表逐项比对过：
CLIP（`openai/clip-vit-large-patch14`）、T5（`google-t5/t5-base`）完全一致；Qwen 3.5（`Qwen/Qwen3.5-0.8B`）的 vocab 和 merges 一致，只差 26 个特殊符。
用 TagsHub 里 794 条真实提示词对比三种分词器，结果和用官网词表算的完全相同。

实现：
- 首次使用时从 Hugging Face 下载公开词表（固定版本），缓存在 `<项目>/cache/tokenizers`，仓库里不放 NovelAI 的文件。
  - `TM_TOKENIZER_DIR` 改缓存目录。
  - `HF_ENDPOINT` 指定镜像，例如 `https://hf-mirror.com`。
  - `TM_TOKENIZER_DOWNLOAD=0` 禁止下载。
- 下载失败或没装 `tokenizers` 时退回估算，`exact: false`，超限只报 warn。
- 契约帧：数 Agent 写的正向提示词。超限报 error；`sdxl-danbooru` 的 profile 设了 `over_limit: warn`，只报 warn。
- 出图前：点「生成所选帧」或「生成此帧」时先逐帧调用 `/compose-preview`，按画风实际用的模型，对拼好画风前后缀和分角色提示词之后的最终文本计数；有帧超限时弹窗列出，确认后才提交（ComfyUI 不检查）。「检查最终长度」按钮只做检查、不提交。
  - 画风模型和契约格式不一致时会提示，例如 `tags.txt` 画风走 `nai-diffusion-3`。
- Custom 页的 Preview 也显示 Tokens。
