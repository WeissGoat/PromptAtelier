---
name: compose-contract-author
description: >-
  为 PromptAtelier 的「Agent 拼接契约」写每一帧的完整提示词：读契约请求和素材（角色、st_/stn_ 动作组、服装、背景），
  按定制要求逐帧拼接，写回契约 Markdown 文件，自检；可按用户指定画风测试或在讨论需求时出例图。
  在收到「Agent 拼接契约」要求 prompt、填写 动作改2/contracts/*.md、或讨论契约并需要试图时使用。
---

# 写 Agent 拼接契约

设计见 `docs/agent_compose_contract_spec_v1.md`。分工：**提示词全部由你拼接**；来源标记、diff、校验、出图都由 Web 和脚本完成，你不用写结构化标注。

## 命令（在 PromptAtelier 仓库根目录执行）

| 命令 | 作用 |
|---|---|
| `uv run tm-core contract show <id> [--summary] [--frames f01-f30] [--config <应用配置>]` | 请求部分（节点、定制要求、选项）、目标格式摘要、已写的帧。`--summary` 每帧只给标题、来源、角色、token 数；`--frames` 只看一段 |
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
- 打开返回的图片，或 `contract review <id> --sheets` 看联系表，结合实际图片反馈；给用户展示例图时附图片路径。复核流程见 `compose-contract-review`。

## 流程

1. `contract show` 读请求：哪些角色（c1、c2…）、哪个动作组、定制要求、`keep_order` / `allow_new_frames` / `max_new_frames`、目标格式。
2. `contract context --summary` 看全组结构，再 `--members` 分段读素材。动作组按成员顺序给出；`ref` 就是帧的 `source` 要写的值。
3. **定制要求为空**：一个成员一帧，顺序与动作组一致，逐帧把角色拼进去。
   **定制要求里有叙事或状态变化**：先规划（下一节），再写帧。
4. 在 front matter 之后逐帧书写（下面的格式）。
5. `contract check` 修到没有 error。warn 逐条看：`identity_anchor`、`frame_novelty` 基本都要改；确认是有意为之的在帧备注里说明。
6. 把 front matter 的 `status: pending` 改为 `status: done`；可以填 `title`（简短中文标题）和 `author`。不要改 front matter 的其他字段。

## 先规划（定制要求里有叙事或状态变化时）

动作组通常只是一堆动作片段，不是现成的分镜。先把它当素材池：

1. 从定制要求里提取：全局硬要求；叙事起点、终点和必须出现的转折；需要保持或按阶段变化的状态；明确不要的表现。
2. 把状态拆成独立维度：时间与场景、角色身份与外观锚点、服装阶段、姿势与空间位置、表情与情绪阶段、道具与身体痕迹（口塞、绳索、武器、体液等）、出场人物与关系、镜头 / POV。
3. 先定镜头计划再写帧：按叙事阶段给成员分组（`--summary` 里的 phase / pose / cast），合并重复或功能相同的成员；
   `keep_order: false` 时按叙事重排，`true` 时保持原顺序；状态变化没有自然承载帧时加过渡帧（`source: custom`，受 `max_new_frames` 限制）。
4. 计划可以写在第一帧之前的说明文字里（不是帧，不会提交生图）。有意合并或舍弃的成员，`coverage` 会给 warn，在相关帧备注里说明即可。

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

## 原则

- 先理解定制要求，区分全局改动（背景、服装、语气）和逐帧改动。
- 服装、发型、配饰结合动作的 `clothing_state`（裸露状态）、`character_scope`（镜头范围）、构图和要求取舍。
- **身份锚点**：帧里出现的角色，至少保留角色名或发色瞳色之一；特写、局部镜头也一样，再加一个当前服装、道具或标志物。删光身份词出图会换人（`identity_anchor` 会报）。
- **构图的身份词**：背影、背面特写、头部出画的帧不要写 `purple_eyes`、`empty eyes` 这类必须露脸才能体现的词，否则模型会把头转回来；用发色、发饰、服装、道具做锚点。
- **来源冲突**：动作素材里的状态词（`standing` / `lying`、`clothed` / `nude`、`gagged`、`bound` 等）只在和本帧状态一致时保留；定制要求和状态推进优先于素材原词。
- 动作的核心（姿势、构图、表情、互动）优先保留；与要求冲突的环境词（如 `white background`、`simple background`）、混进动作里的角色/画风词去掉。
- 尽量沿用素材里的原词写法：Web 按字面匹配给每个词标来源，改了写法会显示成「改写」或「新增」。需要强调时改权重。
- 多角色：按上面「多角色」一节分块写；人物怎么对应以定制要求为准。
- **连续性是一条状态链**：时间与场景、服装阶段、姿势与位置、道具与身体痕迹、出场人物与关系、镜头 / POV 都要前后衔接。
  进入新状态后不要无故回退（衣服不会自己穿回去，绑住的手不会自己松开）；状态变化要在画面里看得出原因。
- **相邻帧至少改变一项**：机位、景别、姿势、表情、互动、服装状态、道具状态。只换 seed 的重复帧合并或删掉（`frame_novelty` 会报）。
- 写完后按帧顺序复查一遍：服装、姿势与位置、道具、人数与关系、POV 与镜头方向有没有跳变或回退。
- 权重写法按目标格式（`contract show` 的 format 段）：NovelAI 用 `{tag}` / `[tag]` / `1.2::tag::`，SDXL 用 `(tag:1.2)`。
- 不要写：画师名（`artist:xxx`）、质量前缀（`masterpiece`、`best quality` 等，由画风叠加）、生图参数。
- 不要修改素材库里的源节点，不要修改 front matter 的请求部分。

## 校验器（contract check）

`frame_structure`（帧标题、source、positive 齐全，id 不重复）、`weight_syntax`、`bracket_balance`、`token_length`（和 NovelAI 官网同样的分词器和上限，超限是错误）、
`language`（不允许中文的格式里检出 CJK）、`forbidden_tags`、`duplicate_tags`、`tag_conflict`（如 barefoot 与 socks）、
`character_count`（人数 tag 与 characters、动作 cast）、`character_blocks`（角色块齐全、行内块与 cN 块混用、角色词写错块）、
`source_exists`、`coverage`（动作组里没被任何帧用到的成员）、
`identity_anchor`（帧的 characters 里有某角色，提示词里却没有这个角色的任何身份词）、
`frame_novelty`（和上一帧去掉全组共用词后只差一个词或完全相同；换了画幅或出场人物的不算）。

`contract check` 结果里的 `tokens` 给出每帧正向的 token 数和上限（V4+ 是主提示词加各角色提示词的合计）。出图时画风前后缀和质量词还会再占几十个 token，接近上限的帧要精简。
