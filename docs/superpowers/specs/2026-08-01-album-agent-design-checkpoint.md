# 图集 Agent 编排阶段性设计检查点

> 已归档：当前正式规范已迁移到 `design/动作改2/docs/superpowers/specs/2026-08-05-derived-story-set-album-plan-design.md`。
> 本文保留用于追溯早期决策。特别是下文的 `composer: full` 已失效：final AlbumPlan 必须使用 AgentComposer，完整 `frame.prompt` 作为已完成的 Agent 结果传入，不走 ScriptComposer。

> 状态：设计中，仅记录已经确认的决策。
>
> 本文不是实现计划，也不表示功能已经开发完成。后续完整 spec 将在本文基础上补充检索、校验、错误处理和验收细节。

## 1. 目标

让 Agent 更好地利用 `design/动作改2` 动作提示词库，编排一组具有主题变化或剧情连续性的图集，并最终复用现有 refactor 生图链路。

图集支持两种意图：

- `theme`：围绕同一主题做动作、镜头和场景变化。
- `story`：按开始、发展、高潮、收束等阶段形成连续叙事。
- `hybrid`：默认模式，允许同时具备主题变化和轻量剧情推进。

## 2. 已确认的产品边界

### 2.1 动作节点是参考，不是硬约束

Agent 应优先检索并利用现有动作节点，但不要求每个 Frame 都必须引用动作节点。

每个 Scene 可以使用动作节点建立物理基础；Scene 下的 Frame 可以：

- 继续使用该动作；
- 轻量改写该动作；
- 组合多个动作节点；
- 在需要过渡镜头时完全原创。

动作库原始文件不被覆盖，Agent 的改写只记录在图集计划中。

动作来源类型暂定为：

```yaml
action_source:
  type: catalog | derived | original
  refs: []
  summary: "本页如何使用或改写动作来源"
```

### 2.2 Artist 不属于 AlbumPlan

`AlbumPlan.yaml` 是创意内容计划，不包含 artist、后端、分辨率、数量和输出目录。

画风和生图参数在执行阶段通过独立的 render profile 提供：

```text
AlbumPlan.yaml + AlbumRenderProfile.yaml
-> compiled_batch.yaml
-> 现有 BatchRunner
```

同一份图集计划可以使用不同 artist 重新编译和生成。

### 2.3 Agent 输出双格式

- `AlbumPlan.yaml`：机器执行的正式计划。
- `album.md`：从 YAML 生成的人类审阅版本。

YAML 是唯一事实源，Markdown 不能反向修改计划。

### 2.4 计划保存来源和冻结 prompt

每个 Frame 同时保存：

- 可选的动作来源引用和内容 hash；
- Agent 的轻量改写说明；
- 最终完整 positive prompt；
- 最终完整 negative prompt。

这样既能追溯动作库来源，也能冻结本次图集方案，不受动作库后续变化影响。

### 2.5 页数和执行确认

支持：

- `fixed`：固定页数；
- `range`：给出最小和最大页数；
- `auto`：由 Agent 决定，但必须有最大页数。

默认流程先生成并审阅 `AlbumPlan.yaml` / `album.md`，只有显式确认后才编译和真实执行。后续可以提供自动执行开关。

## 3. 已确认的架构边界

```text
中文 album Skill
  -> album CLI / AlbumPlanner
      -> ActionCatalog
      -> ActionSearchService
      -> AlbumPlanValidator
      -> AlbumMarkdownRenderer
      -> AlbumBatchCompiler
  -> 现有 BatchRunner
  -> GenerationService
  -> Renderer
  -> NovelAI
```

职责约定：

- Skill：指导 Agent 理解需求、查询候选、组织 Phase/Scene/Frame 和输出计划。
- ActionCatalog：读取动作库并建立机器可查询索引。
- AlbumPlanner：准备查询材料和图集规划上下文，不直接调用模型。
- AlbumPlanValidator：校验引用、页数、结构、明显兼容冲突和重复风险。
- AlbumMarkdownRenderer：从正式 YAML 生成审阅文档。
- AlbumBatchCompiler：将每页编译成普通 BatchTask。
- AgentComposer：继续负责原有单图 Agent 拼接链路，不负责动作检索和图集排序。
- BatchPlanner：继续负责普通批量展开，不重新随机选择 AlbumPlan 中的动作。

