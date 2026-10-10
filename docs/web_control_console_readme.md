# PromptAtelier Web 使用说明

PromptAtelier Web 是 `tags_machine_core` 的本地控制台。前端负责节点选择、临时编辑、提示词预览、单张生成和 Compare 矩阵编排；节点读取、Composer、NovelAI Renderer、任务执行和结果归档仍由后端完成。

## 启动

在 `refactor` 目录执行：

```powershell
uv run python scripts\dev_web.py
```

启动命令默认执行受控重启：先关闭上一轮由本项目启动的 uvicorn、Vite、esbuild 等进程树，再使用相同端口启动新实例。实例信息记录在不会提交的 `runtime/dev_web.json`。

只停止服务、不重新启动：

```powershell
uv run python scripts\dev_web.py --stop
```

如果端口被其他项目或无法确认归属的进程占用，脚本会拒绝启动并打印 PID 和命令行，不会直接结束未知进程。需要改端口时仍可使用 `--backend-port` 和 `--frontend-port`。

启动后终端会打印前端地址。
开发脚本默认启用后端热重载，Python 源码更新后会自动重启 Uvicorn；如需关闭可传入 `--no-reload-backend`。

配置读取顺序：

1. `--config` 指定的文件。
2. `TAGS_MACHINE_CONFIG` 环境变量。
3. `configs/local.yaml`。
4. `configs/local.example.yaml`。

NovelAI token、旧提示词库路径和输出目录建议放在不会提交的 `configs/local.yaml`：

```yaml
legacy:
  design_root: "F:/my_project/new/tags_machine/design"

novelai:
  access_token: "你的 token"
  timeout: 120
  retry: 3

defaults:
  output_dir: "outputs"
```

## Custom 工作台

Custom 页由三列组成：

- `Nodes`：选择 Artist、Character、Action，管理主节点和 Compare 节点，设置 Negative 与生图参数。
- `Node Editor`：以 Form 或 JSON 编辑当前节点草稿。
- `Prompt & Generate`：预览最终提示词和参数，执行普通或 Compare 生图并查看结果。

页面输入保存在浏览器 `localStorage` 的 `promptatelier.custom-workspace/v1` 中。切换到 Batch/Results 或刷新浏览器不会清空节点、临时草稿和参数。运行中的 Compare Job 不写入 localStorage。

### 节点搜索

聚焦 Artist、Character 或 Action 搜索框后，会显示最多 6 个候选。输入关键字后等待约 300ms 即可缩小范围。界面只显示节点文件夹名，内部请求仍使用精确 `ref`，不会因为同名节点而读错路径。

每种节点都有一个 `Primary` 槽位。点击角色标题右侧的加号可增加任意数量的 `Compare` 槽位；Compare 槽位可单独删除。

### 节点编辑

选择节点后点击铅笔按钮，节点会在中间栏展开：

- `Form`：只展示当前节点源真正拥有的业务字段，不显示 `legacy`、路径、Renderer 快照或 Generation 等运行时字段。
- Artist 表单读取并保存 `tags.txt`；Action 的 Prompt 保存到 `tags.txt`，名称/描述等元数据保存到 `meta.yaml`，角色 `selected_keys` 保存到实际的 `action_profile.yaml` 或 `run-prompt-prompt.md`；Character 保存到 `meta.yaml`。
- `JSON`：查看和临时编辑生成链路使用的完整 `NodeDocument`，不会把整份运行时对象直接覆盖回源文件。
- Form 中的合法修改会在约 200ms 后更新当前运行草稿，下一次 Preview/Generate 自动使用，不需要额外应用按钮。只打开表单不会产生临时修改。
- JSON 中只有语法和节点结构合法的内容会更新运行草稿；无效 JSON 会保留在编辑器中并显示错误。
- `保存节点`：先调用 `/api/nodes/save-preview` 生成逐文件 Unified Diff；此时不会写盘。用户二次确认后才调用 `/api/nodes/save-commit` 写回原数据源。
- 保存确认前若任一源文件已被外部修改，后端返回 `source_changed` 并拒绝覆盖，需要重新生成 Diff。
- 浏览器中若存在升级前缓存的节点，首次点击编辑会重新读取源节点并补齐 Form；若后端进程仍是旧版本，界面会明确提示重启 Web 服务，不再把已有节点误显示成空白节点。
- `还原`：恢复到节点库中读入的原始内容。

