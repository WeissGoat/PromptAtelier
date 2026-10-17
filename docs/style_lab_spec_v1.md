# Style Lab 规格 v1

Style Lab 是 PromptAtelier 里的画风复刻工作台，用来替代 `artist-style-reproduction` skill 里由 agent 手工完成的流程：

```text
读入语料 -> 原参重生检查链路 -> 分组 -> 划分并锁定画风 -> 编辑主体测试 -> 导出 artist -> 用导出的 artist 测试
```

## 分期

| 阶段 | 内容 |
| --- | --- |
| P1 | 工作区、图片索引、元数据面板、原参重生与对照、出图设置、LLM 客户端与缓存、翻译接口 |
| P2 | 无损分词器、自动分组、配方编辑器（划分、锁定、来源记录、角色提示词区）、素材卡片、翻译词典 |
| P3 | artist 导出器、回归对照、泛化矩阵（显式角色提示词已在 P2 随渲染器完成） |
| P4 | 替换角色、消融测试、配方版本历史（已完成）；视觉差异诊断（未做） |

本文档详细描述 P1；P2 以后的部分只记录已经确定的约束。

## 工作区

### 位置

- 选择文件夹时，工作区数据放在 `<文件夹>/.stylelab/`。
- 文件夹下存在 `origin/` 时，默认只扫描 `origin/`（`artist_parse/YYYYMMDD/<author>/` 的标准结构），不扫描 `group/`、`repro_tests/` 等副本目录。
- 扫描跟随 junction（`origin/<post>` 通常是指向外部图库的 junction），但 Style Lab 不向 `origin/` 写任何文件。
- 选择一组零散图片时，工作区数据放在 `runtime/stylelab/workspaces/<id>/`。
- 所有打开过的工作区登记在 `runtime/stylelab/registry.json`，方便从界面重新打开。

### 目录结构

```text
.stylelab/
  workspace.json        # 工作区设置：来源、扫描规则、创建时间
  index.json            # 图片索引（元数据摘要），按 path + size + mtime_ns 判断失效
  runs/
    <run_id>/
      run.json          # 一次出图：来源图片、设置、render_request、状态、结果、对照
      *.png             # 生成的图片
```

### 图片记录

每张图片的 `id` 是工作区内相对路径的 sha1 前 12 位，路径不变则 id 稳定。

| 字段 | 含义 |
| --- | --- |
| `path` / `rel_path` | 绝对路径 / 相对工作区来源的路径 |
| `post` | 从投稿目录名 `YYYY-MM-DD_<post_id>_<title>` 解析出的日期、投稿号、标题；解析不到为 `null` |
| `prompt` / `negative_prompt` | v4 `base_caption` 优先，回退到 `prompt` / `uc` |
| `char_captions` | v4 角色提示词（正向 + 负向 + 位置），全部条目 |
| `model` | 归一化后的模型名，来自 `Source` 文本块 |
| `seed` `steps` `scale` `sampler` `cfg_rescale` `noise_schedule` | 主要参数 |
| `width` / `height` | 原图画布尺寸 |
| `request_type` | `PromptGenerateRequest` / img2img / infill 等 |
| `vibe` | 内嵌 vibe 的数量、每张的短 hash、强度、信息提取度 |
| `flags` | `no_metadata`、`inpaint`、`img2img`、`vibe_missing`（有 vibe 参数但没有内嵌图）、`director_ref` |

隐水印元数据恢复会写回原图，P1 只把这类图片标成 `no_metadata`，不自动恢复。

## 原参重生

用源图的完整参数重新生成，验证 NovelAI 客户端 -> gateway 这条链路，不经过 Composer。

- render_request 由后端从源图元数据组装：prompt、negative、v4 caption（含 char_captions）、全部原始参数，`meta.source_image_path` 指向源图，由 `execution._hydrate_reference_images` 补回 vibe。
- inpaint / img2img 缺少底图，不能完全复现；界面要提示，但仍允许运行。

### 出图设置

