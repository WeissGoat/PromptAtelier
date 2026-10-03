# Action Knowledge Base v1 设计规格

## 1. 状态

本文是 `design/动作改2` 动作知识库的正式 v1 设计规格，覆盖配置来源、Catalog 导入、字段归一化、warning、重复节点、查询接口和业务验收。

本规格已经过逐段讨论确认。后续实现以本文为准；早期讨论记录见 `2026-08-01-album-agent-design-checkpoint.md`。

## 2. 目标

为 Agent、Batch 和后续图集编排提供一个稳定、紧凑、可查询的动作知识库，而不是让调用方直接遍历数千个节点目录或读取大型 Markdown 索引。

核心数据流：

```text
design/动作改2/new + design/动作改2/st_*
-> KnowledgeBaseImporter
-> versioned ActionCatalog
-> kb facets/search/show/audit
-> Agent / Batch / AlbumPlanner
```

## 3. 非目标

本阶段不实现：

- `AlbumPlan.yaml`、图集 Markdown 或 Batch 编译。
- 外部 Agent 模型调用。
- Prompt 自动改写或分类自动修复。
- `pn_*`、`story_*` 等未配置目录的自动发现。
- 删除源节点、移动目录或回写 `tags.txt/classify.yaml/meta.yaml`。
- 删除历史 `kb/legacy_modules` 文件；它们不再被运行时和 Agent 查询消费，但物理清理另行处理。

## 4. 唯一事实源

每个动作节点最多由三个文件组成：

```text
tags.txt       原始提示词素材
classify.yaml  分类事实源
meta.yaml      正式 action 节点和执行素材
```

职责边界：

- `classify.yaml` 决定 `phase/species/cast/domain/subtype/pose/environment/tone/flags/clothing`。
- `meta.yaml` 提供 `id/name/description/tags.action/negative_prompt/character_scope`。
- `tags.txt` 用于原始内容审计和 hash，不覆盖结构化分类。
- 目录名只记录来源路径，不推断动作语义。
- `negative_prompt` 不进入正向全文检索。

旧模块 Markdown、`module_registry.yaml` 和 `by_legacy_folder.md` 不属于活动知识层。

## 5. 配置契约

默认配置文件：

```text
configs/knowledge_base.example.yaml
```

Schema：

```yaml
schema: tags-machine-core.knowledge-base/v1
action_root: "F:/my_project/new/tags_machine/design/动作改2"
catalog_dir: "cache/action_catalog"

sources:
  - id: action_new
    path: new
    enabled: true

  - id: legacy_action_folders
    pattern: st_*
    enabled: true
```

规则：

- `action_root` 可以是绝对路径，也可以相对配置文件所在目录解析。
- `catalog_dir` 可以是绝对路径，也可以相对配置文件所在目录解析。
- 每个 source 必须有唯一非空 `id`。
- `path` 和 `pattern` 必须且只能提供一个。
- `path` 解析为 `action_root` 下的一个目录。
- `pattern` 只在 `action_root` 第一层执行 glob，匹配到的每个目录作为扫描根。
- 所有解析结果必须位于 `action_root` 内。
- `enabled: false` 的来源完全忽略。
- 当前默认范围是 `new/ + st_*`；`pn_*`、`story_*` 不自动加入。
- 已配置来源使用完全相同的导入、warning 和查询规则。

## 6. 节点发现

Importer 递归扫描每个已解析 source root。

当目录中至少存在以下一个文件时，该目录形成一条 Catalog 记录：

```text
tags.txt
classify.yaml
meta.yaml
```

规则：

- 分类根目录自身没有节点文件时不形成记录。
- 如果多个 source 配置命中同一物理目录，只导入一次并记录 `duplicate_source_match` warning。
- `ref` 固定为节点目录相对 `action_root` 的 POSIX 路径，例如 `st_rp/021_action`。
- `id` 优先使用可读取的 `meta.yaml.id`，否则使用目录名。
- 导入不修改源目录。

## 7. Catalog 存储

Catalog 使用版本目录和原子指针：

```text
cache/action_catalog/
  current.json
  builds/
    <catalog_hash>/
      manifest.json
      actions.jsonl
      warnings.jsonl
```

`current.json`：

```json
{
  "schema": "tags-machine-core.action-catalog-pointer/v1",
  "catalog_hash": "sha256:...",
  "build": "builds/<catalog_hash>"
}
```

导入流程：

1. 在临时目录生成完整 build。
2. 对排序后的 Catalog 记录计算稳定 `catalog_hash`，计算内容不包含时间戳和绝对机器路径。
3. 将临时目录原子移动为 `builds/<catalog_hash>`；相同 hash 的 build 已存在时直接复用。
4. 最后原子替换 `current.json`。

