# Agent 拼接契约（Compose Contract）设计 v1

> 状态：第一期（P0）已实现，部分 P1 一并完成，实现情况见 §12。
> Agent 直接出图、需求例图与跨契约复用见 §12.2。
> UI 原型：https://claude.ai/artifact/3EwBb7NEkrBoeEL9ZSwzuq （主界面、要求 prompt / 导入、按帧编辑、结果故事板、动作组参考）
> 目标：在 Web 现有「脚本式拼接（Custom）」之外，增加「Agent 式拼接」：
> 用户在 Web 选素材节点并写定制要求 → 主 Agent 读素材、讨论方案 → 用户确认 → 写计划与完整帧 → 审词与裁决 → 生图 → 图片复核子 Agent 看图。发现待修问题，主 Agent 依据报告改词，重新走审词、生图和图片复核流程。

## 0. 已确认的决策

| 问题 | 结论 |
|---|---|
| 分工 | 主 Agent 与用户确认方案、写计划和完整提示词、统一修改与裁决；子 Agent 独立复核；脚本负责解析、校验和出图，不生成提示词内容 |
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
| 动作内容读取 | 使用统一 `NodeReader`：有 `tags.txt` 时正负面都从文本读取（正向排除注释、type 和扩展指令；负面解析 uc / origin_uc / after_uc / negative_prompt / after_negative_prompt）；没有文本时才读取 YAML 提示词。meta.yaml 中其余结构化元数据仍保留，tags.compiled.txt 不隐式优先 |
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
   主 Agent 读要求和素材 → 头脑风暴 → 用户确认方案
          │
          ▼
   写计划区与正式帧 → 程序校验
          │
          ▼
   有状态规划：子 Agent 逐帧状态分析 + 整组回看 → 主 Agent 裁决
     ├─ 有仓库和工具：直接编辑契约文件，用 `contract check` 自检
     └─ 纯对话：输出计划区和帧内容 → 用户粘贴到 Web「导入」
          │
          ▼
 Web: 解析（标记着色 + diff）+ 后端校验 → 按帧微调（写回文件）→ 选帧 + 画风 + 参数 → 生图
          │   每帧 = compose request { composer: agent, agent_result, artist 节点 }
          ▼
   现有 generate / job_manager / 出图历史（结果回挂 contract_id + frame_id）
          │
          ▼
   图片复核子 Agent 审新图及相邻帧 → 主 Agent 读报告并裁决
     ├─ 有待修问题 → 主 Agent 改词 → 审词、修补、复核最终版 → 按授权重出 → 回到图片复核
     └─ 本轮问题已处理 → 用户挑图
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

计划区是首帧之前的正文（API 字段 `preamble`），使用 `###` 标题，二级标题 `##` 专用于帧。`contract show`（包括 `--summary` / `--frames`）和 `contract context` 返回完整计划区，Web 提供折叠展示。
导入支持“计划区 + 帧”及旧式仅帧内容：携带计划则一并替换，仅帧则保留已有计划。复核报告和裁决不属于契约正文，应单独交付。计划区不进入提示词或 `prompt_hash`。

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

- 对比对象：本帧最终正向提示词 vs 来源动作 node 的正向词（按 `NodeReader` 优先读取 `tags.txt`；没有文本时回退 YAML）。
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

Web 对 pending 契约生成两种 prompt，提供「复制」按钮。两种 prompt 都要求先讨论方案，用户确认后才开始正式写作；已有明确确认的方案沿用，不能仅凭新建契约或已有计划文本认定已确认：