| 设置 | 选项 |
| --- | --- |
| 张数 | 1–8，逐张串行提交，每张 `n_samples=1`，避免 429 |
| 种子 | `source`：原图种子（多张时依次 +1）；`random`；`fixed`：指定值（多张时依次 +1） |
| 尺寸 | `source`：原图尺寸；`custom`：指定宽高；`random`：每张从竖、横、方标准尺寸（832×1216、1216×832、1024×1024）里随机抽；`loop`：按竖、横、方依次轮换。配方出图同样适用 |
| 参数覆盖 | model、steps、scale、cfg_rescale、sampler、noise_schedule；不填则沿用原图 |

### 对照

每张生成图完成后计算：

- 参数差异：`compare_render_parameters`，同时给出忽略宽高的结果。
- 图像相似度：两图缩放到同一尺寸后的灰度平均差（0–1，1 为完全相同）和 dHash 汉明距离。
- 结论分三档：参数一致且相似度 ≥ 0.98 为 `match`（链路是确定性的，同参数重生应接近逐像素一致），参数一致但相似度低为 `drift`，参数不一致为 `param_diff`。

## LLM

所有 LLM 功能通过 OpenAI 兼容接口调用（当前是自建 CLIProxyAPI），都是可选增强：未配置或调用失败时，页面其他功能照常可用。

### 配置

```yaml
llm:
  base_url: "https://<server>/v1"
  api_key: null              # 三选一：直接写、环境变量、密钥文件
  api_key_env: "TAGS_MACHINE_LLM_API_KEY"
  api_key_file: null         # 纯文本，或 JSON 文件（读取 api_key_field 字段）
  api_key_field: "OPENAI_API_KEY"
  models:
    text: "deepseek-4.1-flash"          # 主力，NSFW 内容也能处理，但慢（单次 15–60 秒）
    fast: "gemini-3.5-flash-lite"       # 短任务先试，约 1 秒；拒答 NSFW 时很快失败
    fallback: "gemini-3.8-flash-high"
    vision: "gemini-3.8-flash-high"     # 已确认代理能传图
  timeout: 90
  cache_path: "runtime/llm_cache.sqlite"
```

### 客户端约定

- 兼容两种响应外形：标准 `{"choices": [...]}`，以及代理包了一层的 `{"data": {"choices": [...]}}`。
- 要求 JSON 输出的任务会去掉 markdown 代码块围栏再解析，解析后用 pydantic 校验。
- 模型链：普通任务 `text -> fallback`；短任务（翻译）`fast -> text -> fallback`；看图任务只用 `vision`。
- 某个模型失败（HTTP 错误、空内容、没有 choices、JSON 不合法、拒答）就试下一个，全部失败抛出 `LLMError`。
- 实测：Gemini 对含 NSFW tag 的请求直接返回空 choices；DeepSeek 能正常处理但慢，所以翻译用小批并发。
- 缓存键为 `任务名 + 任务版本 + 输入 hash`，存在 sqlite，同一输入的结果保持稳定。

### 翻译

- 输入 tag 列表，输出 `{tag: 中文}`。查询前去掉权重符号（`{}`、`[]`、`1.2::x::`），`{{official art}}` 和 `official art` 共用一条翻译。
- 每个 tag 单独缓存（与模型无关），先查缓存，只把未命中的按每批 40 个、最多 4 批并发发给 LLM。
- 打开或重扫工作区后，后台分析任务把全部提示词、负面和角色提示词的 token 翻译进缓存，并给正向 tag 分类（见 P2）。
- 画师名标为"画师"，不翻译（P2 接入画师名单后生效，P1 由 LLM 判断）。

