---
name: compose-contract-author
description: >-
  为 PromptAtelier 的「Agent 拼接契约」写每一帧的完整提示词：读契约请求和素材（角色、st_/stn_ 动作组、服装、背景），
  按定制要求逐帧拼接，写回契约 Markdown 文件，用 contract check 自检后标记完成。
  在收到「Agent 拼接契约」要求 prompt、或要填写 动作改2/contracts/*.md 时使用。
---

# 写 Agent 拼接契约

设计见 `docs/agent_compose_contract_spec_v1.md`。分工：**提示词全部由你拼接**；来源标记、diff、校验、出图都由 Web 和脚本完成，你不用写结构化标注。

## 命令（在 PromptAtelier 仓库根目录执行）

| 命令 | 作用 |
|---|---|
| `uv run tm-core contract show <id> [--config <应用配置>]` | 请求部分（节点、定制要求、选项）、目标格式摘要、已写的帧 |
| `uv run tm-core contract context <id> [--member N]` | 素材：角色各分区的词、动作组每个成员的正向/负面词、分类（phase/cast/pose…）、`character_scope`、`clothing_state`、服装、背景。成员多时用 `--member N` 一个个取 |
| `uv run tm-core contract check <id>` | 解析 + 校验，输出 issues（JSON）；有 error 时退出码 1 |
| `uv run tm-core contract prompt <id> --kind tools` | 重新输出要求 prompt |
| `uv run tm-core kb search --config <知识库配置> --text <词> [--pose ...]` / `kb show <ref>` | 新增帧时找参考动作；用法见动作库的 `action-kb-search` Skill |

`--config` 默认取 `$TAGS_MACHINE_CONFIG`，再找 `configs/local.yaml`、`configs/cloud.yaml`。契约文件在 `<design_root>/动作改2/contracts/<id>.md`。

## 流程

1. `contract show` 读请求：哪些角色（c1、c2…）、哪个动作组、定制要求、`keep_order` / `allow_new_frames` / `max_new_frames`、目标格式。
2. `contract context` 读素材。动作组按成员顺序给出；`ref` 就是帧的 `source` 要写的值。
3. 在 front matter 之后逐帧书写（下面的格式）。一般一个成员一帧，顺序与动作组一致；要求里需要过渡镜头时再加自定义帧。
4. `contract check` 修到没有 error（warn 看情况处理，确认是有意为之可以保留）。
5. 把 front matter 的 `status: pending` 改为 `status: done`；可以填 `title`（简短中文标题）和 `author`。不要改 front matter 的其他字段。

## 帧格式

````markdown
## f01 推门进教室
source: new/20260930_0101_01_推门进教室
characters: c1
size: portrait

```positive
akemi_homura, mahou_shoujo_madoka_magica,
black_hair, long_hair, purple_eyes,

1girl, solo, opening door, walking, looking at viewer, light smile,
night, classroom, window
```

```negative
red_glasses
```

这里的文字是本帧备注，例如为什么去掉了某些服装词。
````

- 帧 id：`f01`、`f02`…，插入的新帧用 `f02b`。id 用来回挂出图结果，写好后不要改。
- `source`：动作组成员的 `ref`（也接受 `#2` 这种组内序号）；自定义帧写 `custom`，参考过的动作写进 `inspired_by`（逗号分隔）。
- `characters`：本帧出现的角色 id。`size`：可选，`portrait` / `landscape` / `square`，只写方向。
- 多角色、且目标格式支持分角色提示词时，用 ```` ```positive c2 ```` / ```` ```negative c2 ```` 写第二个角色。
- 代码块里可以随意换行、空行分组；提交生图时按格式 profile 把换行当分隔符。

## 原则

- 先理解定制要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 角色身份词（角色名、作品名、发色瞳色等）通常保留；服装、发型、配饰结合动作的 `clothing_state`（裸露状态）、`character_scope`（镜头范围）、构图和要求取舍。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词（如 `white background`、`simple background`）、混进动作里的角色/画风词去掉。
- 尽量沿用素材里的原词写法：Web 按字面匹配给每个词标来源，改了写法会显示成「改写」或「新增」。需要强调时改权重。
- 多角色：只有选了多个角色、且要求说明了分配方式时，才把动作里的人物换成 c2 等；否则保留动作原词。
- 连续性：同一组的服装、场景保持一致，除非要求变化。
- 权重写法按目标格式（`contract show` 的 format 段）：NovelAI 用 `{tag}` / `[tag]` / `1.2::tag::`，SDXL 用 `(tag:1.2)`。
- 不要写：画师名（`artist:xxx`）、质量前缀（`masterpiece`、`best quality` 等，由画风叠加）、生图参数。
- 不要修改素材库里的源节点，不要修改 front matter 的请求部分。

## 校验器（contract check）

`frame_structure`（帧标题、source、positive 齐全，id 不重复）、`weight_syntax`、`bracket_balance`、`token_length`（和 NovelAI 官网同样的分词器和上限，超限是错误）、
`language`（不允许中文的格式里检出 CJK）、`forbidden_tags`、`duplicate_tags`、`tag_conflict`（如 barefoot 与 socks）、
`character_count`（人数 tag 与 characters、动作 cast）、`source_exists`、`coverage`（动作组里没被任何帧用到的成员）。

`contract check` 结果里的 `tokens` 给出每帧正向的 token 数和上限（V4+ 是主提示词加各角色提示词的合计）。出图时画风前后缀和质量词还会再占几十个 token，接近上限的帧要精简。