| 形式 | 内容 | 产物回传 |
|---|---|---|
| **工具版** | 契约文件路径、任务说明、Skill（`compose-contract-author`）、可用命令、完成标准 | agent 在仓库中直接编辑契约文件，`contract check` 自检；Web 轮询到 `status: done` 后刷新 |
| **自包含版** | 内嵌精简后的素材内容（角色分区词表；动作组各成员的正向词、classify 摘要、`clothing.state`、`character_scope`；服装 / 背景）+ 帧格式说明 + 原则 + 目标格式要点 | agent 输出计划区和 §4.2 的帧内容；用户在 Web「导入」中粘贴契约正文，Web 写回文件并校验；有问题时显示校验结果，可以再复制给 agent 修 |

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
| `identity_anchor` | 帧的 `characters` 里有某角色，但提示词（有 cN 块时看 cN 块）里没有这个角色的任何身份词（角色节点的 character / hair / eyes 等分区），特写最常见，出图会换人（warn） |
| `frame_novelty` | 相邻两帧去掉全组共用的词（出现在 60% 以上帧里的身份、服装、场景词）后只差一个词或完全相同（warn）；换了画幅或出场人物的不比较 |

---

## 8. Skill：`compose-contract-author`

放在 `.agents/skills/compose-contract-author/`（同步到 `.claude/skills`）。

### 8.1 工具（`tags_machine_core contract …`）

| 命令 | 作用 |
|---|---|
| `contract create --action-group … --character … [--requirements …]` | 新建契约（同 Web 新建） |
| `contract clone <id> [--requirements …] [--with-frames]` | 基于此契约新建：复制请求部分，可替换要求和选项；`--with-frames` 连帧一起复制 |
| `contract show <id> [--summary] [--frames f01-f30]` | 契约的请求部分、目标格式摘要、已写的帧；`--summary` 不含提示词 |
| `contract context <id> [--summary] [--members 1-20] [--member N]` | 角色分区词表、动作组各成员内容、服装、背景；先 `--summary` 看结构，再分段取，控制上下文长度 |
| `contract check <id>` | 解析 + 校验，输出 issues（JSON） |
| `contract results <id> [--frames] [--artist] [--current-only] [--all]` | 每帧出图状态（有图 / 缺图 / 只有旧图 / 最近一次失败 / 排队）、最新一轮的图、轮次、失败原因 |
| `contract review <id> [--sheets]` | 出图复核：代表图、PNG 元数据检查、连续性校验结果、待办；`--sheets` 生成联系表 |
| `kb facets/search/show` | 已有，新增场景时检索 |

Agent 直接编辑契约文件，不需要额外的写入命令。命令输出统一 UTF-8（设了 `PYTHONIOENCODING` 时按它）。
出图后的复核由单独的 Skill `compose-contract-review` 负责，见 §8.3。

### 8.2 计划、编写与子 Agent 复核

执行规范统一维护在 `src/tags_machine_core/compose_contracts/writing_guide.md`：`compose-contract-author` Skill 要求先读该文件，Web 的工具版和自包含版 prompt 直接嵌入同一份内容。

