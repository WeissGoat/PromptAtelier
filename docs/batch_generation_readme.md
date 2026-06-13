# 批量跑图 README

本文档面向日常使用，说明 Batch YAML 怎么写、每个字段是什么意思、怎么运行，以及运行后会产生哪些结果文件。

更底层的设计背景见 `batch_generation_spec_v1.md`；真实业务验收记录见 `batch_generation_business_test_20260613.md`。

## 1. 基本定位

批量跑图模块负责把一份 Batch YAML 展开成多个任务，然后逐个走 core 的生图链路：

```text
Batch YAML
-> BatchPlanner 展开任务
-> BatchRunner 执行任务
-> Composer 生成 PromptBundle
-> Renderer/Adapter 生成 RenderRequest
-> NovelAI 执行
-> GenerationResult + PNG 参数 + 报告
```

当前正式接入目标是 NovelAI。ComfyUI / SD 暂不作为本阶段主线。

日常推荐两种用法：

- 已经有完整 prompt：用 `composer: full`，批量只负责叠加 artist 和 NovelAI 参数。
- 需要 agent 拼 prompt：用 `composer: agent`，没有缓存时先生成 `requires_agent` 任务，填回 agent 结果后再 `resume-batch`。

## 2. 快速开始

在 `refactor` 根目录运行：

```powershell
cd F:\my_project\new\tags_machine\refactor
```

如果本机没有设置 `NAI_ACCESS_TOKEN`，可以临时从旧项目 token 读取：

```powershell
$tokenText = Get-Content -Path 'F:\my_project\new\tags_machine\novelai\client.py' -Raw
$env:NAI_ACCESS_TOKEN = [regex]::Match($tokenText, 'return\s+"([^"]+)"').Groups[1].Value
```

先规划，不真实生图：

```powershell
uv run python -m tags_machine_core plan-batch examples\batches\prompt_list_20260412.yaml --full
```

真实运行：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --full
```

限制只跑 1 个任务：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --limit 1 --full
```

查看一个批次结果：

```powershell
uv run python -m tags_machine_core inspect-batch outputs\batches\prompt-list-20260412 --full
```

断点续跑：

```powershell
uv run python -m tags_machine_core resume-batch outputs\batches\prompt-list-20260412 --full
```

## 3. 最小 YAML 示例

适合 agent 已经拼好完整 prompt 的场景：

```yaml
schema: tags-machine-core.batch/v1
name: prompt-list-20260412
config: configs/local.example.yaml
output_root: outputs/batches

defaults:
  composer: full
  artist: 20260412
  nt: 1
  resolution: square
  model: nai-diffusion-4-5-full

select:
  prompts:
    - selector: prompt_list
      items:
        - id: standing_001
          prompt: "akemi_homura, 1girl, standing, looking at viewer"
        - id: foot_001
          prompt: "akemi_homura, 1girl, bare feet, foot focus, lower body"

expand:
  mode: prompt_list

run:
  resume: true
```

这里会生成 2 个任务，每个任务使用同一个 artist `20260412`，并走 NovelAI 真实生图。

## 4. Batch YAML 字段

### 4.1 顶层字段

| 字段 | 必填 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `schema` | 否 | `tags-machine-core.batch/v1` | 批量配置版本。建议保留，便于后续兼容检查。 |
| `name` | 是 | 无 | 批次名称，也会作为输出目录名：`outputs/batches/<name>`。 |
| `description` | 否 | `null` | 给人看的说明，不影响生图。 |
| `config` | 否 | `configs/local.example.yaml` | core 运行配置，主要用于读取旧 `design_root` 和后端配置。 |
| `output_root` | 否 | `outputs/batches` | 批次输出根目录。 |
| `defaults` | 否 | 见下文 | 每个任务的默认生图参数和 composer 参数。 |
| `collections` | 否 | `{}` | 给 selector 用的目录集合，适合把“动作分类文件夹”起名后复用。 |
| `select` | 否 | 空选择 | 选择 artist、character、action、background、prompt 的规则。 |
| `expand` | 否 | `mode: product` | 把选择结果展开成任务的方式。 |
| `run` | 否 | 见下文 | 执行、续跑、重试、图片预算相关配置。 |
| `archive` | 否 | 见下文 | 控制哪些中间结果落盘。 |
| `report` | 否 | 见下文 | 控制报告文件内容。 |
| `tasks` | 否 | `[]` | `expand.mode: manual` 时手写任务列表。 |