临时修改只影响当前 Preview/Generate，并在节点名称后显示 `*`。确认保存成功后，当前源节点、运行草稿和 Form 基线会一起刷新。

### NodeDocument 字段

核心字段：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `schema` | 是 | 当前为 `tags-machine-core.node/v1`。 |
| `kind` | 是 | 节点类型，如 `artist`、`character`、`action`。必须与槽位类型一致。 |
| `id` | 是 | 节点稳定标识，不能为空。 |
| `name` | 否 | 界面显示名；为空时回退到 `id`。 |
| `description` | 否 | 节点说明，不直接参与提示词拼接。 |
| `prompt.positive[]` | 是 | 正向提示词片段，每项至少包含 `text`。 |
| `prompt.negative[]` | 是 | 负向提示词片段。 |
| `tags` | 否 | 结构化标签组，供 ScriptComposer 或规则读取。 |

Prompt 片段可选字段：

| 字段 | 含义 |
| --- | --- |
| `text` | 实际提示词文本。 |
| `role` | 语义角色，例如 `hair`、`upper_clothes`。 |
| `weight` | 结构化权重信息。 |
| `include_scopes` / `exclude_scopes` | ScriptComposer 的通用作用域条件。 |
| `notes` | 维护备注。 |

`legacy`、`generation` 等运行时扩展仍存在于 `NodeDocument`，但不会出现在源感知 Form，也不会因为保存 Form 被写进源文件。源文件中不属于当前表单的业务扩展字段会由对应 Adapter 保留。

### 普通 Generate

普通 `Preview` 和 `Generate` 只使用三个 Primary 节点：

1. 前端构造节点输入和生图参数。
2. `/api/compose-preview` 经过 Composer、NovelAI Renderer/Adapter，返回完整提示词与 `render_request`。
3. `Generate` 把 `render_request` 提交到 `/api/generate`。
4. 前端轮询 Job，并显示状态、图片、seed 和输出路径。

普通 Generate 使用界面中的 `NT`。`Negative` 默认是空字符串，`Seed=-1` 表示每次运行随机种子。临时节点和临时修改节点会在名称后显示 `*`。

### Compare Generate

Compare 使用每种角色下所有非空的 Primary 和 Compare 节点，展开笛卡尔积：

```text
图片数 = Artist 数量 × Character 数量 × Action 数量 × Behavior 数量 × NT
```

`Behavior 数量 = 1 + Prompt Behavior Compare 方案数量`。Primary Behavior 始终存在；没有新增 Compare 方案时，Behavior 数量就是 1，和旧版 Compare 数量一致。

某类节点完全为空时按一个 `null` 因子计算，但 Character 和 Action 至少要有一类存在。空白 Compare 槽位不会进入矩阵。

Compare 中的 `NT` 表示完整 Matrix 的执行组数，不是单次 NovelAI 请求的图片数。例如配置 2 个 Artist、1 个 Character、2 个 Action，`NT=3`，按钮会显示：

```text
Artist 2 × Character 1 × Action 2 × Behavior 1 × Groups 3 = 12
```

点击一次 `Compare Generate · 12` 会按 Group 顺序生成 12 个独立 Job。每个组合固定 `n_samples=1`，并针对 NovelAI 串行提交，避免同一账号并发生图触发 `429`；某个组合失败不会中止当前 Group 的其他组合或后续 Group。结果按 Group 展示 seed、进度、Artist、Character、Action、Behavior、Job 状态、图片和错误信息。