- 正式写提示词前按名称查找已有 Skill：V4.5 使用 `nai45-prompt`，V5 / V5 Curated 使用 `nai5-prompting`。先查当前可用技能列表，未列出再搜索项目及环境提供的技能位置，不写死安装路径；找不到或无法读取时再向用户反馈。完整阅读入口及其要求的参考资料后再写词，已读且适用的内容可沿用，不把简介当作已阅读。契约仍保留本项目帧格式及画风 / renderer 的参数职责。
- 主 Agent 读用户要求与素材，先在对话中讨论创作方案：理解、整体走向、编号阶段、重要状态与素材使用；有实质分歧再提供选项及推荐。用户确认后开始正式写作，已有明确确认且适用的方案直接沿用。
- 确认后的方案在首帧之前写成自然语言计划区：`### 用户自定义要求`（引用原文，无要求则写“无”）、`### 全局要求`、`### 阶段安排`（1、2、3 等序号）。
- 按需增加 `### 状态变化规划`，例如：服装、表情、道具、背景等。维度开放，不强制固定栏目，不要求指定变化在哪一帧；简单任务可简写，不额外编造剧情。
- 两份派单都要求先假设材料有缺陷，再用当前词块或原图核验最可疑的细节。主 Agent 将全篇没有实质性疑点的报告判为无效并退回。疑点全部排除时，报告给出具体疑点、排除依据和已查范围。严禁用空洞赞美或鉴赏性打分代替检查。
- 逐帧最小红线清单为【机位与视线穿帮排查】【道具与环境连续性排查】【用户负面禁令排查】【姿势物理逻辑排查】，详细定义统一维护在共享规范中。每项记录核实结果及事实，待核实或不适用说明原因；原文中的有效用户禁令需逐条核对，明确违禁列为阻断项，不因禁用词出现在 negative 块而误判。提示词检查不能替代实际看图。主 Agent 验收四项逐帧覆盖，漏项或只打勾退回补查；这不新增契约必填字段。
- 有状态变化规划时，主 Agent 完成提示词后安排独立子 Agent 复核。子 Agent 读取原始要求、计划、最终正负提示词及备注，逐帧列出相关状态、提示词依据、前后变化和分析；即使无问题也要列出该帧，不抽样或只报异常。
- 从提示词提取实际表达，区分明确描写、镜头外、未明确和上下文推断。具体表情允许符合基调的变化，背景按镜头裁剪取舍。
- 逐帧表之后再按计划维度纵向回看整组，检查远距离状态回退、阶段转折与分段交界，汇总发现及依据。
- 子 Agent 只标记疑点，主 Agent 逐项决定修改、保留并解释或澄清计划，再复核受影响的帧与衔接；合理保留是有效裁决，不强求疑点数量清零。完整逐帧报告、整组回看和裁决在对话或单独报告中交付，不附在最后一帧之后。
- 普通措辞、构图和局部修正由主 Agent 按已确认方案处理；改变已确认剧情方向、重要状态走向或用户要求时，先讨论并确认方案调整。用户要求的少量讨论例图可按草稿处理，不扩大为整组正式写作。
- 主 Agent 从共享规范复制对应的提示词复核或图片复核派单模板，填入版本、范围和可访问的材料。两份模板各自包含四项红线与交付说明。修订后沿用相应模板，附上轮问题和本轮改动。两类子 Agent 只读，主 Agent 按角色验收证据、补查遗漏和交界并裁决。切换角色时旧报告只作线索。
- 提示词修订的常规流程是主 Agent 改词、提示词复核子 Agent 审查、主 Agent 修补、子 Agent 复核最终版，通过后生图，再由图片复核子 Agent 看图。主 Agent 默认按文字报告裁决，证据不足时派回补看。有待修正的画面问题时，依据问题编号和帧号回到改词步骤，新图仍交图片复核子 Agent 核实。按改动影响决定复核范围，试图或环境受限时说明实际完成的检查。
- 工具校验无 error、warn 已审阅，且适用的独立复核和主 Agent 裁决完成后，再标记 `done`。无子 Agent 能力时明确披露、保留草稿，不把自检冒充独立复核。Web 导入标记 `done` 不代表语义复核已完成。
- 此规范不新增状态机、强制字段或自动语义拦截。当前 Web 仍手动复制 prompt 交接，不自动启动、调度或管理子 Agent。出图后的图片复核使用 §8.3 的 Skill。

### 8.3 Skill：`compose-contract-review`

出图后的复核，放在 `.agents/skills/compose-contract-review/`。`contract review --sheets` 输出：

- 每帧状态和代表图（已采用 > 当前提示词 > 其他）；失败原因来自 Web 出图任务记录 `<output_dir>/.web/jobs`；
- `audit`：读 PNG 元数据，列出每个画风实际用的模型、步数、CFG、采样器、尺寸；画幅与帧 `size` 不符、正负面词打架、成人契约的负面词里有 `nsfw`、分角色块没生效时报出；
- `prompt_issues`：`identity_anchor`、`frame_novelty` 等校验结果；`todo`：汇总成待办；
- 联系表写到 `<output_dir>/.contract_review/<id>/`：`overview_NN.jpg`（每帧代表图，看故事线）、`frames_NN.jpg`（每帧全部候选）。

主 Agent 准备用户要求、已确认计划、对应最终提示词、图片路径和结果信息，指定版本、画风、轮次与帧范围，委派独立、具备看图能力的子 Agent。子 Agent 实际看联系表与可疑帧及前后帧原图，检查人物、状态、情绪和镜头衔接，返回逐帧结论、候选建议、依据和覆盖范围；不能用提示词或工具输出冒充视觉检查。