路径说明：

- `config`、selector 的相对路径按 Batch YAML 所在目录解析。
- `expand.action_group_record` 是运行态 cache 路径，相对当前运行目录解析；示例中的 `cache/batch/...` 会落在 `refactor/cache/batch/...`。
- 建议从 `F:\my_project\new\tags_machine\refactor` 运行命令，示例路径都按这个目录写。

### 4.2 `defaults`

`defaults` 会被复制到每个任务的 `task.render`、`task.agent` 和 `task.policy`。

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `backend` | `novelai` | 生图后端。当前主线只使用 `novelai`。 |
| `composer` | `full` | 提示词生成模式：`full`、`agent`、`script`。 |
| `artist` | `null` | 画风节点名或 artist ref，例如 `20260412`。如果 `select.artists` 有值，会覆盖/展开成对应任务。 |
| `nt` | `1` | 每个任务出几张图。为控制 Anlas 和输出可比性，建议批量时保持 `1`。 |
| `resolution` | `random_standard` | 尺寸预设：`square`、`landscape`、`portrait`、`random_standard`。 |
| `width` | `null` | 自定义宽度。和 `height` 同时提供时优先生效。 |
| `height` | `null` | 自定义高度。和 `width` 同时提供时优先生效。 |
| `seed` | `null` | 固定 seed。为空时由后端随机。 |
| `image_format` | `png` | 输出格式。当前建议保持 `png`，因为要读取 PNG 参数。 |
| `model` | `nai-diffusion-4-5-full` | NovelAI 模型名。 |
| `prompt_policy_profile` | `null` | PromptPolicyPipeline 配置名。为空或 `off` 表示不启用。AgentComposer 默认不经过规则管线。 |
| `agent_model` | `null` | 给 agent 任务记录的模型偏好，不直接调用模型。 |
| `cache_dir` | `null` | agent prompt cache 目录。 |
| `add_male_caption` | `true` | NovelAI v4+ character captions 自动拆分时，如检测到男性角色，额外补男性 caption。 |
| `character_prompts` | `auto` | NovelAI v4+ character captions 模式。`auto` 表示 renderer 尝试根据 character 节点把角色提示词移入 character captions。 |
| `params` | `{}` | 透传给 renderer/backend 的高级参数，例如 NovelAI 特定采样参数。 |

尺寸预设：

| `resolution` | 尺寸 |
| --- | --- |
| `square` | `1024x1024` |
| `landscape` | `1216x832` |
| `portrait` | `832x1216` |
| `random_standard` | 每个任务从上面三种标准尺寸里随机选择 |

### 4.3 `composer`

| 值 | 输入要求 | 行为 |
| --- | --- | --- |
| `full` | 必须有完整 `prompt` | 不再拼 character/action，只把完整 prompt 包装成 `PromptBundle`，再进入 renderer。 |
| `agent` | 需要 character/action/artist 等节点，或已有 agent cache | 没缓存时输出 `requires_agent`；有缓存时复用 agent 结果生成 prompt。 |
| `script` | 需要 character/action 等节点 | 使用通用 ScriptComposer 规则拼接。当前优先级低于 AgentComposer。 |

当前业务建议：

- 生产稳定主链路优先 `full`。
- 需要让 agent 帮忙组合角色动作时用 `agent`。
- `script` 只适合作为后续规则化拼接实验，不建议为了还原旧 formula 硬塞特殊规则。

### 4.4 `select`

`select` 分为六类：

```yaml
select:
  artists: []
  characters: []
  actions: []
  action_groups: []
  backgrounds: []
  prompts: []
```

每一项都是一个 selector。支持的公共字段：

