# PromptAtelier Web 使用说明

PromptAtelier Web 是 `tags_machine_core` 的本地控制台。前端负责节点选择、临时编辑、提示词预览、单张生成和 Compare 矩阵编排；节点读取、Composer、NovelAI Renderer、任务执行和结果归档仍由后端完成。

## 启动

在 `refactor` 目录执行：

```powershell
uv run python scripts\dev_web.py --backend-port 8877
```

启动后终端会打印前端地址。当前机器的 `8765` 位于 Windows 保留端口范围内，推荐固定使用 `8877`。

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

- `Form`：编辑基础字段、Prompt、Negative Prompt、Tags 和扩展字段。
- `JSON`：编辑完整 `NodeDocument`；与 Form 共用同一份草稿。
- `应用到本次运行`：校验节点后更新当前工作台草稿，不修改磁盘文件。
- `保存节点`：显式调用 `/api/nodes/save`，写入节点库的 `meta.yaml`。
- `还原`：恢复到节点库中读入的原始内容。

关闭或切换节点时，如果存在尚未应用的修改，界面会先确认。新建空白节点与编辑已有节点使用同一套临时草稿机制；空白节点保存前需要填写节点库内的目标 `ref`。

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

除核心字段外，`legacy`、`agent`、`composition`、`generation`、`clothing` 等扩展对象会在 Form/JSON 切换和保存时原样保留。

### 普通 Generate

普通 `Preview` 和 `Generate` 只使用三个 Primary 节点：

1. 前端构造节点输入和生图参数。
2. `/api/compose-preview` 经过 Composer、NovelAI Renderer/Adapter，返回完整提示词与 `render_request`。
3. `Generate` 把 `render_request` 提交到 `/api/generate`。
4. 前端轮询 Job，并显示状态、图片、seed 和输出路径。

普通 Generate 使用界面中的 `NT`。`Negative` 默认是空字符串，`Seed=-1` 表示不固定种子。

### Compare Generate

Compare 使用每种角色下所有非空的 Primary 和 Compare 节点，展开笛卡尔积：

```text
图片数 = Artist 数量 × Character 数量 × Action 数量
```

某类节点完全为空时按一个 `null` 因子计算，但 Character 和 Action 至少要有一类存在。空白 Compare 槽位不会进入矩阵。

例如配置 2 个 Artist、1 个 Character、2 个 Action，按钮会显示：

```text
Artist 2 × Character 1 × Action 2 = 4
```

点击一次 `Compare Generate · 4` 会生成 4 个独立 Job。每个组合固定 `n_samples=1`，并针对 NovelAI 串行提交，避免同一账号并发生图触发 `429`；某个组合失败不会中止其他组合。结果卡会显示 Artist、Character、Action、Job 状态、seed、图片和错误信息。

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

cd web
npm run test
npm run build
```
