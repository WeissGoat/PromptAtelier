---
name: compose-contract-author
description: >-
  用于 PromptAtelier 的 Agent 拼接契约。主 Agent 与用户确认方案后写计划和逐帧提示词，或修改已有契约并安排复核。受派的提示词复核子 Agent 审查词块和前后帧风险。支持按用户指定画风测试或出讨论例图。
---

# 写 Agent 拼接契约

## 选择任务

- **新写契约**。主 Agent 完整阅读[共享编写规范](../../../src/tags_machine_core/compose_contracts/writing_guide.md)，用 `contract show` 读要求，用 `contract context --summary` 看全组，再按 `--members` 分段取素材。与用户确认方案后，交付计划区和逐帧提示词。有状态变化规划时，用下方派单模板安排整组复核。
- **修改已有提示词**。主 Agent 从当前版本、改动要求和相关帧开始，沿用已确认的方案。按[提示词修订与重出流程](../../../src/tags_machine_core/compose_contracts/writing_guide.md#提示词修订与重出流程)安排审词、修补和最终版复核。重出后由图片复核子 Agent 看图，主 Agent 根据文字报告修正仍有问题的帧，再交审词，进入下一轮。
- **受派复核提示词**。直接执行[提示词复核派单模板](../../../src/tags_machine_core/compose_contracts/writing_guide.md#提示词复核派单模板)，只读审查指定版本和帧范围。返回词块依据、前后帧风险和覆盖范围，由主 Agent 裁决。

写或改正式提示词时，先按名称查找 V4.5 的 `nai45-prompt` 或 V5 / V5 Curated 的 `nai5-prompting`，读完入口及其要求的资料再写。查找顺序和契约适配见[写提示词前必读的 Skill](../../../src/tags_machine_core/compose_contracts/writing_guide.md#写提示词前必读的-skill)。出图后看实际图片用 `compose-contract-review`。

## 命令（在 PromptAtelier 仓库根目录执行）

| 命令 | 作用 |
|---|---|
| `uv run tm-core contract show <id> [--summary] [--frames f01-f30] [--config <应用配置>]` | 请求部分（节点、定制要求、选项）、计划区（preamble）、目标格式摘要、已写的帧。`--summary` 每帧只给标题、来源、角色、token 数；`--frames` 只看一段 |
| `uv run tm-core contract context <id> [--summary] [--members 1-20] [--member N]` | 素材：角色各分区的词、动作组每个成员的正向/负面词、分类（phase/cast/pose…）、`character_scope`、`clothing_state`、服装、背景。**先 `--summary` 看全组结构，再 `--members` 分段取提示词**；整组一次取出可能有几十 KB，会被截断 |
| `uv run tm-core contract check <id>` | 解析 + 校验，输出 issues（JSON）；有 error 时退出码 1 |
| `uv run tm-core contract prompt <id> --kind tools` | 重新输出要求 prompt |
| `uv run tm-core contract create --action-group <组> --character <角色> [--character <角色2>] [--requirements <文字> \| --requirements-file <文件>] [--no-keep-order] [--max-new-frames N]` | 新建契约（等同 Web 新建），输出新 id |
| `uv run tm-core contract clone <id> [--requirements …] [--with-frames]` | 基于已有契约新建：复制请求部分，可替换定制要求和选项；`--with-frames` 连帧一起复制，在旧版上改 |
| `uv run tm-core contract artists [--query <搜索词>]` | 列出正在运行的后台的可用画风与 ref，供用户指定 |
| `uv run tm-core contract generate <id> --artist <ref> [--frames f01,f05] [--nt 1] [--dry-run] [--wait]` | 按契约帧出图；草稿可用。预检不花额度；去掉 --dry-run 后提交后台任务，结果带图片路径 |
| `uv run tm-core contract job <任务id> [--wait] [--timeout 600]` | 查出图进度和结果；等待超时任务仍继续，不要重提 |
| `uv run tm-core contract results <id>` / `contract review <id> --sheets` | 出图结果和复核，见 `compose-contract-review` Skill |
| `uv run tm-core kb search --config <知识库配置> --text <词> [--pose ...]` / `kb show <ref>` | 新增帧时找参考动作；用法见动作库的 `action-kb-search` Skill |

`--config` 默认取 `$TAGS_MACHINE_CONFIG`，再找 `configs/local.yaml`、`configs/cloud.yaml`。契约文件在 `<design_root>/动作改2/contracts/<id>.md`。
命令输出统一是 UTF-8 的 JSON（要求 prompt 是 Markdown）；在 PowerShell 里中文乱码时先设 `$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()`。

`artists / generate / job` 使用正在运行的 PromptAtelier 后台，无需浏览器。自动读取 `runtime/dev_web.json`，也可用 `--server http://127.0.0.1:53211` 或 `$PROMPTATELIER_URL` 指定；使用**该后台**的配置和契约目录，不接受 `--config / --root`。其他本地契约命令仍按上面的配置规则。

## 测试与讨论例图

- 生图前先确认用户指定的画风；没有指定就先问，可用 `contract artists --query` 列候选供用户选，不要自行选择。用户在当前沟通里已指定则沿用。
- 用户要试图或沟通方案时，可以先在当前契约里写少量代表帧（保留 `pending`），`contract check` 检查后用 `--frames` 精确选择，不要把示例请求扩大为整份契约批量生图。
- 先 `contract generate <id> --artist <ref> --frames f01,f05 --dry-run` 看最终提示词、模型、尺寸、token；实际提交去掉 `--dry-run`，可加 `--wait`。异步提交返回任务 id，后续用 `contract job <任务id> --wait`。超限先精简，用户接受截断时才加 `--allow-over-limit`。
- 支持 `--size contract|random|portrait|landscape|square|custom`、`--width / --height`、`--nt`、`--seed`、`--negative`、`--character-prompts auto|off`、`--add-male-caption`、`--comfyui-target`。
- 默认跨契约复用相同有效参数的成功图片；随机 seed／随机尺寸也复用第一次结果。需要新的候选时用 `--force`；提示词、画风参数等变了自动重出。失败、图片丢失不会复用。
- 主 Agent 将返回的图片路径交给图片复核子 Agent，按需用 `contract review <id> --sheets` 准备联系表。由子 Agent 看例图，主 Agent 依据审片报告向用户反馈并附图片路径。复核流程见 `compose-contract-review`。

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
- 代码块里可以随意换行、空行分组；提交生图时按格式 profile 把换行当分隔符。

## 多角色

契约选了多个角色（c1、c2…）、目标格式支持分角色提示词（`contract show` 的 format 段）时，画面里有两个及以上角色的帧这样写：

| 代码块 | 写什么 |
|---|---|
| ```` ```positive ```` | 画面共用的部分：人数 tag（`2girls` 等）、互动、构图镜头、背景环境。不写某个角色专属的词 |
| ```` ```positive c1 ```` / ```` ```positive c2 ```` | 这个角色自己的全部内容：性别词（`girl` / `boy`）、身份词（角色名、发色瞳色）、服装，以及动作里属于这个人的部分（姿势、表情、谁对谁做什么） |
| ```` ```negative c1 ```` | 可选，只对这个角色生效的负面词 |

````markdown
## f01 坐在腿上
source: #1
characters: c1, c2

```positive
2girls, yuri, sitting on lap, night, classroom, window
```

```positive c1
girl, akemi_homura, black_hair, long_hair, purple_eyes, sitting behind, hands on another's waist, smile
```

```positive c2
girl, kaname_madoka, pink_hair, twintails, pink_eyes, sitting on lap, open mouth, blush
```
````

- `characters:` 列出的每个角色都要有自己的 ```` ```positive cN ````。
- 动作素材里的行内写法 `::character A: … ::` / `::character B: … ::`：把 A、B 里的词挪进对应的 cN 块，主提示词里删掉这一段，**不要两种写法混用**（混用时行内块会原样提交，`contract check` 报 error）。默认 A→c1、B→c2；定制要求说明了谁做什么时按要求对应。块里原来的角色名、发色等换成该角色自己的身份词。
- 只出现一个角色的帧（单人特写等）可以只写 ```` ```positive ````。
- 出图时：NovelAI V4+ 画风把 cN 块作为角色提示词提交；V3 画风、ComfyUI 画风或关掉 Character Prompts 时，cN 块并进主提示词。

## 校验器（contract check）

`frame_structure`（帧标题、source、positive 齐全，id 不重复）、`weight_syntax`、`bracket_balance`、`token_length`（和 NovelAI 官网同样的分词器和上限，超限是错误）、
`language`（不允许中文的格式里检出 CJK）、`forbidden_tags`、`duplicate_tags`、`tag_conflict`（如 barefoot 与 socks）、
`character_count`（人数 tag 与 characters、动作 cast）、`character_blocks`（角色块齐全、行内块与 cN 块混用、角色词写错块）、
`source_exists`、`coverage`（动作组里没被任何帧用到的成员）、
`identity_anchor`（帧的 characters 里有某角色，提示词里却没有这个角色的任何身份词）、
`frame_novelty`（和上一帧去掉全组共用词后只差一个词或完全相同；换了画幅或出场人物的不算）。

`contract check` 结果里的 `tokens` 给出每帧正向的 token 数和上限（V4+ 是主提示词加各角色提示词的合计）。出图时画风前后缀和质量词还会再占几十个 token，接近上限的帧要精简。