## Web API（P1）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/style-lab/workspaces` | 已登记的工作区 |
| POST | `/api/style-lab/workspaces` | 打开或创建：`{"root": "<文件夹>"}` 或 `{"files": [...], "name": "..."}` |
| DELETE | `/api/style-lab/workspaces/{id}` | 删除工作区：图片组数据移到 `runtime/stylelab/trash/`，文件夹工作区只从列表去掉；有未完成的出图时 409 |
| PUT | `/api/style-lab/workspaces/{id}/name` | 改工作区名称：`{"name"}`，空白合并，1~80 字 |
| GET | `/api/style-lab/workspaces/{id}` | 工作区设置 + 图片记录列表 |
| POST | `/api/style-lab/workspaces/{id}/scan` | 增量重扫 |
| POST | `/api/style-lab/workspaces/{id}/upload` | 图片组工作区上传图片（multipart `files`） |
| POST | `/api/style-lab/workspaces/{id}/images/remove` | `{"image_ids": [...]}` 从工作区移除：uploads 里的副本删掉；其余记进工作区的 `excluded`，扫描时跳过，原文件不动 |
| POST | `/api/style-lab/workspaces/{id}/images/restore` | 清空 `excluded`，移除过的原图重新出现 |
| POST | `/api/style-lab/workspaces/{id}/analyze` | 后台分析（翻译 + tag 分类），返回 job_id；打开、重扫、上传后自动触发 |
| GET | `/api/style-lab/workspaces/{id}/analysis` | tag 类别和自动分组（只读缓存，不调用 LLM） |
| GET | `/api/style-lab/workspaces/{id}/images/{image_id}` | 单张图片完整元数据（含原始参数，vibe 图片数据截断） |
| GET | `/api/style-lab/workspaces/{id}/file` | 读取图片：`image_id` 或 `path`（只允许工作区图片和 runs 目录），`size>0` 返回缩略图 |
| POST | `/api/style-lab/workspaces/{id}/regenerate` | 原参重生：`{"image_id": "...", "settings": {...}}`，返回 run 记录（含 job_id） |
| GET | `/api/style-lab/workspaces/{id}/runs` | run 列表，可按 `image_id` 过滤 |
| GET | `/api/style-lab/workspaces/{id}/runs/{run_id}` | 单个 run，含每张结果的对照 |
| GET | `/api/style-lab/llm/status` | LLM 是否已配置、模型名 |
| POST | `/api/style-lab/translate` | `{"texts": [...], "provider": "google" \| "llm"}` -> `{"translations": {...}}`；`google` 走谷歌翻译免费接口（不需要 LLM，中文日文不翻），`llm` 是 AI 翻译（默认） |

## P2：分词、分组、配方编辑

### 无损分词

后端 `style_lab/tokens.py` 和前端 `web/src/styleLab/tokens.ts` 是同一套规则，共用 `tests/fixtures/prompt_tokens.json`：

- 按逗号（含全角）、竖线、换行切开；
- 成对的 `{}` `[]` `()` 内部不切，`artist:[[a, b]]` 是一个 token；没配对的括号当普通字符；
- `1.2::a, b::` 权重组整体是一个 token，支持嵌套（`数字::` 开、单独的 `::` 关）；没闭合的权重不成组；
- 每个 token 记住前面的原始分隔符，原样拼回去逐字节相同。用 artist_parse 下 4002 段真实提示词验证过往返无差异。
- `inner_tags` 把权重组、括号组拆成普通 tag（去掉权重、`artist:` 前缀、SD 风格的 `:0.5`），用于统计、分类和翻译。

### tag 分类

- 类别：画风侧 `artist` `style` `quality` `meta`；内容侧 `count` `character` `appearance` `clothing` `action` `expression` `scene` `camera` `nsfw`；以及 `other`。
- 规则先处理确定的（人数、质量词、年份、`no text` 等），其余用 LLM（`fast -> text -> fallback`），按 tag 缓存。
- token 的类别：`artist:` 前缀算画师；组里有画师算画师；否则取多数。

### 自动分组

一个投稿算一个单位：

1. 每个投稿的签名 = 画师 tag 集合（没有画师 tag 时用风格 tag）。
2. 按签名 Jaccard 相似度 >= 0.5 聚成画风家族。
3. 家族内按"相对共有基础栈多出的 tag"拆稳定变体：至少 max(2, 10%) 个投稿才单独成组，零星变化并到最接近的变体。
4. 再按 vibe 状态（`no_vibe` / `vibe_<hash>` / `missing`）和模型细分。