> 历史失效说明：本 checkpoint 原先将完整 Prompt 映射为 `composer: full`，该方案已废弃。
> 当前规范要求 AlbumPlan 任务使用 `composer: agent`，将完整 `frame.prompt` 作为已完成的 Agent 结果传入，
> 从而保留 AgentComposer 的节点快照、缓存、归档、retry 和 resume 语义。Artist 仍由 Batch 运行配置提供。

## 4. 知识库和 Skill 的复用方案

### 4.1 继续复用

- 节点目录内的 `classify.yaml`：动作分类事实源。
- 节点目录内的 `meta.yaml`：正式动作 prompt 和节点元数据。
- `kb/generated/*.md`：人工阅读索引。
- `.agents/skills/agent-director-workflow`：Phase/Scene/Frame 导演方法参考。
- `.agents/skills/storyboard-tuning-master`：后续逐帧真实出图调优参考。

### 4.2 新增和调整

新增正式入口：

```text
design/动作改2/.agents/skills/album-director/SKILL.md
```

父项目 `skills/` 只提供薄入口，不复制完整规则。

程序索引生成在 `refactor/cache/action_catalog/` 或图集工作目录，不写回 `design/动作改2`，避免刷新动作库污染 Git。

`st_*` 和 `new` 都作为动作节点来源，使用完全相同的扫描、校验、索引和查询规则。目录名只记录来源，不改变节点行为。

当前默认检测范围通过配置声明：

```yaml
knowledge_base:
  sources:
    - id: action_new
      path: new
      enabled: true

    - id: legacy_action_folders
      pattern: st_*
      enabled: true
```

其中：

- 配置了且 `enabled: true` 的来源，参与元数据扫描、分类校验、质量报告、索引构建和正常查询。
- `new` 不再有 staging 特殊行为，可以被 Agent、Batch 和图集编排正常选取。
- `pn_*`、`story_*` 等目录当前不在默认范围内，是否加入只通过配置决定。

因此当前默认检测范围和候选范围都是 `new/ + st_*`。

知识库导入采用“宽进严告警”：配置来源中的节点尽量写入统一索引，缺少文件、字段不一致或内容无法解析时记录 warning，不因为单个节点问题阻断全量导入，也不额外用 `incomplete` 状态过滤普通查询。完全无法读取的文件仍保留来源记录，并在 warning 中说明无法读取的字段。

## 5. Catalog 字段归一化

Catalog 只生成派生数据，不回写源目录。源文件中的 prompt、括号权重、正负面内容和字段顺序保持不变。

### 5.1 classify.yaml

正式分类字段仍以现有 `classify.yaml` v1 为准：

```text
标量：phase、species、cast、tone、clothing
列表：domain、pose、environment、flags
映射：subtype
```

Catalog 归一化规则：

- 列表字段接受字符串、列表或空值，统一输出字符串列表。
- 字符串只做 trim 和大小写/分隔符的搜索副本归一化，不修改源值。
- `subtype` 的 key 不在 `domain` 中时记录 warning，仍保留原值。
- 未知枚举值记录 warning，仍保留原值，不丢弃节点。
- 不从文件名、目录名或 prompt 词面反推缺失分类。
- `classify.node_id` 与 `ref` 不一致时记录 warning，`ref` 仍以物理相对路径为准。

### 5.2 meta.yaml

Catalog 读取以下正式字段：

```text
schema、kind、id、name、description
tags.action、negative_prompt、character_scope
```

规则：

- `tags.action` 的字符串和列表都归一化为搜索词列表，但保留完整原始 prompt 的路径和 hash。
- `negative_prompt` 只记录存在性、数量和 hash，不把负面词当正向分类证据。
- `character_scope` 用于图集镜头和 ScriptComposer 查询；未知 scope 记录 warning。
- `meta.clothing` 与 `classify.clothing` 不一致时记录 warning，分类查询以 `classify.yaml` 为准。
- `legacy` 只作为审计字段读取，不再作为知识库分类来源。
- YAML 中的 `()`, `{}`, `[]` 权重和 NovelAI 语法不做字符串规则解释，按 YAML 已解析的字符串/列表保存。