看图检查同时覆盖计划符合性和实际画面自身的连续性，不局限于主 Agent 已规划的维度，没有状态规划时也适用。子 Agent 从图片提取姿势、位置、朝向和人物与物体关系等实际可见状态，发现站坐反复、位置无依据跳变等生成不稳定问题；逐帧报告区分画面事实、计划 / 提示词预期和不确定项，疑点提供前后帧及图片路径。整组回看也覆盖看图发现的重要维度。合理动作或机位变化不是错误；裁剪看不到的内容不推断为已改变，必要时看原图与相邻帧核实。

背景检查兼顾前后连贯性和对当前构图、裁剪的影响：核对主要陈设与人物的空间关系是否合理，识别不服务本帧焦点却抢占画面、遮挡主体或拉远景别的背景元素。合理的出画、虚化和省略可以保留，不要求重复完整背景。子 Agent 提供具体元素和视觉依据，主 Agent 决定精简提示词、调整构图、换候选或重出。

图片复核的问题记录必须可追溯：id、严重程度和证据状态、相关帧与图片路径及局部、观察事实和前后对照、对目标或连续性的影响、处理建议及不确定项。子 Agent 打开可疑帧及前后帧原图核实；逐帧表不能用一列“优秀 / 正常”代替事实。主 Agent 对只有赞美、剧情复述或缺少定位依据的报告退回补查，不计为质检完成；保留某项必须回应实际证据，不能事后改计划为缺陷开脱。

主 Agent 汇总裁决，统一执行授权范围内的提示词修正及重出（见 §12.2），用户最终选择采用。区分提示词问题、个别候选不佳、生成失败和旧图。重出后由图片复核子 Agent 检查新图及衔接。无可用看图子 Agent 时标明待视觉复核。用户指定或确需主 Agent 查看某个局部时，注明自检帧号与依据。

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
| 校验器 | `compose_contracts/validators.py` | §7 的 11 个全部实现，另加 `character_blocks`（§4.4）、`identity_anchor`、`frame_novelty`；`token_length` 用真实分词器，见 §12.1 |
| token 计数 | `src/tags_machine_core/prompt_tokens.py` | 契约帧、`contract check` 的 `tokens`、`/compose-preview` 的 `token_usage` 共用 |
| 要求 prompt | `compose_contracts/prompts.py` | 工具版 / 自包含版 |
| CLI | `tm-core contract create / clone / show / context / check / prompt / results / review` | `check` 有 error 时退出码 1；分段读取 `--frames` / `--members` / `--summary` 在 `compose_contracts/selection.py` |
| 出图复核 | `compose_contracts/review.py` | `results`、`review`、PNG 元数据检查、联系表（Pillow，优先用系统中文字体） |
| Skill | `.agents/skills/compose-contract-author/`、`compose-contract-review/`（`.claude/skills` 指向它们） | |
| API | `web/routes/contracts.py` | §10 全部接口；另有 `GET /contracts/action-groups`、`/contracts/action-groups/detail`、`PUT /contracts/{id}/fields` |
| 生图追溯 | `services/json_api.py`、`renderers/common.py`、`renderers/novelai.py`、`execution.py` | compose 请求的 `contract` → `PromptBundle.meta.extra.contract` → render meta → PNG `tags_machine_core.contract` |
| 结果与采用 | `ContractService.results / update_picks` | 契约批次输出到 `outputs/compares/contract_<时间>_<随机>/<帧id>/`，出图历史里归为「契约」类型 |
| Web 解析 | `web/src/contracts/analysis.ts`（有单测） | 分词、标记、diff，与后端分词规则一致 |
| Web 页面 | `web/src/pages/AgentStudio.tsx`、`web/src/contracts/*` | 侧栏「Agent 拼接」 |
| 配置 | `contract.root`（默认 `<design_root>/动作改2/contracts`）、`contract.formats_dir`、`contract.runner: manual` | |