Compare 启动时会冻结当前生图参数。同一 Group 内所有组合共享 seed，不同 Group 使用不同 seed。若界面 Seed 为 `-1`，每组生成一个不同的随机 seed；若指定 Seed，则各组依次使用 `Seed + 0`、`Seed + 1`……。除 Artist/Character/Action/Behavior 组合外，宽高、Negative 和其他 Renderer 参数在整次 Compare 中保持一致。

Prompt Behavior 方案也遵循同一规则：同一 Group 内不同 Behavior 方案共享 seed，只有完整 Behavior 配置不同。普通 `Generate` 始终使用 Primary Behavior；当前选中的 Compare Behavior 可以用于 Preview，但只会在 `Compare Generate` 中实际批量执行。

每次点击 `Compare Generate` 都会创建一个独立父目录，并按 Group 建立子目录：

```text
outputs/compare_<timestamp>_<id>/
  group_001_seed_123456/
  group_002_seed_123457/
```

图片详情的左右切换顺序先遍历当前 Group 的 Matrix，再进入下一 Group。节点类型右侧的加号会镜像当前 Primary 节点；随后对 Compare 节点的临时修改不会改变 Primary。

旧 `design/画风` 下的 Artist 会通过 Artist 专用读取器载入，因此临时修改仍保留 `renderers.novelai` 中的 `gen_json`、negative prompt 和画风前后缀。升级前已缓存在浏览器中的旧 Artist 草稿需要重新选择一次节点，避免继续使用缺少 Renderer 信息的历史缓存。

### 图片详情与 PNG 元数据

普通 Generate 和 Compare Generate 成功后，点击任意缩略图会打开共享的图片详情窗口。左侧显示可缩放的大图，右侧显示尺寸、文件大小、修改时间、seed、模型、采样器、steps、scale、Prompt、Negative，以及可展开的完整 PNG Parameters 和 PNG Text。

详情中的元数据由后端在打开窗口时重新读取实际 PNG 文件，不使用前端生成请求或内存中的 `GenerationResult` 推断。点击 `打开所在文件夹` 会在 Windows 资源管理器中打开输出目录并选中当前图片；按 `Escape`、点击遮罩或右上角关闭按钮可退出详情窗口。

同一普通 Job 或同一轮 Compare 的图片会组成一个详情序列。使用左右箭头按钮或键盘 `←` / `→` 切换图片，首尾位置停住且不会循环。第二张开始会显示“当前 PNG 相对上一张 PNG”的参数 Diff，包括变更、新增和移除项；reference/vibe 图片只展示 hash 与大小摘要，不展示原始 base64。

## Prompt Behavior

Custom 工作台的 Prompt Behavior 与生图参数分开管理。

### Identity Minimal Sections

默认使用 Character 节点的 `meta.yaml.identity_minimal`，没有该字段时使用系统默认 section。

选择 `Override for this run` 后，可以从当前 Character 节点的 tags/Prompt roles 中选择 section，也可以输入自定义 section。覆盖模式至少保留一个 section，不能保存空列表。

### Character Prompts

NovelAI v4/v4.5 模型支持：

- `Auto`：Renderer 根据角色节点和最终 prompt 自动拆分 Character Prompts。
- `Off`：不拆分，角色提示词保留在 Base Prompt。

Auto 模式下可以开关 `Add male caption`。默认开启。

### Policy Rules

Web 不提供 Policy 模板选择，始终继承项目配置中的 `legacy_compat` 基线。每条规则使用三态：

- `Inherit`：使用项目配置。
- `Enabled`：本次运行开启该规则。
- `Disabled`：本次运行关闭该规则。

当前可覆盖规则包括：`tag_normalize`、`dedupe`、`character_section_filter`、`tag_conflict`、`character_count`、`clothing_policy`、`visibility_policy`、`character_extension`、`character_weight`。

Preview 会显示后端实际返回的 Policy baseline、Identity included/suppressed sections 和 Character Prompts 状态。Preview、普通 Generate、Compare Generate 使用同一份 Request Builder；普通 Generate 使用 Primary，Compare Generate 为每个组合使用对应的完整 Behavior 方案。