| 字段 | 含义 |
| --- | --- |
| `selector` | 选择器类型：`explicit`、`folder`、`collection`、`glob`、`prompt_list`、`prompt_file`。 |
| `refs` | `explicit` 用，直接列出节点 ref。artist 可以是名字，其他节点通常是目录或文件路径。 |
| `root` | `folder` 用，扫描某个目录。 |
| `name` | `collection` 用，引用 `collections` 中定义的名字；在 `select.action_groups` 中也是动作组名。 |
| `pattern` | `glob` 用，支持通配符。 |
| `path` | `prompt_file` 用，读取 prompt 文件。 |
| `format` | `prompt_file` 用，支持 `lines`、`jsonl`、`json`、`yaml`、`csv`。 |
| `items` | `prompt_list` 用，直接内联 prompt 列表。 |
| `recursive` | `folder` / `collection` 用，是否递归扫描子目录。 |
| `node_files` | 判断一个目录是不是节点目录的文件名列表，默认 `meta.yaml`、`node.yaml`、`tags.txt`。 |
| `include` | 过滤保留项，目前支持 `names`、`paths`。 |
| `exclude` | 过滤排除项，目前支持 `names`、`paths`。 |
| `limit` | 最多取多少个结果。 |
| `shuffle` | 是否先打乱选择结果。 |

#### `explicit`

直接指定节点：

```yaml
select:
  artists:
    - selector: explicit
      refs:
        - 20260412
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/...
```

artist 的 `refs` 通常是旧 `design/画风/<artist>/` 的目录名；character/action/background 的 `refs` 通常是节点目录路径。

`select.actions` 和 `select.action_groups` 的区别：

- `select.actions` 是动作节点池，用于 `product` / `zip` 这类组合展开。
- `select.action_groups` 是动作分类池，用于 `character_action_group`，每个角色先选一个动作组，再跑完组内动作。
- `character_action_group` 模式不能同时配置 `select.actions`。
- 非 `character_action_group` 模式不能配置 `select.action_groups`。

#### `folder`

扫描目录下的节点：

```yaml
select:
  actions:
    - selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_ft_bare
      recursive: true
      limit: 20
```

目录里只要存在 `meta.yaml`、`node.yaml` 或 `tags.txt`，就会被认为是一个节点。

#### `collection`

先在 `collections` 起名，再在 `select` 使用：

```yaml
collections:
  actions:
    foot:
      - F:/my_project/new/tags_machine/design/动作改2/st_ft_bare

select:
  actions:
    - selector: collection
      name: foot
      recursive: true
      limit: 3
```

适合旧 tags_machine 那种“填分类文件夹批量跑动作”的习惯。

#### `glob`

用通配符找节点：

```yaml
select:
  actions:
    - selector: glob
      pattern: F:/my_project/new/tags_machine/design/动作改2/**/meta.yaml
      limit: 10
```

如果匹配到文件，会取文件所在目录作为节点 ref。

#### `action_groups`

`action_groups` 是一组命名动作分类，每个分类内部仍复用普通 selector：

```yaml
select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/.../character_a
        - F:/my_project/new/tags_machine/design/角色/.../character_b

  action_groups:
    - name: st_rp
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_body_mouth_rp
      recursive: true
      limit: 20

    - name: st_sfw
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/sfw_pose
      recursive: true
      limit: 20
```

它的目标展开方式是：

```python
for character in characters:
    action_group = strategy.choose(action_groups)
    for action in action_group.actions:
        run(character + action)
```

`name` 会进入每个任务的 `source.action_group`，报告和日志会显示这个字段。

#### `prompt_list`

在 YAML 里直接写完整 prompt：

```yaml
select:
  prompts:
    - selector: prompt_list
      items:
        - id: foot_001
          prompt: "akemi_homura, 1girl, bare feet, foot focus, lower body"
          negative: "bad anatomy"
          nodes:
            - role: character
              ref: F:/my_project/new/tags_machine/design/角色/...
          meta:
            note: "人工挑选样例"
```

`items` 中每个 prompt item 的字段：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `id` | 是 | prompt 条目 ID，会进入 task id。 |
| `prompt` | 是 | 完整正向提示词。 |
| `negative` | 否 | 单条 prompt 的负向提示词。 |
| `nodes` | 否 | 关联节点引用，用于记录来源，也可辅助 renderer 处理 character captions。 |
| `meta` | 否 | 任意附加信息，会进入 task source。 |

`nodes` 的结构：