任一步骤失败时，不修改现有 `current.json`。

## 8. Catalog 记录

`actions.jsonl` 每行一个 `ActionCatalogItem`：

```json
{
  "schema": "tags-machine-core.action-catalog-item/v1",
  "ref": "st_rp/021_action",
  "id": "021_action",
  "kind": "action",
  "source": {
    "root_id": "legacy_action_folders",
    "relative_path": "st_rp/021_action",
    "group": "st_rp"
  },
  "files": {
    "tags_path": "st_rp/021_action/tags.txt",
    "classify_path": "st_rp/021_action/classify.yaml",
    "meta_path": "st_rp/021_action/meta.yaml",
    "tags_hash": "sha256:...",
    "classify_hash": "sha256:...",
    "meta_hash": "sha256:...",
    "content_hash": "sha256:..."
  },
  "classification": {
    "phase": "core",
    "species": "human",
    "cast": "1boy1girl",
    "domain": ["sex"],
    "subtype": {"sex": ["penetration"]},
    "pose": ["lying"],
    "environment": ["bed"],
    "tone": "normal",
    "flags": [],
    "clothing": "nude"
  },
  "action": {
    "name": "021_action",
    "description": "...",
    "character_scope": "default",
    "positive_terms": ["penetration", "lying", "bed"],
    "negative_terms_count": 12,
    "negative_hash": "sha256:..."
  },
  "alias_group": "sha256:...",
  "canonical_ref": "st_rp/021_action",
  "aliases": ["st_rp/021_action"],
  "warnings": []
}
```

完整 positive/negative prompt 不进入 `search` 摘要输出。`show` 根据记录中的源文件路径读取并返回完整内容。

## 9. 归一化规则

### 9.1 classify.yaml

标量字段：

```text
phase species cast tone clothing
```

列表字段：

```text
domain pose environment flags
```

映射字段：

```text
subtype
```

规则：

- 标量空值输出 `null`。
- 列表字段接受标量、列表或空值，统一输出去空、保序去重的字符串列表。
- 搜索副本使用 `casefold`、下划线转空格和连续空白折叠；源值不回写。
- `subtype` 每个 value 接受标量、列表或空值并统一为字符串列表。
- `subtype` key 不在 `domain` 时记录 warning，仍保留值。
- 不从目录名、文件名或 prompt 推断缺失分类。
- 未知枚举记录 warning，仍保留值。

稳定枚举校验范围：

```text
phase: start pre core climax post
species: human human_xeno human_tentacle
cast: solo 1boy1girl 1boy2girls 1boy3girls 2girls 3girls
      multi_boys1girl multi_boys2girls multi_boys3girls multi_boys_multi_girls
domain: sex body foot mouth breast crotch yuri sfw
tone: normal forced affectionate
clothing: clothed nude specific_outfit
```

`pose/environment/flags/subtype` 的值允许扩展，v1 不做完整枚举拒绝。

### 9.2 meta.yaml

Importer 读取：

```text
schema kind id name description tags.action negative_prompt character_scope clothing.state
```

规则：

- `tags.action` 接受字符串、列表或空值。
- 正向搜索词来自 `tags.action`，按逗号拆分后建立归一化副本；原始字符串和 NovelAI 权重不回写。
- `negative_prompt` 接受字符串、列表或空值，只计算数量和 hash，不进入正向搜索。
- `character_scope` 未知时记录 warning，仍保留值。
- `classify.clothing` 与 `meta.clothing.state` 不一致时记录 warning，Catalog 分类字段以 `classify.yaml` 为准。
- `legacy` 只用于审计，不参与分类。

允许的 `character_scope`：

```text
default full_body upper_body lower_body portrait face_detail hand_detail foot_detail object_focus
```

## 10. Warning 契约

Catalog 导入采用“宽进严告警”：单个节点问题不阻断全量导入，也不自动修复源文件。

Warning 结构：

```json
{
  "ref": "new/example_action",
  "file": "classify.yaml",
  "code": "missing_file",
  "message": "缺少 classify.yaml",
  "details": {}
}
```