实测 105845157 的 50 个投稿：一个家族，拆成"基础栈 28"和"+azuuru 22"，和已有的 `Crisp_Manga_Ink` / `Azuuru_Manga_Ink` 两个预设一致。

左栏也可以改为按投稿、按月份分组：在前端按图片的投稿信息计算（`post.dir_name`、`post.date` 的年月），只在工作区里有投稿信息时显示，选中后网格和共性分析都只看这些图。

### 配方

配方存在 `.stylelab/recipes/<id>.json`，旧版本在 `<id>.history/v<n>.json`。画风（`style_signature`：前缀、后缀、负面的文本，模型，参数，`use_source_vibe`，flags）变了保存时版本号加一；只改主体、角色提示词、素材、名字、备注等时原地覆盖，版本号不变。保存时带 `base_version`，版本不一致返回 409；原地保存不加版本号，所以请求里的 `updated_at` 和当前的不一致时也返回 409。

| 字段 | 含义 |
| --- | --- |
| `stage` | `split`（划分中）/ `edit`（已锁定画风，编辑主体） |
| `locked` | 锁定时画风区不能改文字、不能回到划分；主动移入移出 token 始终允许 |
| `prefix` / `suffix` | 画风，导出到 tags.txt 第 1、3 行 |
| `subject` / `character` | 只用于测试出图；`character.captions` 是各条角色提示词的正向、负向和位置（`center`），`character.use_coords` 对应原图的 `v4_prompt.use_coords`。旧配方的单条 `character.tokens` / `negative` 读入时自动转成 `captions` |
| `dropped` | 不进提示词的 token |
| `negative` | 画风负面，导出为 `origin_uc` |
| `model` / `params` | 画风参数（导出到 `gen_json`，不含宽高、种子、张数） |
| `use_source_vibe` | 出图时带上原图内嵌的 vibe 图 |
| `flags` | 默认带 `not_quailty_prompts`，避免 legacy 画风自动追加项目质量词 |

配方里的一个 token 是一块：一整组提示词，原样拼进提示词，不按 tag 分词（新建配方时原图整段是主体里的一块，每条角色提示词也是一块）。只有用户点 `按 tag 拆开` 时才分词；`合并成一块` 把同一处的几块按原分隔符拼起来。

每块记录来源：`source`、`character:<ref>`、`action:<ref>`、`manual`。素材按来源整块加入或移除，筛 tag 时重写那一块；不和主体里已有的 tag 去重。改过文字的原图块记为 `manual`（重新划分时不当成原文）。旧配方里按 tag 存的素材 token 仍能按来源移除，重写时合成一块。

替换角色探针按 tag 判断去留：先把主体和角色提示词里的块拆成 tag（拼回去文字不变），再去掉角色名、外貌、服装。

### 划分

- 在原文上按字符标记范围，只去掉两头的空格和逗号。每段标记各自成块，相邻的不合并。
- 锁定时每段写成一块（文本就是原文，去掉两头的逗号空格，不分词）：前缀、后缀、丢弃里每段标记一块，两段标记之间没标的主体也各一块。同一区的两段之间只隔着分隔符时沿用原文的分隔符。`按 tag 拆开` 时选区里的每个 token 各标一段；`采用建议` 把连着的同区 token 标成一段。
- 重新划分时，token 先在原文的词边界上找位置，找不到再认任意位置（按字符切出的块可能紧贴着别的字）。
- 热力图用整个工作区的投稿级出现率（一个投稿算一次），和划分建议用的同组出现率不同。显示为每个 tag 上沿的橙色条，不盖住区的底色。

### 划分建议

- 画风类 tag：画师总是画风，其余同组出现率 >= 50% 才算；
- 同组出现率 >= 80% 的场景、其他类 tag 算画风调味；
- 高频的镜头、外貌、作品/角色名标为"待判断"（如 `shallow depth of field` 是画风，`face focus` 是内容），不自动划分；
- 人数、服装、动作、表情、NSFW 永远是主体；
- 画风 token 后面的主体 token 比前面多就进前缀，否则进后缀。