| 字段 | 含义 |
| --- | --- |
| `role` | 节点角色，例如 `artist`、`character`、`action`、`background`。 |
| `ref` | 节点名或路径。 |
| `index` | 同角色多节点时的顺序。通常不用手写，planner 会重新编号。 |

#### `prompt_file`

从外部文件读取完整 prompt：

```yaml
select:
  prompts:
    - selector: prompt_file
      path: examples/batches/prompts_20260412.txt
      format: lines
```

`format: lines` 时，每个非空行是一条 prompt，`#` 开头的行会跳过。

其他格式：

- `jsonl`：每行一个 prompt item JSON。
- `json`：整个文件是 prompt item 数组。
- `yaml`：整个文件是 prompt item 数组。
- `csv`：表头字段按 prompt item 读取，常用列是 `id,prompt,negative`。

### 4.5 `expand`

`expand` 决定 selector 结果如何变成任务。

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `mode` | `product` | 展开模式：`product`、`zip`、`prompt_list`、`manual`、`character_action_group`。 |
| `max_tasks` | `null` | 最多保留多少个任务。 |
| `shuffle` | `false` | 展开后是否打乱任务顺序。 |
| `action_group_strategy` | `balanced_random` | `character_action_group` 使用：`random`、`ordered`、`balanced_random`。 |
| `action_group_record` | `null` | `balanced_random` 使用的历史记录文件。 |
| `seed` | `null` | 固定动作组随机策略的随机种子。 |

模式说明：

| `mode` | 行为 |
| --- | --- |
| `prompt_list` | 每条 prompt item 生成任务；如果同时选择多个 artist，会形成 prompt × artist。 |
| `product` | character × action × artist × background 笛卡尔积。 |
| `zip` | 按索引配对；长度不一致时短列表会循环取值。 |
| `manual` | 不看 selector，直接使用顶层 `tasks`。 |
| `character_action_group` | 每个 character 选择一个 action group，再跑完该组内全部 action。 |

`character_action_group` 策略：

| `action_group_strategy` | 行为 |
| --- | --- |
| `random` | 每个角色随机选一组，允许重复。 |
| `ordered` | 按角色顺序轮流选组，动作组不够时循环。 |
| `balanced_random` | 优先从 `action_group_record` 里历史 `selected_count` 最少的组中随机选，尽量避免重复。 |

`balanced_random` 的记录文件示例：

```json
{
  "schema": "tags-machine-core.action-group-record/v1",
  "groups": {
    "st_rp": {"selected_count": 2},
    "st_sfw": {"selected_count": 1},
    "st_foot": {"selected_count": 1}
  }
}
```

`manual` 示例：

```yaml
defaults:
  composer: full
  artist: 20260412

expand:
  mode: manual

tasks:
  - id: custom_001
    prompt: "akemi_homura, 1girl, standing"
    negative: "bad anatomy"
    artist: 20260412
```

### 4.6 `run`

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `resume` | `true` | 已成功任务是否跳过。适合断点续跑。 |
| `stop_on_error` | `false` | 是否遇到第一个失败任务就停止。 |
| `max_images` | `null` | 本次最多生成多少张图。用于控制成本。 |
| `execute_requires_agent` | `false` | 预留字段。当前 requires_agent 不会直接调用外部模型。 |
| `retry.max_attempts` | `3` | 每个任务最多尝试次数。 |
| `retry.timeout_seconds` | `null` | 覆盖后端请求 timeout；为空使用 config 默认。 |
| `retry.retry_on` | `["429","500","502","503","504","timeout"]` | 哪些错误文本视为可重试。 |
| `retry.backoff_seconds` | `[1.0,2.0,5.0,10.0]` | 每次重试前等待秒数。超过列表长度后使用最后一个值。 |

示例：

```yaml
run:
  resume: true
  stop_on_error: false
  max_images: 20
  retry:
    max_attempts: 5
    timeout_seconds: 60
    retry_on: ["429", "502", "503", "504", "timeout"]
    backoff_seconds: [1, 3, 10, 20]
```

