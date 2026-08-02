# Action Knowledge Base v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `design/动作改2/new` 与 `design/动作改2/st_*` 建立可版本化、可查询、宽进严告警的 Action Catalog，并提供 `kb import/audit/facets/search/show` 命令。

**Architecture:** 新增独立 `tags_machine_core.knowledge_base` 包。Importer 只读取配置声明的动作目录，将源文件归一化为稳定 JSONL Catalog，经内容 hash 发布到版本目录；CatalogReader 只消费当前 build，CLI 负责结构化输出和错误码，不改动 Composer、Policy、Renderer、BatchPlanner 或源节点。

**Tech Stack:** Python 3.11、Pydantic 2、PyYAML、argparse、JSON Lines、pytest。

## Global Constraints

- 事实源固定为 `classify.yaml`、`meta.yaml`、`tags.txt`，不消费旧 Markdown 知识层。
- 默认只导入 `new/` 与第一层 `st_*`；`pn_*`、`story_*` 不自动加入。
- 坏节点只产生 warning，不阻断全量导入；配置错误和原子发布失败返回命令失败。
- 不修改 `design/动作改2` 的任何文件。
- 日志写 stderr，JSON/YAML 结果写 stdout。
- 注释使用中文；实现保持独立，不影响现有 AgentComposer 链路。

---

### Task 1: 配置、模型与归一化

**Files:**
- Create: `src/tags_machine_core/knowledge_base/__init__.py`
- Create: `src/tags_machine_core/knowledge_base/models.py`
- Create: `src/tags_machine_core/knowledge_base/config.py`
- Create: `src/tags_machine_core/knowledge_base/normalization.py`
- Create: `tests/test_knowledge_base_config.py`
- Create: `tests/test_knowledge_base_normalization.py`

**Interfaces:**
- Consumes: YAML 配置路径、源 YAML/text 内容。
- Produces: `KnowledgeBaseConfig`、`CatalogWarning`、`ActionCatalogItem`、`load_knowledge_base_config()`、`normalize_classification()`、`normalize_meta()`。

- [ ] **Step 1: 编写配置与归一化测试**

覆盖相对路径、`path/pattern` 互斥、source id 唯一、根目录越界、列表字段标量转列表、未知枚举 warning、`tags.action`/negative 的字符串与列表形态。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_knowledge_base_config.py tests/test_knowledge_base_normalization.py -q`

Expected: 因 `tags_machine_core.knowledge_base` 尚不存在而失败。

- [ ] **Step 3: 实现配置、Pydantic 模型和纯归一化函数**

关键签名：

```python
def load_knowledge_base_config(path: str | Path) -> KnowledgeBaseConfig: ...

def normalize_classification(
    raw: object,
    *,
    ref: str,
) -> tuple[ActionClassification, list[CatalogWarning]]: ...

def normalize_meta(
    raw: object,
    *,
    ref: str,
) -> tuple[NormalizedActionMeta, list[CatalogWarning]]: ...
```

- [ ] **Step 4: 运行聚焦测试**

Run: `uv run pytest tests/test_knowledge_base_config.py tests/test_knowledge_base_normalization.py -q`

Expected: PASS。

### Task 2: 导入、alias 与原子 Catalog 发布

**Files:**
- Create: `src/tags_machine_core/knowledge_base/importer.py`
- Create: `src/tags_machine_core/knowledge_base/catalog.py`
- Create: `tests/test_knowledge_base_importer.py`
- Create: `tests/test_knowledge_base_catalog.py`

**Interfaces:**
- Consumes: `KnowledgeBaseConfig` 与 Task 1 的归一化函数。
- Produces: `import_catalog(config) -> KnowledgeBaseImportResult`、`CatalogStore.load_current()`、稳定 hash build、alias 元数据。

- [ ] **Step 1: 编写导入业务夹具测试**

构造 `new/`、`st_rp/`、`pn_skip/`，覆盖缺文件、YAML 解析失败、重复 source、完全重复 alias、prompt 相同但 classify 不同的 `duplicate_content`、连续导入 hash 稳定。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_knowledge_base_importer.py tests/test_knowledge_base_catalog.py -q`

Expected: importer/catalog 未实现而失败。

- [ ] **Step 3: 实现发现、读取、hash、warning 与发布**

