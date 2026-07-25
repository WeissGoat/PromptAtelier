# Web Random Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PromptAtelier Custom 页面增加 Folder、Collection、Glob 随机节点，支持 Action `classify.yaml` 二次过滤、候选预览、普通 Generate、Compare Matrix 和 NT 真实出图。

**Architecture:** 候选路径扫描和 Collection 展开抽到通用 `node_pools` 输入层，Web API 提供分页扫描和无重复抽取。前端槽位只保存 `NodePoolSpec`，Preview/Generate 前把随机槽位解析成普通 `NodeDocument`，现有 Composer、Policy 和 Renderer 不接触随机类型。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、PyYAML、React 18、TypeScript、Vitest、NovelAI。

## Global Constraints

- 直接在当前 `main` 开发，不创建新分支。
- 不修改或提交当前工作区中与随机节点无关的既有变更。
- AgentComposer 的 Hash、缓存输入和执行逻辑不得修改。
- 固定节点普通 Generate 继续使用现有单请求链路；只有存在随机节点时拆分为 `n_samples=1`。
- 单次 Generate 内同一随机槽位无重复，候选耗尽后重置并避免边界连续重复。
- `classify.yaml` 过滤第一版只允许 Action 使用；未启用过滤时不要求节点存在该文件。
- 业务测试和 NovelAI 真实出图是最终门禁，聚焦测试用于保护关键边界，不扩散无关 smoke test。

---

## File Structure

### Backend

- Create `src/tags_machine_core/node_pools/models.py`：候选池请求、分类过滤、候选、统计和抽取结果模型。
- Create `src/tags_machine_core/node_pools/selectors.py`：Folder、Collection、Glob 公共路径展开。
- Create `src/tags_machine_core/node_pools/classify.py`：读取并归一化 Action `classify.yaml`。
- Create `src/tags_machine_core/node_pools/resolver.py`：候选校验、过滤、搜索、分页和无重复抽取。
- Create `src/tags_machine_core/node_pools/project_collections.py`：加载 `web.project_requires` 的 Collection。
- Create `src/tags_machine_core/node_pools/__init__.py`：稳定导出接口。
- Create `src/tags_machine_core/web/services/node_pool_service.py`：Web 扫描缓存和节点响应组装。
- Create `src/tags_machine_core/web/routes/node_pools.py`：Collection、scan、sample API。
- Modify `src/tags_machine_core/config.py`：增加 `WebConfig.project_requires`。
- Modify `src/tags_machine_core/web/app.py`：装配 NodePoolService 和路由。
- Modify `src/tags_machine_core/batch/selectors.py`：Folder、Collection、Glob 委托公共选择器，Batch 外部格式不变。
- Modify `src/tags_machine_core/execution.py`：把 `request.meta.random_nodes` 写入实际 PNG 的 core metadata。

### Frontend

- Modify `web/src/workspace/types.ts`：增加随机槽位和 `NodePoolSpec` 类型。
- Modify `web/src/workspace/storage.ts`：持久化随机配置，迁移旧工作区快照。
- Modify `web/src/workspace/CustomWorkspaceProvider.tsx`：创建、更新、清除随机槽位和临时样例状态。
- Modify `web/src/nodes/types.ts`、`web/src/nodes/temporaryNodes.ts`：识别随机槽位，阻止未解析随机槽位直接序列化。
- Modify `web/src/components/NodeSlot.tsx`、`web/src/components/NodeRoleGroup.tsx`：增加骰子入口和 Random 摘要。
- Create `web/src/components/RandomNodeEditor.tsx`：来源、过滤条件、统计和懒加载候选界面。
- Modify `web/src/components/NodeWorkspaceEditor.tsx`：在中间编辑区切换普通节点与随机节点编辑器。
- Modify `web/src/api/types.ts`：增加候选池 API 类型。
- Create `web/src/randomNodes/api.ts`：scan/sample 客户端。
- Create `web/src/randomNodes/resolve.ts`：按实际任务数量批量解析随机槽位。
- Modify `web/src/compare/matrix.ts`：随机槽位作为一个已选择矩阵项。
- Modify `web/src/compare/useCompareRunController.ts`：每个实际 Compare 项使用对应随机抽取结果。
- Modify `web/src/workspace/requestBuilder.ts`：仅接受已解析槽位并附加随机选择 metadata。
- Modify `web/src/components/CustomGeneratePanel.tsx`：Preview 样例抽取、随机 Primary 多任务进度和结果展示。
- Modify `web/src/styles.css`：随机节点编辑器、统计、过滤器和候选列表布局。