### 4.7 `archive`

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `save_prompt_bundle` | `true` | 保存 `prompt_bundle.json`。 |
| `save_render_request` | `true` | 保存 `render_request.json`。 |
| `save_generation_result` | `true` | 保存 `generation_result.json`。 |
| `save_png_params` | `true` | 保存从 PNG 读取到的参数摘要 `png_params.json`。 |
| `copy_images` | `false` | 是否把图片复制进任务目录的 `images/`。默认图片仍保存在全局输出目录，但路径会写进结果。 |

建议日常保持默认，便于问题排查和对比旧 tags_machine。

### 4.8 `report`

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `markdown` | `true` | 写出 `report.md`。 |
| `json` | `true` | 写出 `report.json`。 |
| `include_prompt_preview` | `true` | 报告里带 prompt 前 300 字符预览。 |
| `include_png_params_summary` | `true` | 报告里带 PNG 参数摘要。 |
| `visual_check_template` | `true` | `report.md` 增加人工视觉检查列。 |

## 5. 常用使用方式

### 5.1 完整 prompt 列表

用于 agent 或人工已经拼好 prompt 的情况：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_list_20260412.yaml --full
```

特点：

- `composer: full`
- 不需要 character/action 节点
- 最接近当前稳定主链路 `run-prompt`

### 5.2 prompt 文本文件

YAML：

```yaml
defaults:
  composer: full
  artist: 20260412

select:
  prompts:
    - selector: prompt_file
      path: examples/batches/prompts_20260412.txt
      format: lines

expand:
  mode: prompt_list
```

运行：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\prompt_file_20260412.yaml --full
```

适合外部 agent 批量产出一行一个 prompt，core 只负责稳定跑图和归档。

### 5.3 从动作分类文件夹批量跑

YAML 结构：

```yaml
defaults:
  composer: script
  artist: 20260412
  nt: 1
  resolution: random_standard

collections:
  actions:
    foot:
      - F:/my_project/new/tags_machine/design/动作改2/st_ft_bare

select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/...
  actions:
    - selector: collection
      name: foot
      recursive: true
      limit: 3
  artists:
    - selector: explicit
      refs:
        - 20260412

expand:
  mode: product
  max_tasks: 3
```

运行：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\action_folder_script_20260412.yaml --full
```

这类用法对应旧 tags_machine “指定动作分类文件夹批量跑”的习惯。

### 5.4 每个角色随机选择一个动作分类

适合类似 blackboard 的循环：

```python
for character in characters:
    action_group = choice(action_groups)
    for action in action_group:
        run(character + action)
```

YAML 结构：

```yaml
defaults:
  composer: script
  artist: 20260412
  nt: 1
  resolution: random_standard

select:
  characters:
    - selector: explicit
      refs:
        - F:/my_project/new/tags_machine/design/角色/.../character_a
        - F:/my_project/new/tags_machine/design/角色/.../character_b

  action_groups:
    - name: st_rp
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_body_mouth_rp
      recursive: true

    - name: st_sfw
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/sfw_pose
      recursive: true

    - name: st_foot
      selector: folder
      root: F:/my_project/new/tags_machine/design/动作改2/st_ft_bare
      recursive: true

expand:
  mode: character_action_group
  action_group_strategy: balanced_random
  action_group_record: cache/batch/action_group_record.json
  seed: 20260613
```

运行：

```powershell
uv run python -m tags_machine_core plan-batch examples\batches\character_action_group_20260412.yaml --log-level info --full
uv run python -m tags_machine_core run-batch examples\batches\character_action_group_20260412.yaml --limit 1 --log-level info --full
```

`plan-batch` 输出的 `selector_summary.action_groups` 会显示每个动作组展开出的任务数。`report.md` 的任务详情会包含 `source: character=..., action_group=..., action=...`。

### 5.5 AgentComposer 缓存流程

第一次跑没有缓存时，任务会进入 `requires_agent`，并在批次目录生成 agent 任务：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\agent_cache_miss.yaml --full
```

检查：

```powershell
uv run python -m tags_machine_core inspect-batch outputs\batches\agent-cache-miss --full
```

把外部 agent 结果写回缓存后，再续跑：

```powershell
uv run python -m tags_machine_core resume-batch outputs\batches\agent-cache-miss --full
```

说明：