### 预览与出图

配方拼成一个和导出后读回来完全一致的 legacy artist 节点（`prompt_prefix` / `prompt_suffix` / `negative_prompt` / `params` / `flags`），主体作为完整提示词，走正式的 compose -> render 链路。

角色提示词用渲染器新增的显式模式：

```json
{"character_prompts": {"mode": "explicit", "captions": [{"positive": "...", "negative": "...", "center": {"x": 0.3, "y": 0.5}}], "use_coords": false, "add_male_caption": true}}
```

`center` 可省略（按画面中心）；`use_coords` 为 true 时 `v4_prompt.use_coords` 打开，模型按位置摆放（V4.5 / V5）。base 提示词不动；`add_male_caption` 开着时，和 auto 模式一样按主体里的 `1boy` 等计数补男角色提示词。之前考虑过用 `::character A: ...::` 块语法，但块后面的画风后缀会被一起吞进角色提示词，所以改为显式模式。

配方出图的 run 记为 `kind: "recipe"`，带配方 id 和版本；和原图对照只看相似度和提示词差异，结论记为 `reference`。

### Web API（P2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/style-lab/workspaces/{id}/recipes` | 配方列表 |
| POST | `/api/style-lab/workspaces/{id}/recipes` | 从图片新建：`{"image_id", "name"?, "group_id"?, "draft"?}`，`draft: true` 只返回不保存（version 0）；或 `{"recipe": {...}}` 保存前端改过的草稿（version 1，id 已存在返回 409） |
| GET | `/api/style-lab/workspaces/{id}/recipes/{rid}` | 配方 + 历史版本列表 |
| PUT | `/api/style-lab/workspaces/{id}/recipes/{rid}` | 保存：`{"recipe", "base_version"}`，冲突返回 409 |
| DELETE | `/api/style-lab/workspaces/{id}/recipes/{rid}` | 删除 |
| GET | `/api/style-lab/workspaces/{id}/recipes/{rid}/versions/{v}` | 读历史版本 |
| POST | `/api/style-lab/workspaces/{id}/recipes/preview` | 预览未保存的草稿：实际发送的提示词、负面、角色提示词 |
| POST | `/api/style-lab/workspaces/{id}/recipes/{rid}/generate` | 用已保存的配方出图，设置同原参重生 |
| GET | `/api/style-lab/library/node?ref=&role=` | 素材卡片：节点 tag 按部位分组，下划线换成空格 |

## P3：导出 artist 与测试

### 导出

配方导出到 `design/画风/<作者 id>_<EnglishStyleName>/`（画风目录取 `NodeWorkspace` 的画风根目录）。作者 id 默认取工作区根目录名（`artist_parse/<日期>/<作者 id>`）；画风名只允许英文字母、数字和单个下划线。

`tags.txt` 沿用旧格式：

```text
<前缀，空时写 ,>
,
<后缀，空时省略>
type, not_quailty_prompts
=
origin_uc, <画风负面>
gen_json, {"model": ..., "sampler": ..., ...}
```

- `gen_json` 来自预览用的同一个 artist 节点：画风参数、模型、vibe（`reference_image_multiple` 等原样内嵌，和已有画风一致），不含宽高、种子。
- `add_original_image` 缺省时写 `false`：旧画风缺省时渲染器按 `true` 处理，网页端文生图的元数据里又没有这一项。
- token 之间的换行改成逗号：tags.txt 一行就是一段，预览、导出、读回三者一致。
- 前缀为空时第 1 行也写 `,`，否则读取器丢掉空行后，后缀会被当成前缀。

导出前的检查：