### Tests And Docs

- Create `tests/test_node_pools.py`。
- Create `tests/test_web_node_pools.py`。
- Modify `tests/test_batch_generation.py`。
- Modify `web/src/workspace/storage.test.ts`。
- Modify `web/src/compare/matrix.test.ts`、`web/src/compare/useCompareRunController.test.tsx`。
- Create `web/src/components/RandomNodeEditor.test.tsx`。
- Modify `web/src/pages/CustomStudio.test.tsx`。
- Create `docs/web_random_node_business_test_20260726.md`。

---

### Task 1: Common Node Pool Models And Selectors

**Files:**
- Create: `src/tags_machine_core/node_pools/models.py`
- Create: `src/tags_machine_core/node_pools/selectors.py`
- Create: `src/tags_machine_core/node_pools/project_collections.py`
- Create: `src/tags_machine_core/node_pools/__init__.py`
- Modify: `src/tags_machine_core/config.py`
- Modify: `src/tags_machine_core/batch/selectors.py`
- Test: `tests/test_node_pools.py`
- Test: `tests/test_batch_generation.py`

**Interfaces:**
- Produces `NodePoolSpec.model_validate(data)`。
- Produces `ProjectCollectionLoader.load() -> dict[str, dict[str, list[Any]]]`。
- Produces `expand_node_pool_source(role, source, context) -> list[str]`。

- [ ] **Step 1: Add focused failing tests**

覆盖 Folder、Glob、Collection 嵌套表达式、路径去重和 `WebConfig.project_requires`。Batch 回归测试使用现有 `expand_selector()`，确认输出顺序不变。

- [ ] **Step 2: Run the focused tests**

Run:

```powershell
uv run python -m unittest tests.test_node_pools tests.test_batch_generation.BatchGenerationTest.test_collection_selector_supports_nested_expressions
```

Expected: 新增模型或导出尚不存在而失败。

- [ ] **Step 3: Implement models and common selector expansion**

核心类型必须使用判别明确的字段：

```python
class NodePoolSource(BaseModel):
    type: Literal["folder", "collection", "glob"]
    value: str
    recursive: bool = False
    include_names: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=list)


class ClassifyFilter(BaseModel):
    phase: list[str] = Field(default_factory=list)
    species: list[str] = Field(default_factory=list)
    cast: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    subtype: list[str] = Field(default_factory=list)
    pose: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    clothing: list[str] = Field(default_factory=list)


class NodePoolSpec(BaseModel):
    source: NodePoolSource
    filters: NodePoolFilters = Field(default_factory=NodePoolFilters)
```

`batch/selectors.py` 的 prompt_file/prompt_list 分支保留原位，四种节点来源分支委托 `expand_node_pool_source()`。

- [ ] **Step 4: Add project collection loading**

`WebConfig.project_requires` 默认空列表，路径相对当前项目工作目录解析。Loader 沿用现有 require 递归合并和循环检测，最后只返回 `collections`。

- [ ] **Step 5: Run tests and commit**

```powershell
uv run python -m unittest tests.test_node_pools tests.test_batch_generation
git add src/tags_machine_core/node_pools src/tags_machine_core/config.py src/tags_machine_core/batch/selectors.py tests/test_node_pools.py tests/test_batch_generation.py
git commit -m "feat: add shared node pool selectors"
```

### Task 2: Classify Filtering And Random Deck

**Files:**
- Create: `src/tags_machine_core/node_pools/classify.py`
- Create: `src/tags_machine_core/node_pools/resolver.py`
- Modify: `tests/test_node_pools.py`