### Prompt Behavior Compare

点击 Prompt Behavior 标题右侧的加号，会完整镜像当前 Primary 方案并创建一个 Compare 方案。方案包含完整的 Identity、Character Prompts 和 Policy Rules 配置，可以独立改名、编辑和删除。

例如：

```text
Default              Primary
No Character Prompts Compare
```

此时 Compare 摘要会显示：

```text
Artist 1 × Character 1 × Action 1 × Behavior 2 × Groups 1 = 2
```

方案之间不会共享临时编辑状态。刷新页面后方案和当前选中方案会从浏览器 Workspace 缓存恢复；旧版本只有一份 `promptBehavior` 的 Workspace 会自动迁移为 Primary。

## 画风工坊（Style Lab）

画风工坊用来做画风复刻：读入一个作者语料，逐张检查原图能否按原参数重新生成，划分画风、编辑配方，导出成 artist 后再用它测试。完整规格见 [Style Lab 规格](style_lab_spec_v1.md)。

### 打开语料

- 在顶栏粘贴文件夹路径后点 `打开文件夹`。文件夹下有 `origin/` 时只扫描 `origin/`（`artist_parse/YYYYMMDD/<作者>/` 的标准结构），并跟随投稿目录的 junction。
- 也可以把一组图片直接拖进页面，自动建成一个"图片组"工作区，图片复制到 `runtime/stylelab/workspaces/<id>/uploads/`。
- 工作区数据写在 `<文件夹>/.stylelab/`，不会写进 `origin/`。重新打开同一文件夹会沿用原来的索引，只重新读取大小或修改时间变了的图片；点顶栏的刷新按钮可手动重扫。

### 浏览和筛选

- 中间按投稿分段显示缩略图，角标标出模型、vibe 数量和特殊情况（局部重绘、图生图、缺 vibe 图、角色参考、无元数据）。
- 左栏按模型、vibe 组合和标记筛选，可以一键隐藏重绘、图生图和无元数据的图片。窗口宽度小于 1280 时左栏自动收起。
- 选中图片后按 `←` / `→` 在当前筛选结果里切换。
- 点右栏的大图、对照里的原图和重生图、配方的原图或测试结果，或双击网格里的图，打开图片详情：适应窗口 / 原始大小，`←` / `→` 切换，显示尺寸、文件大小、修改时间、完整路径；`打开所在位置` 在资源管理器里打开文件夹并选中这张图，`复制路径` 复制完整路径。右栏标题旁的文件夹按钮也能直接打开所在位置。
- 网格下方是 `共性分析`，范围是当前分组和筛选出的图：
  - `推荐作为基准`：和其他图提示词重合度最高、参数和多数一致的三张，适合拿来新建配方。
  - 提示词和角色提示词按 `全部共有`、`多数有`、`少数有` 分层；同一个 tag 权重写法不一样时标 `权重不一`，悬停看各权重的张数。
  - 参数表列出模型、采样器、步数、CFG、vibe、负面等，不一致的行标黄并给出分布。尺寸是每次出图的设置，不参与比较。
  - 选中一张图时，最上面显示它和其他图的差异：默认和"多数"比（多出的是超过一半的其他图都没有的，缺少的是超过一半的其他图都有的），也可以点缩略图和某一张一对一比。差异包括提示词、角色提示词的增删、权重不同（按 `n::…::` 分段解析）和参数不同。双击缩略图改为选中那张。
  - `逐张差异`：每张图缺了哪些多数图都有的 tag、有哪些只有它有的 tag、哪些参数和多数不同。点一行选中那张图。

### 元数据和译文

右栏显示原图的提示词、角色提示词（v4 `char_captions`）、负面和参数。打开 `译文` 后每个 tag 下方显示中文。