- `agent_tasks/<task_id>.json` 是交给外部 agent 的任务。
- `agent_results` 或 cache 的落盘方式以后可以接 UI/worker；当前核心逻辑是“没有缓存就退出并提示 requires_agent，有缓存就继续生成”。
- AgentComposer 不经过 PromptPolicyPipeline，避免规则系统影响 agent 已经拼好的 prompt。

### 5.6 JSON API 入口

适合前端或 worker 调用：

```powershell
uv run python -m tags_machine_core api-plan-batch path\to\batch_request.json --full
uv run python -m tags_machine_core api-run-batch path\to\batch_request.json --full
uv run python -m tags_machine_core api-resume-batch path\to\batch_resume_request.json --full
uv run python -m tags_machine_core api-inspect-batch path\to\batch_inspect_request.json --full
```

请求可以传：

- `batch_spec` / `spec_path`：指向 YAML 文件。
- `spec` / `batch`：直接内联 BatchSpec 对象。

文件路径请求示例：

```json
{
  "batch_spec": "examples/batches/prompt_list_20260412.yaml"
}
```

续跑和查看请求示例：

```json
{
  "run_dir": "outputs/batches/prompt-list-20260412",
  "batch_spec": "examples/batches/prompt_list_20260412.yaml"
}
```

## 6. 输出结果结构

默认输出目录：

```text
outputs/batches/<batch-name>/
  batch.yaml
  batch_source.json
  index.json
  manifest.jsonl
  report.json
  report.md
  agent_tasks/
    <task_id>.json
  tasks/
    <task_id>/
      task.json
      status.json
      agent_task.json
      prompt_bundle.json
      render_request.json
      generation_result.json
      png_params.json
      images.json
      images/
        *.png
```

并不是每个任务都会有上面所有文件：

- `plan-batch` 只会写批次目录、`manifest.jsonl` 和任务清单相关文件。
- `requires_agent` 任务会有 `agent_task.json`，但不会有真实生图结果。
- 只有真实生图成功的任务才会有 `prompt_bundle.json`、`render_request.json`、`generation_result.json`、`png_params.json`、`images.json`。
- `images/` 只有 `archive.copy_images: true` 时才会复制图片进任务目录；否则图片路径记录在 JSON 里。

### 6.1 批次级文件

| 文件 | 含义 |
| --- | --- |
| `batch.yaml` | 本次运行使用的 Batch YAML 副本。API 内联 spec 也会被转成 YAML 保存。 |
| `batch_source.json` | 记录 Batch YAML 来源：文件路径或 inline API request。 |
| `manifest.jsonl` | 任务状态追加日志。每行是一个 manifest entry。运行、重试、成功、失败都会追加记录。 |
| `index.json` | 规划阶段任务索引，便于快速查看任务列表。 |
| `report.json` | 汇总报告，包含 status 计数和每个任务的主要结果。 |
| `report.md` | 给人看的 Markdown 报告，包含图片路径、错误、prompt 预览和人工视觉检查列。 |

`manifest` 状态含义：

| 状态 | 含义 |
| --- | --- |
| `pending` | 已规划，还未开始。 |
| `ready` | 预留状态，表示可执行。 |
| `running` | 当前尝试正在执行。 |
| `requires_agent` | agent 模式缺少缓存，需要外部 agent 先生成 prompt。 |
| `succeeded` | 真实生图成功，并读取到了 PNG 参数。 |
| `succeeded_with_warning` | 预留状态，表示成功但有警告。 |
| `failed` | 任务失败。 |
| `skipped` | 续跑时发现已成功，跳过。 |
| `cancelled` | 预留状态，表示取消。 |

### 6.2 任务级文件

#### `task.json`

规划后单个任务的完整输入快照，结构对应 `BatchTask`：

```json
{
  "schema": "tags-machine-core.batch-task/v1",
  "id": "task_id",
  "index": 0,
  "composer": "full",
  "nodes": [],
  "prompt": "akemi_homura, 1girl, standing",
  "negative": null,
  "extra_prompt": "",
  "render": {},
  "agent": {},
  "policy": {},
  "output": {},
  "source": {}
}
```