**Interfaces:**
- Produces `load_classify_tags(node_dir: Path) -> dict[str, set[str]]`。
- Produces `NodePoolResolver.scan(role, spec) -> NodePoolScanResult`。
- Produces `NodePoolResolver.sample(role, spec, count, rng=None) -> NodePoolSampleResult`。

- [ ] **Step 1: Add classify fixtures and failing tests**

覆盖：未启用过滤不读取文件；标量和数组统一集合；`subtype` 扁平化；同字段 OR、跨字段 AND；缺失/非法文件统计；非 Action 使用过滤时报错。

- [ ] **Step 2: Implement classify normalization**

归一化输出仅包含：

```python
CLASSIFY_FIELDS = (
    "phase", "species", "cast", "domain", "subtype",
    "pose", "environment", "tone", "flags", "clothing",
)
```

每个配置字段满足：

```python
bool(node_values[field] & requested_values[field])
```

多个已配置字段全部通过才保留节点。

- [ ] **Step 3: Implement scan and no-repeat sampling**

扫描结果包含 `raw_total`、`total`、`missing_classify`、`invalid_classify`、`classify_mismatch` 和警告。抽取使用乱序队列；重置时若候选数大于一，新的首项不得等于上一轮末项。

- [ ] **Step 4: Run tests and commit**

```powershell
uv run python -m unittest tests.test_node_pools
git add src/tags_machine_core/node_pools tests/test_node_pools.py
git commit -m "feat: filter and sample random node pools"
```

### Task 3: Web Node Pool API

**Files:**
- Create: `src/tags_machine_core/web/services/node_pool_service.py`
- Create: `src/tags_machine_core/web/routes/node_pools.py`
- Modify: `src/tags_machine_core/web/routes/__init__.py`
- Modify: `src/tags_machine_core/web/app.py`
- Modify: `configs/local.example.yaml`
- Modify local only: `configs/local.yaml`
- Create: `tests/test_web_node_pools.py`

**Interfaces:**
- `GET /api/node-pools/collections?role=action`。
- `POST /api/node-pools/scan` with `{role, spec, q, offset, limit, refresh}`。
- `POST /api/node-pools/sample` with `{role, spec, count}`。

- [ ] **Step 1: Write route tests**

使用临时 design_root 和临时 project require 文件，验证分页、搜索、facets、统计、完整节点抽取和结构化 400 错误。

- [ ] **Step 2: Implement NodePoolService**

服务保存五分钟进程内扫描缓存，key 为 role 与规范化 spec 的 SHA256。`scan` 对缓存结果做 query/offset/limit；`sample` 忽略分页缓存并重新扫描。

- [ ] **Step 3: Register routes and local configuration**

示例及本机配置增加：

```yaml
web:
  project_requires:
    - examples/project/collections.yaml
    - examples/project/nai_const_action_groups.yaml
```

`configs/local.yaml` 仅本机修改，不加入 Git。

- [ ] **Step 4: Run API tests and commit**

```powershell
uv run python -m unittest tests.test_web_node_pools tests.test_web_app tests.test_web_nodes
git add src/tags_machine_core/web configs/local.example.yaml tests/test_web_node_pools.py
git commit -m "feat: expose web random node pools"
```

### Task 4: Persisted Random Slots And Editor UI