正式 warning code：

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
duplicate_source_match
source_missing
```

行为：

- 缺文件：建立记录并 warning。
- YAML 解析失败：建立最小来源记录并 warning。
- 字段类型异常：保留可读取字段并 warning。
- 完全无法读取源文件：保留来源路径并 warning。
- 导入有 warning 仍返回成功退出码。
- 配置文件无法解析、action root 越界、Catalog 原子发布失败属于命令级失败。

## 11. Alias 规则

- `content_hash` 由三个文件的存在性和内容 hash 组成。
- `content_hash` 完全相同的记录属于同一个 `alias_group`。
- 每个物理 `ref` 都保留。
- `canonical_ref` 为 alias group 内按 POSIX ref 字典序排序后的第一项。
- 默认搜索每组只展示 canonical record。
- `--all-sources` 展示全部 alias。
- prompt 相同但 classify 不同不进入同一 alias group，并记录 `duplicate_content` warning。

## 12. CLI 契约

```powershell
uv run python -m tags_machine_core kb import --config configs/knowledge_base.example.yaml
uv run python -m tags_machine_core kb audit --config configs/knowledge_base.example.yaml
uv run python -m tags_machine_core kb facets --config configs/knowledge_base.example.yaml
uv run python -m tags_machine_core kb search --config configs/knowledge_base.example.yaml --domain foot --cast solo --limit 20 --format json
uv run python -m tags_machine_core kb search --config configs/knowledge_base.example.yaml --source new --text "foot focus"
uv run python -m tags_machine_core kb show --config configs/knowledge_base.example.yaml "st_rp/021_action" --format json
```

### 12.1 import

输出 schema：`tags-machine-core.kb-import-result/v1`。

至少包含：

```text
catalog_hash build_dir record_count alias_group_count warning_count reused_build
```

### 12.2 audit

输出当前 build 的 warning 汇总和完整 warning 列表。

### 12.3 facets

按 source、phase、species、cast、domain、subtype、pose、environment、tone、flags、clothing、character_scope 输出计数。

### 12.4 search

- 不同字段之间是 `AND`。
- 同一字段逗号分隔值是 `OR`。
- 支持 `source/phase/species/cast/domain/subtype/pose/environment/tone/flags/clothing/character_scope/text`。
- `text` 搜索 `id/name/description/positive_terms`，不搜索 negative。
- 默认 `limit=20`，必须大于等于 1。
- 排序为 score 降序、ref 升序。
- 没有结果时成功返回空数组。
- 默认隐藏 alias；`--all-sources` 展示全部来源。

输出 schema：`tags-machine-core.action-search-result/v1`。

### 12.5 show

- 只接受精确 `ref`，不存在时命令失败，不做模糊回退。
- 返回 Catalog 摘要、完整 `classify.yaml` mapping、完整 `meta.yaml` mapping、原始 `tags.txt` 文本和所有 warning。
- 源文件在导入后被删除时返回 `source_missing`，不静默使用其他目录猜测。

## 13. 日志

- `INFO`：配置路径、解析 source 数、发现节点数、复用/新建 build、Catalog 路径和耗时。
- `WARNING`：按 code 汇总 warning 数量；默认不逐条刷屏。
- `DEBUG/TRACE`：逐节点 ref、hash、alias 分组和解析细节。
- CLI JSON 输出写 stdout；日志写 stderr，保证 Agent 可以稳定解析 JSON。

## 14. 与现有模块的边界

- 不修改 `AgentComposer`、`ScriptComposer`、`PromptPolicyPipeline`、Renderer 或 BatchPlanner。
- 不改变现有 `node_pools` 扫描行为。
- Knowledge Base v1 新增独立 `tags_machine_core.knowledge_base` 包。
- 后续 AlbumPlanner 只通过 Catalog API/CLI 查询，不直接扫描 `design/动作改2`。

## 15. 业务验收

使用真实目录 `F:/my_project/new/tags_machine/design/动作改2`：

1. 默认配置只展开 `new/ + st_*`。
2. `pn_*`、`story_*` 不进入 Catalog。
3. `new/` 和 `st_*/` 使用相同记录结构和 warning 规则。
4. 全量导入遇到坏节点仍完成，并输出 warning 汇总。
5. 连续两次导入未修改数据时 `catalog_hash` 相同，第二次 `reused_build=true`。
6. `facets` 返回实际分类计数。
7. `search` 能查询 `cast/domain/phase/clothing/character_scope`。
8. `text` 能匹配正向 prompt，但不能仅因 negative 命中而返回。
9. `show` 保留完整 NovelAI 权重和正负面 prompt。
10. 重复节点 alias 展示稳定，`--all-sources` 可展开。
11. 随机抽查至少 10 个 `new` 和 10 个 `st_*` 结果，`ref/classification/action` 与源文件一致。
12. 导入和查询过程不修改 `design` Git 工作区。

业务验收结果写入：

```text
docs/knowledge_base_business_acceptance_YYYYMMDD.md
```