译文由 `configs/local.yaml` 的 `llm` 段配置的 OpenAI 兼容接口生成：先试 `models.fast`，被拒（例如 NSFW 内容）再交给 `models.text`。每个 tag 单独缓存在 `runtime/llm_cache.sqlite`。打开工作区后后台会把全部提示词预翻译一遍，顶栏显示进度。没有配置 `llm` 时 `译文` 按钮不可用，其他功能照常。

### 原参重生

用原图的完整参数（包括 v4 角色提示词，vibe 从原图补回）直接出图，不经过 Composer，用来确认本地 NovelAI 链路正常。

- 张数 1–8，逐张串行提交。种子可选原图、随机或指定，多张时依次 +1；尺寸可选原图或自定义；`覆盖参数` 可单独改模型、采样器、调度、步数、CFG、CFG rescale。
- 每张出完自动和原图对照：参数差异（本次主动改动的参数默认隐藏）、提示词按 tag 显示增删、灰度相似度和 dHash 距离。结论分三档：`链路正常`、`参数一致，画面有差异`、`参数不一致`。
- 对照支持并排和滑块两种看法。结果保存在 `<文件夹>/.stylelab/runs/<run_id>/`，切换图片后可以回看历史记录。
- 常见的 NovelAI 错误（401 token 失效、402、429 限流）会直接给出处理办法，原始错误在鼠标悬停提示里。
- 原图元数据里客户端额外记的字段（如 NAI Smart Studio 另存的 `negative_prompt`、`char_prompts`、`cfg_scale`，以及 `tag_hint_*` 开关）重生时原样发出，NovelAI 不回写，对照时标为可忽略，不算参数不一致。NAI Smart Studio 还会在 Comment 里另存一份 `Description`、`Software`、`Source`、`Generation time`，同样属于这一类。勾选 `显示可忽略的差异` 后，同一原因的差异合并成一行，只列字段名，悬停看两边的值。
- 和上一次（同一张图）发给 NovelAI 的内容完全相同、且上一次还在跑或已经出完时，会先提示"结果也会一样"，点 `仍要生成` 才出图。失败、取消的可以直接重试。配方出图和导出测试也一样。

### 分组

左栏顶部是自动分组：按投稿把画师栈相近的归成一个画风家族，家族内再按稳定的画师变体（如"+azuuru"）、vibe 和模型细分，数字是投稿数。点分组只看这组的图片。

分组依赖 tag 分类，由打开工作区后的后台分析任务完成，顶栏显示进度，分析过程中分组会逐步变准。没有配置 LLM 时只能识别 `artist:` 前缀的画师。

### 配方

在右栏点 `从这张图新建配方` 进入配方工作区：左边是原图和所属分组的画风栈，中间是配方，右边是素材卡片。

划分画风：

- 整段原始提示词按原顺序平铺。点 token 之间的缝放分界线（先放前缀/主体线，再放主体/后缀线）。
- 或者选中 token（Shift 连选、Ctrl 多选）后按 `1` 前缀、`2` 主体、`3` 后缀、`X` 丢弃。
- `采用建议` 按 tag 类别和同组出现率自动划分；琥珀色虚线框是同组高频、但拿不准是画风还是内容的 token（如镜头词），需要自己判断。
- 鼠标悬停 token 可以看类别和同组出现率。划好后点 `锁定画风`。

编辑：

- 紫色是画风（导出到 artist），青色是主体（只用于测试）。选中 token 后按 `1`/`S` 进前缀、`2` 回主体、`3`/`Shift+S` 进后缀、`X` 丢弃；也可以直接拖动跨区或调顺序。
- 主体可以切到文本视图直接改：文字没变的 tag 保留原来的来源，新写的记为手打。`恢复原图主体` 只换主体，画风区不动。
- 锁定时画风区不能改文字；点 `解锁` 后可以文本编辑画风区，或回到划分视图重新划分。
- 角色提示词（单角色）可以用原图的 #1、手写，或从角色卡片填入；下面显示实际发送的角色提示词，渲染器按 `1boy` 等自动补的男角色会标出来。
- `实际发送` 显示的是正式出图链路算出的提示词和负面，和导出后的 artist 出图完全一致。
- 画风参数里可以改模型、采样器、步数、CFG 等，选择是否带原图的 vibe，以及是否追加项目默认质量词（复刻时默认关）。