Importer 递归发现含任一节点文件的目录；`content_hash` 包含文件存在性与各文件 hash；Catalog 记录按 `ref` 排序后计算稳定 hash；临时 build 完成后再替换 `current.json`。

- [ ] **Step 4: 运行导入测试**

Run: `uv run pytest tests/test_knowledge_base_importer.py tests/test_knowledge_base_catalog.py -q`

Expected: PASS，第二次导入 `reused_build=true`。

### Task 3: facets、search、show 与 audit

**Files:**
- Create: `src/tags_machine_core/knowledge_base/query.py`
- Create: `tests/test_knowledge_base_query.py`

**Interfaces:**
- Consumes: `CatalogStore.load_current()` 返回的 manifest/items/warnings。
- Produces: `audit_catalog()`、`build_facets()`、`search_actions()`、`show_action()`。

- [ ] **Step 1: 编写查询测试**

覆盖字段间 AND、字段内 OR、text 只搜索正向字段、score/ref 稳定排序、默认隐藏 alias、`all_sources` 展开、精确 show 和源文件删除后的 `source_missing`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_knowledge_base_query.py -q`

Expected: query API 未实现而失败。

- [ ] **Step 3: 实现查询服务**

关键签名：

```python
def search_actions(
    catalog: LoadedCatalog,
    filters: ActionSearchFilters,
) -> ActionSearchResult: ...

def show_action(catalog: LoadedCatalog, ref: str) -> dict[str, object]: ...
```

- [ ] **Step 4: 运行查询测试**

Run: `uv run pytest tests/test_knowledge_base_query.py -q`

Expected: PASS。

### Task 4: CLI、示例配置与用户文档

**Files:**
- Create: `src/tags_machine_core/knowledge_base/cli.py`
- Modify: `src/tags_machine_core/cli.py`
- Create: `tests/test_knowledge_base_cli.py`
- Create: `configs/knowledge_base.example.yaml`
- Create: `docs/knowledge_base_readme.md`

**Interfaces:**
- Consumes: Tasks 1-3 的服务 API。
- Produces: `python -m tags_machine_core kb import|audit|facets|search|show`。

- [ ] **Step 1: 编写 CLI 测试**

验证嵌套子命令、默认 JSON 输出、`--format yaml`、search filters、`--all-sources`、无 current build 和非法 limit 的非零退出码。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_knowledge_base_cli.py -q`

Expected: 顶层 parser 不识别 `kb`。

- [ ] **Step 3: 注册命令并补齐配置/文档**

`knowledge_base.cli.add_knowledge_base_subparser()` 负责整组命令，顶层 `cli.py` 只增加一次注册调用，避免继续膨胀业务逻辑。

- [ ] **Step 4: 运行 CLI 与 core 回归测试**

Run: `uv run pytest tests/test_knowledge_base_*.py tests/test_cli_config.py tests/test_cli_nodes.py -q`

Expected: PASS。

### Task 5: 真实 `new + st_*` 业务验收

**Files:**
- Create: `docs/knowledge_base_business_acceptance_20260802.md`

**Interfaces:**
- Consumes: `F:/my_project/new/tags_machine/design/动作改2` 只读源目录。
- Produces: 实际 Catalog build、验收报告和可复现命令。

- [ ] **Step 1: 记录导入前 design Git 状态**

Run: `git -C F:/my_project/new/tags_machine/design status --short`

- [ ] **Step 2: 连续执行两次真实导入**

Run: `uv run python -m tags_machine_core kb import --config configs/knowledge_base.example.yaml`

Expected: 两次 `catalog_hash` 相同，第二次 `reused_build=true`，导入范围只有 `new + st_*`。

- [ ] **Step 3: 执行 facets/search/show/audit 业务查询**

至少覆盖 `cast/domain/phase/clothing/character_scope`，验证 positive text 命中、negative-only 不命中、alias 默认折叠与展开，并抽查 10 个 `new` 和 10 个 `st_*` 节点。

- [ ] **Step 4: 确认源目录未被修改并写验收报告**

再次执行 design Git 状态并与导入前对比，将实际记录数、warning 汇总、hash、查询样例和抽查结论写入验收文档。

- [ ] **Step 5: 最终回归**

Run: `uv run pytest tests -q`

Expected: 当前 core 基线与新增测试全部通过。