关键字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 任务 ID，由输入摘要和 hash 生成，也可在 manual task 中手写。 |
| `index` | 批次中的顺序。 |
| `composer` | 本任务使用的 composer。 |
| `nodes` | 关联节点列表，支持多角色、多同类节点。 |
| `prompt` | `full` 模式的完整 prompt。 |
| `negative` | 任务级 negative prompt。 |
| `render` | 生图参数快照。 |
| `agent` | agent 选项，例如 cache_dir、agent_model。 |
| `policy` | PromptPolicyPipeline 配置。 |
| `output.task_dir` | 本任务输出目录。 |
| `source` | selector 或 prompt item 带来的来源信息。 |

`character_action_group` 模式下，`source` 会包含：

| 字段 | 含义 |
| --- | --- |
| `character` | 当前任务使用的角色节点路径。 |
| `action` | 当前任务使用的动作节点路径。 |
| `action_group` | 当前动作来自哪个动作分类。 |
| `action_group_strategy` | 动作组选择策略。 |
| `action_group_record` | 使用的 record 文件路径，可能为空。 |
| `action_index_in_group` | 当前动作在组内的索引。 |
| `action_count_in_group` | 当前动作组总动作数。 |
| `action_group_selected_count` | `balanced_random` 选择后该组累计选中次数。 |

#### `status.json`

当前任务最新状态：

```json
{
  "schema": "tags-machine-core.batch-task-status/v1",
  "task_id": "task_id",
  "status": "succeeded",
  "attempt": 1,
  "render": {},
  "image_paths": [],
  "error": null,
  "warning": null,
  "updated_at": "2026-06-13T..."
}
```

失败排查优先看：

1. `status.json.error`
2. `manifest.jsonl` 中同一 `task_id` 的最近几行
3. `report.md` 的 Error 列

#### `prompt_bundle.json`

Composer 输出的完整提示词包，对应 `PromptBundle`：

| 字段 | 含义 |
| --- | --- |
| `schema` | `tags-machine-core.prompt-bundle/v2`。 |
| `prompt.positive` | 正向提示词。 |
| `prompt.negative` | 负向提示词。 |
| `meta` | 节点、组合、agent、业务来源等元信息。 |
| `cache` | cache key、是否命中缓存等信息。 |
| `created_at` | 创建时间。 |

#### `render_request.json`

Renderer/Adapter 输出的生图请求，对应 `RenderRequest`：

| 字段 | 含义 |
| --- | --- |
| `schema` | `tags-machine-core.render-request/v1`。 |
| `backend` | 后端名，当前主线是 `novelai`。 |
| `prompt` | 最终传给后端的正向 prompt。 |
| `negative_prompt` | 最终传给后端的 negative prompt。 |
| `model` | 后端模型。 |
| `seed` | seed。 |
| `size.width` / `size.height` | 最终尺寸。 |
| `params` | 后端参数，包括采样、character prompts、reference/vibe 等。 |
| `artist_payload` | artist 节点解析出的画风数据。 |
| `meta` | renderer 附加信息。 |

#### `generation_result.json`

真实生图返回和归档结果，对应 `GenerationResult`：

| 字段 | 含义 |
| --- | --- |
| `schema` | `tags-machine-core.generation-result/v1`。 |
| `backend` | 后端名。 |
| `images` | 生成图片列表。每项包含 `path`、`filename`、`meta`。 |
| `request_body` | 最终发给 NovelAI 的 request body。用于和 PNG 参数对比。 |
| `png_info` | 从 PNG 文件读取到的内嵌参数。 |
| `cache_hit` | 是否命中执行层缓存。 |
| `created_at` | 创建时间。 |

#### `png_params.json`

从图片 PNG 信息里读取出来的参数摘要。用于验收：

- core `GenerationResult.request_body` 是否和图片内嵌参数一致。
- 新版 core 和旧 tags_machine 图片参数差异有多大。

常用对比命令：

```powershell
uv run python -m tags_machine_core inspect-image-params path\to\image.png --normalized
uv run python -m tags_machine_core compare-render-params path\to\old.png path\to\generation_result.json --show-normalized
```

#### `images.json`

任务生成图片索引：

```json
{
  "images": [
    {
      "path": "outputs/xxx.png",
      "filename": "xxx.png",
      "meta": {}
    }
  ]
}
```