素材架：

- 右栏分 `角色`、`动作` 两页。在搜索框里输入或点开下拉选素材；内容相同的副本目录（如 `xxx - 快捷方式`）合并成一条，标出合并了几份。
- 动作可以按 `classify.yaml` 的分类筛选：人数、类型、姿势、服装，`更多分类` 里还有细分、场景、氛围、元素、阶段，每个选项后面是数量。
- 选中的素材放在下面的素材块里，随配方保存，换了搜索词也还在。
- 素材块里先点 tag 筛掉不要的（划掉的不会加入），再 `加入主体`；也可以把整块拖进主体的任意位置，或拖到角色提示词（角色卡替换 #1，动作卡追加）。已经加进去的块，再筛 tag 会同步增删。
- 主体里来自同一块素材的 tag 用虚线框圈在一起，框上的 `×` 一键移出；素材块上的 `×` 连同它加进主体和角色提示词的 tag 一起拿掉。主体里原有的同名 tag 保留。
- 以前直接从卡片加进主体的 tag 列在素材架下面，可以 `放上素材架` 接着编辑，或一键移出。
- 来自角色卡的 tag 左边是橙色条，来自动作卡的是蓝色条。
- 角色提示词的 `主体里有 1boy 等男性计数时自动补男角色提示词` 默认不勾选。

保存与出图：

- `Ctrl+S` 保存，每次保存版本号加一。
- 没保存的修改会备份在浏览器里，刷新或误关页面后重新打开会提示恢复。
- `生成` 会先保存再出图，结果和原图并排或滑块对照，记录配方版本。

### 导出 artist 与测试

配方页下方的 `导出与测试`：

- `导出 artist…` 会先保存配方，再打开导出对话框。填画风名（英文，下划线分词，如 `Crisp_Manga_Ink`），作者 id 默认是语料目录名。
- 对话框显示目标目录、tags.txt 内容、和已有画风的差异（默认对比上一次导出，或同作者最接近的画风），以及读回校验结果。读回校验不通过不能导出。
- 同名目录已存在时导出为并列版本（`_v2`……），不会覆盖。导出过的版本列在面板里；配方之后又改过会标出来。
- 选一个导出的 artist 后可以测试：
  - `回归对照`：从同组原图里挑几张（默认 4 张，可点缩略图增减），去掉画风后用导出的 artist 按原种子、原尺寸重画，逐张和原图对照，显示平均相似度。展开 `内容提示词` 可以看实际用的内容和去掉了哪些画风 token。
  - `泛化矩阵`：从提示词库选角色（行）和动作（列），共用一个种子出图，看画风换了内容还稳不稳。

## Batch

Batch 页继续使用现有 BatchPlanner 和 BatchExecutor。可以编辑 inline batch 参数，也可以指定 Batch YAML；`Plan Preview` 与真实运行使用同一套规划链路。

## Results

Results 页读取后端结果索引。单次生成的 `GenerationResult` 通常包含：

- `images[]`：图片路径、文件名和图片级 meta。
- `request_body`：实际发送到 NovelAI 的请求参数。
- `png_info`：写入或读取到的 PNG 参数。

Batch 结果还包含 `run_dir`、`output_dir`、任务状态、`prompt_bundle.json`、`render_request.json`、`generation_result.json` 和参数图等归档文件。

## 验证命令

```powershell
uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_compose tests.test_web_results tests.test_web_batch tests.test_novelai_artist_dedup -v
uv run python -m pytest tests/test_style_lab.py tests/test_web_style_lab.py tests/test_llm_client.py tests/test_prompt_tokens.py tests/test_novelai_character_prompts.py -q

cd web
npm run test
npm run build
```