- **读回校验**：在临时目录写一遍 tags.txt，用正式的 `NovelAIArtistRepository` 读回来，前缀、后缀、负面、参数、标记逐项和配方比对。不一致（例如某段以 `type` 开头被当成标记行）就拒绝导出。
- **对比**：默认和这个配方上一次的导出比；没导出过就挑同作者已有画风里画风 token 最接近的。提示词按 token 增删列出；只换了位置或顺序时单独说明。参数逐项列出，宽高、种子不比，没写和空列表视为相同，vibe 只比张数。
- **目录**：目标目录已存在时不覆盖，改用并列版本 `_v2`、`_v3`……；导出请求带上预览时看到的目录名，目录在这期间被占用就返回 409，要求重新预览。

写入时先写到画风目录下的临时目录，再整体改名，失败不会留下半个画风。目录里除了 tags.txt 还有：

| 文件 | 内容 |
| --- | --- |
| `notes.md` | 来源（工作区、配方及版本、原图、投稿）、参数、测试用主体 |
| `stylelab_export.json` | 导出标记：配方 id 和版本、工作区、原图、时间 |
| `source_<原图名>.png` 等 | 勾选“附带原图”时：原图、原图提示词、负面、测试用主体（`source_action_*`）、完整参数 |

每次导出记在 `.stylelab/exports.json`，配方页据此显示已导出的版本，以及配方在导出后是否又改过。

### 用导出的 artist 测试

测试按目录名读取导出的 artist，走和日常出图完全一样的链路（`compose_render_plan`，`render.artist` 是目录名）。导出的 artist 和配方本身拼出的请求逐字段相同（有测试覆盖）。

**回归对照**（`kind: "regression"`）：

- 候选图：配方所属分组（或变体）里有元数据、不是局部重绘/图生图的图，每个投稿一张，配方原图排第一，其余按日期从新到旧；默认取 4 张，最多 12 张。
- 内容提示词：原图提示词先把配方的画风块（前缀、后缀）原样出现的整段切掉（块前后必须是分隔符或首尾），再按 tag 去掉画风块拆出的 tag 和分类为画师/风格/质量/元信息的 tag；配方里手动留在主体的 tag 不按分类去掉；去掉后只剩权重符号的碎片（如 `::`）也去掉。
- 丢弃的词（`dropped`）：`keep`（默认）留在内容里，分类说是风格也不去掉，这样和原图比的是同一张图；`strip` 和画风一起去掉。
- 种子、尺寸、角色提示词取各自原图；也可以用共用随机种子或指定种子，尺寸可用 `custom`、`random`、`loop`（`size_mode`，没写时给了宽高就是 `custom`）。
- 每张和自己的原图对照，界面显示平均相似度。

**泛化矩阵**（`kind: "matrix"`）：提示词库的角色（行，最多 4 个）× 动作（列，最多 4 个），用节点组合；全部格子共用一个种子，默认 832×1216，也可以 `random`、`loop`。不和原图对照。

测试 run 的 items 额外记录 `label`、`source`、`subject`、`removed`（回归对照）或 `character`、`action`（泛化矩阵）。

### Web API（P3）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/style-lab/workspaces/{id}/recipes/{rid}/exports` | 建议的作者 id、画风目录、以前的导出、可对比的已有画风 |
| POST | `/api/style-lab/workspaces/{id}/recipes/{rid}/export/preview` | `{"name", "author"?, "compare_ref"?, "include_source"?}` → 目标目录、tags.txt、读回校验、对比 |
| POST | `/api/style-lab/workspaces/{id}/recipes/{rid}/export` | 同上，另带 `expected_folder`；目录变了返回 409 |
| POST | `/api/style-lab/workspaces/{id}/recipes/{rid}/probe` | P4 画风探针：`{"settings": {"kind": "swap" \| "ablation", "characters"?, "replace_clothing"?, "caption_index"?, "units"?, "include_baseline"?, "seed_mode", "seed"?}, "force"?}` |
| POST | `/api/style-lab/workspaces/{id}/recipes/{rid}/artist-test` | `{"settings": {"kind", "artist", "image_ids"?, "characters"?, "actions"?, "seed_mode", "seed"?, "width"?, "height"?}}` |
| GET | `/api/style-lab/workspaces/{id}/runs?recipe_id=` | 某个配方的全部 run（配方出图、回归对照、泛化矩阵） |