CLI 结果和 `report.md` 也会打印图片路径；业务验收时优先打开 `images.json` 或 `report.md` 里的路径。

### 6.3 Agent 任务文件

`agent_tasks/<task_id>.json` 和任务目录里的 `agent_task.json` 内容一致，用来交给外部 agent。

典型用途：

- 外部 agent 读取 character/action/artist 节点和任务说明。
- agent 返回完整 prompt。
- core 将 agent 结果写入 cache。
- `resume-batch` 继续生图。

### 6.4 运行日志

默认日志级别是 `error`。批量跑图时建议打开 info：

```powershell
uv run python -m tags_machine_core run-batch examples\batches\character_action_group_20260412.yaml --limit 1 --log-level info --full
```

`character_action_group` 模式会输出：

- 解析出的动作组数量、角色数量、策略。
- 每个角色选中的动作组、动作数量、`selected_count`。
- 每个任务的 `index/total`、角色、动作组、动作、artist、分辨率、`nt`、seed。
- 重试时的 `attempt/max_attempts`、错误和等待时间。
- 成功后的图片路径。
- 每个角色动作组的完成摘要。

## 7. 成本和稳定性建议

- 批量真实跑图时优先 `nt: 1`。
- NovelAI 会员标准图是否消耗 Anlas 受模型、尺寸、采样参数、reference/vibe、图片数量等影响；批量前先用 `--limit 1` 验证。
- `resolution: random_standard` 会在 `1024x1024`、`1216x832`、`832x1216` 中随机。需要可复现实验时显式指定 `square`、`landscape` 或 `portrait`。
- `run.resume: true` 适合长批次，失败后可以续跑。
- 需要控制总量时使用 `run.max_images` 或 CLI `--limit`。
- 对比旧 tags_machine 时，保留 `generation_result.json`、`png_params.json` 和原图路径，不要只看视觉结果。

## 8. 推荐工作流

### Agent 批量产完整 prompt

1. 外部 agent 根据角色、动作、场景产出一行一个 prompt 文件。
2. Batch YAML 使用 `prompt_file` + `composer: full`。
3. 先 `plan-batch` 看任务数。
4. `run-batch --limit 1 --full` 试一张。
5. 没问题后完整 `run-batch`。
6. 用 `inspect-batch` 和 `report.md` 看结果。

### 按动作分类文件夹跑样例

1. 在 `collections.actions` 中登记动作分类目录。
2. `select.characters` 选择一个或多个角色。
3. `select.actions` 使用 `collection` + `recursive`。
4. `expand.mode: product`。
5. 用 `max_tasks` 或 `limit` 控制第一轮验证数量。

### 对比旧 tags_machine

1. 旧项目先生成基准图。
2. core 使用同 prompt、同 artist、同 seed、同模型和尺寸跑图。
3. 使用 `inspect-image-params` 读取两边 PNG 参数。
4. 使用 `compare-render-params` 对比旧图和 core `generation_result.json`。
5. 人工打开图片检查主体、动作、镜头、画风是否一致。

## 9. 常见问题

### 为什么 `plan-batch` 后没有图片？

`plan-batch` 只展开任务，不调用 NovelAI。真实生图要用 `run-batch` 或 `resume-batch`。

### 为什么任务是 `requires_agent`？

`composer: agent` 需要 agent 结果或缓存。当前 core 不直接调用外部大模型；没有 cache 时会生成 agent task 并停止该任务。

### 为什么图片不在任务目录？

默认 `archive.copy_images: false`，图片保存在全局输出目录，任务目录只记录路径。需要复制图片进任务目录时设置：

```yaml
archive:
  copy_images: true
```

### 为什么 prompt 里角色词没有全部留在主 prompt？

NovelAI v4+ 支持 character captions。`character_prompts: auto` 时，renderer 会尝试根据 character 节点从 base prompt 中提取角色相关提示词，放到 NovelAI character captions 里。

### YAML 里的括号、花括号、方括号会不会影响权重提示词？

建议所有 prompt 字段都用引号包起来：

```yaml
prompt: "{akemi_homura}, (bare feet:1.2), [simple background]"
```

这样 `()`、`{}`、`[]` 都会作为普通字符串内容，不会被 YAML 当成结构语法。