**Files:**
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/storage.ts`
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Modify: `web/src/nodes/types.ts`
- Modify: `web/src/nodes/temporaryNodes.ts`
- Modify: `web/src/components/NodeSlot.tsx`
- Modify: `web/src/components/NodeRoleGroup.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.tsx`
- Create: `web/src/components/RandomNodeEditor.tsx`
- Modify: `web/src/api/types.ts`
- Create: `web/src/randomNodes/api.ts`
- Modify: `web/src/styles.css`
- Test: `web/src/workspace/storage.test.ts`
- Test: `web/src/components/RandomNodeEditor.test.tsx`
- Test: `web/src/components/NodeSlot.test.tsx`

**Interfaces:**
- `NodeVariantSlot.sourceKind: "fixed" | "random"`。
- `NodeVariantSlot.randomSpec: NodePoolSpec | null`。
- Provider methods `createRandom(slotId)`, `updateRandomSpec(slotId, spec)`, `openRandomEditor(slotId)`。

- [ ] **Step 1: Add state and migration tests**

旧 v2 快照迁移时为所有槽位补 `sourceKind: "fixed"` 和 `randomSpec: null`；随机配置刷新后保持，扫描结果和样例不得写入 localStorage。

- [ ] **Step 2: Implement random slot state**

随机槽位没有 `draftNode`。`serializeNodeSlot()` 遇到未解析随机槽位必须抛出明确错误，防止它绕过任务规划进入 Composer。

- [ ] **Step 3: Add slot interaction**

骰子按钮把当前槽位切换为随机节点并打开中间编辑区。Compare 加号仍镜像 Primary，包括随机配置；清除或选择固定节点时清空随机配置。

- [ ] **Step 4: Build RandomNodeEditor**

实现来源表单、Collection 下拉、Action classify 多选、统计卡、候选搜索和滚动到底加载下一页。来源或过滤条件变化后清空旧列表并自动扫描；保留手动重新扫描按钮。

- [ ] **Step 5: Run frontend tests and commit**

```powershell
cd web
npm test -- --run src/workspace/storage.test.ts src/components/NodeSlot.test.tsx src/components/RandomNodeEditor.test.tsx
npm run build
cd ..
git add web/src
git commit -m "feat: add random node editor"
```

### Task 5: Preview And Primary Random Generation

**Files:**
- Create: `web/src/randomNodes/resolve.ts`
- Modify: `web/src/workspace/requestBuilder.ts`
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `src/tags_machine_core/web/routes/generate.py`
- Modify: `src/tags_machine_core/execution.py`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Modify: `tests/test_web_compose.py`

**Interfaces:**
- `sampleRandomSlot(slot, count) -> Promise<ResolvedRandomNode[]>`。
- `resolveRandomSlots(items) -> resolved task items`。
- `buildComposeRenderRequest(..., { randomSelections })` 把选择记录带入请求上下文。

- [ ] **Step 1: Add Preview and Primary tests**

Preview 抽取一次且标记样例；Generate 不复用 Preview；随机 Primary `NT=3` 创建三个 `n_samples=1` 请求；固定 Primary 仍创建一个 `n_samples=3` 请求。

- [ ] **Step 2: Implement sample resolution**

解析结果转换为普通槽位副本：

```typescript
{
  ...slot,
  sourceKind: "fixed",
  sourceRef: draw.ref,
  sourceNode: draw.node,
  draftNode: draw.node,
  randomSpec: null,
}
```

同时保留独立的 `RandomSelectionRecord`，不得把随机配置写入 Composer nodes。

- [ ] **Step 3: Implement random Primary run flow**

存在随机槽位时按 NT 顺序执行 Compose 和 Generate，每项生成参数 `n_samples=1`，每项使用独立 seed，结果在同一个随机运行目录下展示。无随机槽位继续走旧流程。

- [ ] **Step 4: Attach result and PNG metadata**

`/generate` 把合法的 `random_selections` 合并到 `render_request.meta.random_nodes`，并把同一记录附加到 Job result。`build_core_png_text()` 增加 `random_nodes` 字段，确保元数据来自实际请求并写入 PNG。

- [ ] **Step 5: Run tests and commit**

```powershell
uv run python -m unittest tests.test_web_compose
cd web
npm test -- --run src/pages/CustomStudio.test.tsx src/workspace/requestBuilder.test.ts
npm run build
cd ..
git add src/tags_machine_core/web/routes/generate.py src/tags_machine_core/execution.py web/src tests/test_web_compose.py
git commit -m "feat: generate primary random nodes"
```

### Task 6: Compare Matrix Random Resolution

**Files:**
- Modify: `web/src/compare/matrix.ts`
- Modify: `web/src/compare/runPlan.ts`
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/compare/matrix.test.ts`
- Modify: `web/src/compare/runPlan.test.ts`
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Modify: `web/src/components/CustomGeneratePanel.tsx`

**Interfaces:**
- Random slot counts as one matrix factor even when `draftNode` is null。
- Each `CompareRunItem` receives resolved slots and `randomSelections` before Compose。