## P3 之后的调整

### 原参重生的对照

- 原图元数据里有、NovelAI 出图不回写的键（重生时已原样发送），标为可忽略差异。典型来源是 NAI Smart Studio：它在 Comment 里另记一份 `negative_prompt`、`char_prompts`、`cfg_scale`、`model`、`Description` 等。`tag_hint_*` 是客户端的提示开关，NovelAI 回写为 null，同样忽略。界面上同一原因的可忽略差异合并成一行。

### 图片详情

`GET /workspaces/{id}/file-info?image_id=|path=` 返回绝对路径、大小、修改时间；`POST /workspaces/{id}/reveal` `{image_id | path}` 在资源管理器里打开所在文件夹并选中文件（仅 Windows，其他平台 501）。两者和 `/file` 一样只接受工作区里的原图和 runs 下的出图。打开用 `SHOpenFolderAndSelectItems`：文件名里常有逗号，`explorer /select,` 会在逗号处截断。
- `Source` 是 "NovelAI Diffusion V5 …" 时，对照用的模型名按 V5 解析。
- V4 起 `Source` 不写 Curated / Full，只写代际加模型哈希（如 `NovelAI Diffusion V5 DB276663`）。原图模型照 novelai.net 前端的规则认（`clients/novelai.py` 的 `NOVELAI_SOURCE_HASH_MODELS`，2026-10-11 从官网 `_app` 包核对）：按代际查哈希表，表里含各模型的历代哈希，例如 V5 Full `657484A5` / `0ADF9AB7`、V5 Curated `DB276663`、V5 Full Medium `93F4BD30` / `70AB5786`。哈希没登记时和官网一样兜底：V5 当 Curated，V4.5 当 V4.5 Curated，其余 V4 当 V4 Curated Preview；图片同时标 `model_unverified`（界面显示"模型待确认"），可以在重生设置里手动选模型。Source 比第三方客户端在 Comment 里另记的 `model` 优先。V4 Curated 的模型 id 是 `nai-diffusion-4-curated-preview`。
- 图片记录带 `record_version`；解析规则变了版本加一，打开工作区时旧版本记录即使文件没变也会重新读取。

### 重复请求

`request_hash` 是发给 NovelAI 的请求（不含 meta 里的来源记录）的指纹，记在 run 里。和同一目标的上一次同类出图（原参重生按原图，配方出图和导出测试按配方）指纹相同、且上一次是 queued / running / succeeded 时，返回 409 `duplicate_request`，`details` 带上一次的 `run_id`、`status`、`created_at`；请求带 `force: true` 才出图。查重和创建 run 在同一把锁里，连点两次也拦得住。

### 素材库

`GET /api/style-lab/library/search?role=&q=&facet=cast:solo&facet=pose:lying&offset=&limit=` 返回去重后的节点：

- 节点内容（meta.yaml / node.yaml 去掉 `id`、`name`、`description`、`legacy` 及空行，加上 tags.txt）相同的目录合并成一条；代表目录优先取名字不带"快捷方式 / 副本 / copy"后缀的，名字去掉后缀。`copies`、`copy_paths` 是其余副本。
- 动作带 `classify.yaml` 分面（cast、domain、subtype、pose、environment、clothing、tone、flags、phase）。同一分面多选任一命中，不同分面同时满足；`facet_options` 里每个分面的计数不受它自己的选择影响。
- 目录用 scandir 遍历，按文件修改时间只重读改过的目录；指纹和分面缓存在 `runtime/stylelab/library_index.json`。动作库七千多个目录，第一次约十几秒，之后约 2 秒；第一次搜索时后台会顺带建好动作索引。