### 5.3 warning code

统一 warning code 暂定为：

```text
missing_file
parse_error
schema_mismatch
kind_mismatch
id_mismatch
invalid_enum
subtype_domain_mismatch
meta_classify_mismatch
empty_action_prompt
unsupported_prompt_shape
duplicate_content
```

所有 warning 都写入 Catalog 记录和独立的 `warnings.jsonl`。warning 不阻止整批导入，也不自动修复源文件。

## 6. 重复节点和查询契约

### 6.1 重复节点

重复判断不依赖目录优先级，而依赖文件内容 hash：

- `tags/classify/meta` 三者内容完全相同：归入同一个 `alias_group`。
- 每个物理来源仍保留自己的 `ref`，来源不会互相覆盖。
- 默认搜索每个 `alias_group` 只展示一个稳定代表。
- `show` 默认展示代表，使用 `--all-sources` 时展示全部物理来源。
- prompt 相同但 `classify.yaml` 不同：不合并，只记录 `duplicate_content` 或分类差异 warning。
- 代表选择使用稳定排序，不依赖扫描顺序，避免每日刷新后结果漂移。

### 6.2 Catalog 查询命令

正式命令暂定为：

```powershell
uv run python -m tags_machine_core kb import --config configs/knowledge_base.yaml
uv run python -m tags_machine_core kb audit --config configs/knowledge_base.yaml
uv run python -m tags_machine_core kb facets
uv run python -m tags_machine_core kb search --domain foot --cast solo --limit 20 --format json
uv run python -m tags_machine_core kb search --source new --text "foot focus"
uv run python -m tags_machine_core kb show "st_rp/021_action" --format json
```

查询规则：

- 不同字段之间默认 `AND`。
- 同一字段的多个值默认 `OR`，例如 `cast=solo,1boy1girl`。
- `domain`、`flags`、`environment` 支持包含匹配。
- `--text` 搜索 `id/name/description/tags.action` 的正向摘要，不搜索 `negative_prompt`。
- 搜索默认只返回摘要，`show` 才读取并返回完整 `meta.yaml` 内容。
- 默认限制返回数量，Agent 需要更多候选时必须显式传入 `--limit`。

搜索结果至少包含：

```json
{
  "schema": "tags-machine-core.action-search-result/v1",
  "catalog_hash": "sha256:...",
  "query": {},
  "results": [
    {
      "ref": "st_rp/021_action",
      "id": "021_action",
      "score": 8.4,
      "classification": {},
      "action": {
        "character_scope": "foot_detail",
        "description": "..."
      },
      "alias_count": 2,
      "warnings": []
    }
  ]
}
```

Agent 使用顺序固定为：

```text
facets -> search -> 选择少量候选 -> show -> 写入 AlbumPlan
```

旧 `kb/legacy_modules/`、`kb/module_registry.yaml` 和 `by_legacy_folder.md` 不再作为 Agent 的活动知识层。来源相对路径可以作为索引中的技术字段，用于物理目录筛选和审计，但不参与动作语义判断。

现有 `kb/generated` 只作为阅读资料，不作为运行时唯一查询源。当前索引记录数与实际节点数存在差异，后续必须由新索引刷新流程解决。

## 5. 暂未冻结的内容

以下内容进入下一轮设计，不在本检查点中假定已经确定：

- `AlbumPlan.yaml` 的最终字段和版本细节；
- ActionCatalog JSONL 的完整字段；
- 搜索命令和 Skill 命令模板；
- exact / supplementable / conflict 的兼容判定细则；
- Scene/Frame 去重和连续性警告；
- AlbumPlanning cache 的具体文件结构；
- 校验报告和真实 NovelAI 业务验收用例；
- 是否复用现有 batch 的 `require` 配置。

## 6. 下一步

1. 完成检索、兼容、去重和缓存设计。
2. 补充错误处理、CLI 契约和业务验收标准。
3. 将本检查点扩展为正式设计 spec。
4. 用户确认正式 spec 后，再编写实现计划和开发代码。