- [ ] **Step 1: Add matrix and controller tests**

覆盖 Random Artist × Fixed Character × Compare Action × Behavior × NT；候选数量不参与矩阵数量；每个实际 item 独立抽取；同 NT group 仍共享 seed。

- [ ] **Step 2: Update matrix selection**

统一使用：

```typescript
export function isSelectedSlot(slot: NodeVariantSlot): boolean {
  return slot.sourceKind === "random" ? Boolean(slot.randomSpec) : Boolean(slot.draftNode);
}
```

- [ ] **Step 3: Resolve each random slot before running items**

按 slotId 统计整个计划中的出现次数，每个 slotId 调用一次 `/node-pools/sample`，再按任务顺序消费返回节点。每个实际任务仍串行提交 NovelAI。

- [ ] **Step 4: Show actual chosen labels**

Compare 结果卡显示最终 Artist、Character、Action 名称；随机来源使用 Random badge，并可查看 source type、候选数和实际 ref。

- [ ] **Step 5: Run tests and commit**

```powershell
cd web
npm test -- --run src/compare/matrix.test.ts src/compare/runPlan.test.ts src/compare/useCompareRunController.test.tsx src/pages/CustomStudio.test.tsx
npm run build
cd ..
git add web/src
git commit -m "feat: resolve random compare nodes"
```

### Task 7: End-To-End Business Validation

**Files:**
- Create: `docs/web_random_node_business_test_20260726.md`
- Modify only if defects are found: files owned by Tasks 1-6

- [ ] **Step 1: Run focused backend and frontend gates**

```powershell
uv run python -m unittest tests.test_node_pools tests.test_web_node_pools tests.test_web_compose tests.test_web_app tests.test_batch_generation
cd web
npm test -- --run
npm run build
cd ..
```

Expected: 全部通过，Batch selector 行为无回归。

- [ ] **Step 2: Start Web and verify browser workflow**

```powershell
uv run python scripts/dev_web.py
```

验收 Folder、Collection、Glob、Action classify 筛选、候选滚动分页、刷新持久化、Preview 样例和错误提示。

- [ ] **Step 3: Run NovelAI Folder random Character**

选择一个固定 Artist、一个 Folder 随机 Character 和固定 Action，设置 `NT=3`。确认三个任务 `n_samples=1`、角色不重复、图像均成功，并从 PNG 读取 `random_nodes`。

- [ ] **Step 4: Run NovelAI classified Action and Compare**

Action 使用 `design/动作改2/new` Folder，过滤 `domain=foot` 与 `subtype=[footjob, sole_focus]`；执行固定 Artist × Random Action × `NT=2`。再增加 Artist Compare，确认矩阵数量、同组 seed 和每张图实际 Action ref。

- [ ] **Step 5: Verify AgentComposer regression boundary**

使用既有固定节点 AgentComposer 缓存 Preview，不配置随机节点，记录 Hash/缓存命中与改动前一致。检查 Git diff，确认 AgentComposer 文件未修改。

- [ ] **Step 6: Write business report and commit**

报告记录 Web 地址、配置、候选统计、实际图片绝对路径、PNG 随机元数据、Compare 数量、seed 和发现的问题。

```powershell
git add docs/web_random_node_business_test_20260726.md
git commit -m "docs: validate web random nodes"
```

### Task 8: Final Review

- [ ] **Step 1: Inspect repository state**

```powershell
git status --short
git log -8 --oneline
git diff HEAD~7 -- src/tags_machine_core/composers/agent.py src/tags_machine_core/composers/agent_cache.py
```

Expected: 仅保留用户原有无关脏文件；AgentComposer diff 为空。

- [ ] **Step 2: Check implementation against spec**

逐项核对：三种来源、Action classify、未启用不影响、分页候选、样例 Preview、无重复抽取、NT、Compare、PNG metadata、浏览器持久化和 AgentComposer 边界。

- [ ] **Step 3: Report final evidence**

最终回复必须给出真实图片路径、业务报告路径、关键提交和未解决问题；不得仅用单元测试通过声明功能完成。
