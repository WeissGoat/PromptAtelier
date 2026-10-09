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
| P3 | artist 导出器、回归对照、泛化矩阵、`run-prompt` 支持显式角色提示词 |
| P4 | 替换角色、消融测试、配方版本历史、视觉差异诊断 |

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
| `char_captions` | v4 角色提示词（正向 + 负向），单角色阶段也完整保留 |
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
| 尺寸 | `source`：原图尺寸；`custom`：指定宽高 |
| 参数覆盖 | model、steps、scale、cfg_rescale、sampler、noise_schedule；不填则沿用原图 |

### 对照

每张生成图完成后计算：

- 参数差异：`compare_render_parameters`，同时给出忽略宽高的结果。
- 图像相似度：两图缩放到同一尺寸后的灰度平均差（0–1，1 为完全相同）和 dHash 汉明距离。
- 结论分三档：参数一致且相似度 ≥ 0.9 为 `match`，参数一致但相似度低为 `drift`，参数不一致为 `param_diff`。

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
- 打开或重扫工作区后，后台任务把全部提示词、负面和角色提示词预翻译进缓存（`POST /workspaces/{id}/pretranslate` 也可手动触发）。
- 画师名标为"画师"，不翻译（P2 接入画师名单后生效，P1 由 LLM 判断）。

## Web API（P1）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/style-lab/workspaces` | 已登记的工作区 |
| POST | `/api/style-lab/workspaces` | 打开或创建：`{"root": "<文件夹>"}` 或 `{"files": [...], "name": "..."}` |
| GET | `/api/style-lab/workspaces/{id}` | 工作区设置 + 图片记录列表 |
| POST | `/api/style-lab/workspaces/{id}/scan` | 增量重扫 |
| POST | `/api/style-lab/workspaces/{id}/upload` | 图片组工作区上传图片（multipart `files`） |
| POST | `/api/style-lab/workspaces/{id}/pretranslate` | 后台预翻译，返回 job_id |
| GET | `/api/style-lab/workspaces/{id}/images/{image_id}` | 单张图片完整元数据（含原始参数，vibe 图片数据截断） |
| GET | `/api/style-lab/workspaces/{id}/file` | 读取图片：`image_id` 或 `path`（只允许工作区图片和 runs 目录），`size>0` 返回缩略图 |
| POST | `/api/style-lab/workspaces/{id}/regenerate` | 原参重生：`{"image_id": "...", "settings": {...}}`，返回 run 记录（含 job_id） |
| GET | `/api/style-lab/workspaces/{id}/runs` | run 列表，可按 `image_id` 过滤 |
| GET | `/api/style-lab/workspaces/{id}/runs/{run_id}` | 单个 run，含每张结果的对照 |
| GET | `/api/style-lab/llm/status` | LLM 是否已配置、模型名 |
| POST | `/api/style-lab/translate` | `{"texts": [...]}` -> `{"translations": {...}}` |

## 已确定的后续约束（P2+）

- 先只支持单角色：一条 base caption + 一条角色提示词。
- 配方编辑器从原始提示词开始：放两条分界线切出前缀 / 主体 / 后缀，或按 1/2/3/X 刷选，或采用"同组词频 + LLM"建议，然后锁定画风。
- 锁定只阻止批量操作（恢复原图主体、替换角色、清空主体）改动画风区；主动把主体 token 划为画风（S / Shift+S）始终允许。
- 每个 token 记录来源（原图、角色卡、动作卡、手打、LLM），素材卡片的"移除"只删只属于这张卡的 token。
- 角色提示词区同时显示原图的 `char_captions`、可编辑的 #1、以及渲染器预测会生成的角色提示词（含根据 `1boy` 等计数标签自动添加的），不一致时标黄并写明原因。
- 分词器必须无损：没改动的 token 重新拼回去要和原文逐字节相同，包括 `|` 分隔符和权重语法。
- 导出的 `tags.txt` 沿用现有格式：第 1 行前缀，第 2 行 `,`，第 3 行后缀，`gen_json` 不含宽高。