配方新增 `materials`：这个配方用到的素材块 `{role, ref, name, excluded}`，`excluded` 是筛掉的 tag。素材架本身是全局的：`GET / PUT /api/style-lab/shelf`，存在 `runtime/stylelab/material_shelf.json`，内容是 `materials`（同样的素材块，按 role + ref 去重）和 `facets`（角色 / 动作各自的分类筛选）。素材块用进配方时才复制进配方的 `materials`；配方在用的块，在素材架上筛 tag 会同步增删配方里的 tag。主体和角色提示词里的 token 仍用 `character:<ref>` / `action:<ref>` 记来源。`character.add_male_caption` 默认改为 `false`。

回归对照的角色提示词照搬原图的全部条目，不再按计数补男角色。

### 共性分析

图片网格下方，在前端按当前分组（画风分组、投稿或月份）和筛选出的图计算：提示词 tag 去掉权重后按出现张数分为全部共有、多数（≥ 一半）、少数；记录每个 tag 的权重写法（对整段文本按 `n::` / `::` 分段，权重段可以跨逗号），写法不一致时提示。参数逐项统计分布，不比尺寸。每张图和其他图的 tag 平均 Jaccard 重合度作为代表性，重合度高、参数偏离少的排前面，作为推荐基准。

选中的图和对比对象比：对比对象是其余全部图时，"多出"是超过一半的其他图没有的，"缺少"是超过一半的其他图有的，恰好一半的两边都不算；权重和参数和多数比。对比对象是某一张图时就是两边各自独有的 tag 和不同的权重、参数。

## P4：画风探针与版本历史

### 画风探针

`style_lab/probe.py`。在保存好的配方上生成几个变体，用同一个种子出图（`seed_mode` 同出图设置，默认原图种子），run 的 `kind` 是 `swap` 或 `ablation`，每张图带 `label`、`role`（`baseline` / `variant`）和改了什么。

- 基准图：完整配方。`ablation` 总是带；`swap` 由 `include_baseline` 决定。变体出完后和同一次的基准图算 `baseline_compare`（`similarity`、`dhash_distance`），和原图的对照照旧写在 `compare`。
- 替换角色：`characters` 是 `[{ref, name, tags}]`（最多 4 个），tags 由前端按素材块的筛选给出。
  - 换进哪里由 `target` 决定：`subject`、`caption`（第 `caption_index` 条），默认 `auto` 是原角色在哪就换哪。auto 先找角色名（类别 character 或角色卡的 token），依次看各条角色提示词、再看主体；都没有时取外貌 tag 最多的地方（并列时主体优先）。没启用角色提示词时总是主体。
  - 换进角色提示词：这一条里去掉角色卡加进来的 token 和类别为 character、appearance（`replace_clothing` 时加 clothing）的 token，性别词保留，新角色插在第一个被去掉的位置；没有性别词时补 `girl`。主体里只去掉角色名和角色卡的 token。
  - 换进主体：去掉同样的 token，新角色插在原来的位置；没有可去的就放在开头的人数 tag 后面。启用了角色提示词且只有一条时，那一条里的同类 token 也去掉（多半是同一个角色写的动作），两条以上不动。
  - 每张记录 `target`、`removed`、`added`。
- 消融：`units` 是 `[{label, token_ids}]`（最多 12 组），token 必须在画风前缀或后缀里，否则 400（配方改过了）。每组去掉后出一张，记录 `token_ids`、`removed`。
- 查重同其他出图：同一配方上一次同类探针的请求完全相同时 409。

### 版本历史

保存时旧版本写进 `recipes/<id>.history/v<N>.json`（P2 起就有）。前端：

- 左栏列出版本，标上每个版本出过的图（run 里的 `recipe.version`）和导出（导出记录的 `recipe_version`）。
- 版本对比按区域列出 token 的增删（按文本计数，不看来源和分隔符；只有顺序或分隔符变了时列在设置里），以及模型、参数、角色提示词开关、素材、备注等设置的变化。
- 恢复：旧版本的内容换上当前的 id、版本号和时间放进编辑区，保存后成为新版本（画风和当前一样时原地保存）。

### 还没做

- 视觉差异诊断。