提前完成的 P1：历史契约按所选节点筛选（完全 / 部分匹配）、来源过期提示、按帧编辑写回（带 hash 冲突检测）、5 秒轮询与 Shift+刷新先 `git pull`、多角色分角色提示词（§4.4：生图按角色提交；帧卡片按 主→c1→c2 排列并标角色色，角色词写错块时波浪线标出，Diff 合并各角色块对比，编辑时可添加角色块）、结果故事板（契约头部「结果故事板」或帧下方「查看全部」进入，不是单独路由，而是契约页的一个视图：左栏让给故事板，右栏生图面板保留，「生成此帧」可直接用；每帧一行，按「结果目录 + 画风」分轮，可按画风、当前提示词、已采用筛选）、刷新后保留页面状态（左栏请求、生图设置含画风、视图开关、故事板与筛选、每份契约勾选的帧，存在浏览器 localStorage，`web/src/contracts/persist.ts`）。

Agent 侧（CLI + Skill）另外补了：`contract create / clone`（「基于此契约新建」目前只有 CLI，Web 还没有按钮）、分段读取、出图结果与复核、联系表，以及要求 prompt 里的「先规划」和状态链原则。

还没做：
- 「帧 × 画风」对比；Web 上的「基于此契约新建」按钮（后端 `ContractService.clone` 已有）。
- 让 Agent 通过 CLI 重出失败帧（`retry-failed`）：会花额度，和一键执行（P2）一起考虑。
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

### 12.2 Agent 出图与跨契约复用

- `contract artists [--query …]` 列出后台可用画风；Agent 生图前先询问用户指定画风，已有指定则沿用。画风不写进契约请求。
- `contract generate <id> --artist <ref> [--frames f01,f05] [--nt 1] [--seed 42] [--dry-run] [--wait]`：新接口 `POST /api/contracts/{id}/generate`，解析契约、检查所选帧、按画风拼最终请求并检查 token；实际生成复用 Web 的持久后台任务。`pending` 草稿也能指定少量帧出需求例图。
- `--dry-run` 返回最终提示词、参数和 token，不调用生图后端。随机值在预检时只作示意，实际生成时重新抽取。超限需精简，或明确 `--allow-over-limit`。
- `contract job <任务id> [--wait] [--timeout 600]`：返回状态与图片路径；超时返回非零退出码，任务继续在后台运行，不重复提交。部分失败也返回非零退出码。
- 以上远程命令自动读 `runtime/dev_web.json` 的后台端口；可用 `--server` 或环境变量 `PROMPTATELIER_URL` 指定。使用该后台的应用配置和契约目录，不使用本地命令的 `--config / --root`。
- Python 适配在 `compose_contracts/generation.py`，CLI 客户端在 `generation_client.py`。Web 现有帧请求和 Agent 请求都经过 `run_generate_batch`，不另建生图执行器。
- Web Agent 拼接页默认勾选「跳过相同参数」，请求字段为 `generate.skip_duplicates`；Agent 对应 `--force` 可强制生成新候选。契约批量请求未传字段时也默认复用；其他工作区保持原有行为，可显式启用该字段。
- 复用键取渲染后的正负面词、角色提示词、模型、采样器、步数、CFG、张数、尺寸、seed、画风有效配置、ComfyUI 工作流与运行位置等；排除契约 id、帧 id、标题、输出目录和追踪元数据。随机 seed／随机尺寸按相同随机设置复用首轮结果；强制生成可重新抽取。
- 成功结果索引存在 `<output>/.web/generation_cache/`，重启保留；单个后台进程内同参数并发提交按键串行，后到的复用先完成的结果。失败、空结果、不足请求张数或图片丢失不写成功缓存。上线前没有索引的旧图不猜测匹配，首次仍生成并建立索引。
- 复用保留原 PNG，在新任务帧目录写 `generation.reuse.json` 关联当前 `contract_id / frame_id / prompt_hash`；故事板、results、review、采用均能读到图片，原契约的 PNG 元数据不改。后台任务项 `cache_hit` 标记复用，任务面板显示复用项数。
