# Node Source-Aware Form Save Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Artist、Action、Character 提供来源感知的精简 Form，并通过“保存预演 Diff → 用户确认 → 原子写回原数据源”的两阶段流程替换当前统一写 `meta.yaml` 的保存方式。

**Architecture:** 后端新增 Node SourceAdapter 层，将源文件、Form Edit Model 和运行时 `NodeDocument` 分离。前端只编辑 Adapter 返回的 `editor.values`，每次修改同时生成临时运行时节点；保存时由后端生成文件级 Unified Diff 和短期 `preview_id`，确认后重新校验源文件哈希并写入。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、PyYAML、React、TypeScript、Vitest、Testing Library

## Global Constraints

- Artist 保存回原 `tags.txt`，不能创建替代性的 `meta.yaml`。
- Action Prompt 保存回 `tags.txt`，结构化元数据保存回 `meta.yaml`，角色选择规则保存回实际来源 `action_profile.yaml` 或 `run-prompt-prompt.md`。
- Character 保存回原 `meta.yaml`。
- 第一次点击保存不得修改磁盘。
- 正式提交前必须重新校验所有源文件 sha256。
- 未知 legacy 行和未知扩展参数不得因为 Form 未展示而丢失。
- AgentComposer、Composer、Renderer 和 NovelAI Client 协议保持不变。
- 不使用子 agent；在当前任务内按顺序实现并验收。

---

### Task 1: Node 编辑协议与 SourceAdapter 注册表

**Files:**
- Create: `src/tags_machine_core/web/node_editing/models.py`
- Create: `src/tags_machine_core/web/node_editing/base.py`
- Create: `src/tags_machine_core/web/node_editing/registry.py`
- Create: `src/tags_machine_core/web/node_editing/__init__.py`
- Modify: `src/tags_machine_core/web/services/node_workspace.py`
- Test: `tests/test_web_node_editing.py`

**Interfaces:**
- Produces: `NodeEditorDocument`、`NodeEditorSource`、`FileMutation`、`NodeSourceAdapter`、`NodeSourceAdapterRegistry`。
- Consumes: 节点目录、role 和 Adapter 的 `values`。

- [ ] **Step 1: 写协议测试**

验证 `NodeWorkspace.read_node(..., role=...)` 返回：

```python
response["editor"] == {
    "adapter": "character_meta_yaml/v1",
    "role": "character",
    "values": {...},
    "sources": [{"path": ..., "format": "meta.yaml", "sha256": ..., "writable": True}],
    "capabilities": {"save": True, "multi_file": False},
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m unittest tests.test_web_node_editing -v`

Expected: FAIL，当前响应没有 `editor`。

- [ ] **Step 3: 实现协议模型**

`models.py` 定义：

```python
class NodeEditorSource(BaseModel):
    path: str
    format: str
    sha256: str | None
    writable: bool = True

class NodeEditorDocument(BaseModel):
    adapter: str
    role: str
    values: dict[str, Any]
    sources: list[NodeEditorSource]
    capabilities: dict[str, bool]

class FileMutation(BaseModel):
    path: Path
    format: str
    before_text: str
    after_text: str
    before_sha256: str | None
```

- [ ] **Step 4: 实现 Adapter 接口和注册表**

`NodeSourceAdapter` 提供：

```python
def matches(self, node_dir: Path, role: str) -> bool: ...
def read_editor(self, node_dir: Path) -> NodeEditorDocument: ...
def build_runtime_node(self, node_dir: Path, values: dict[str, Any]) -> NodeDocument: ...
def preview_mutations(self, node_dir: Path, values: dict[str, Any]) -> list[FileMutation]: ...
```

注册表按明确顺序选择 Artist、Action、Character Adapter；无匹配时返回只读 generic editor，不允许保存。

- [ ] **Step 5: 接入 NodeWorkspace**

`read_node` 保留 `node/raw`，新增 `editor`；`preview_editor` 使用选中的 Adapter 将 `values` 转成运行时 `NodeDocument`。

- [ ] **Step 6: 验证**

Run: `uv run python -m unittest tests.test_web_node_editing tests.test_web_nodes -v`

Expected: 全部通过。

---

### Task 2: Artist、Action、Character 来源 Adapter

**Files:**
- Create: `src/tags_machine_core/web/node_editing/text_utils.py`
- Create: `src/tags_machine_core/web/node_editing/artist_tags.py`
- Create: `src/tags_machine_core/web/node_editing/action_sources.py`
- Create: `src/tags_machine_core/web/node_editing/character_yaml.py`
- Modify: `src/tags_machine_core/web/node_editing/registry.py`
- Test: `tests/test_web_node_source_adapters.py`

**Interfaces:**
- Consumes: `NodeSourceAdapter` 协议。
- Produces: `legacy_artist_tags/v1`、`action_sources/v1`、`character_meta_yaml/v1`。

- [ ] **Step 1: Artist Adapter 测试**

构造包含 Prompt 行、`type`、`origin_uc`、`gen_json` 和未知扩展行的真实结构 `tags.txt`。验证：

- Form 只返回 Prompt Prefix/Suffix、Negative、After Negative、常用 params 和 flags。
- 未修改字段序列化后源文件字节不变。
- 修改 Prompt 只改变 Prompt 行。
- 未知扩展行保持原样。
- 不生成 `meta.yaml`。

- [ ] **Step 2: 实现 Artist Adapter**

复用 `NovelAIArtistRepository` 构建运行时节点；源文件 Writer 解析有序区段，只替换已编辑区段。`gen_json` 在 params 未变化时保留原行，变化时合并原字典后序列化，避免丢失 reference/vibe 和未知 NovelAI 参数。

- [ ] **Step 3: Action Adapter 测试**

覆盖三种文件：

- `tags.txt`：Prompt。
- `meta.yaml`：name、description、negative、tags 及其他源元数据。
- `run-prompt-prompt.md` 或 `action_profile.yaml`：`selected_keys`。

验证只修改 Prompt 时仅产生 `tags.txt` mutation；修改 selected_keys 时只额外产生实际规则来源文件 mutation，`classify.yaml` 保持不变。

- [ ] **Step 4: 实现 Action Adapter**

Action Edit Model：

```json
{
  "id": "...",
  "name": "...",
  "description": "...",
  "prompt_lines": ["..."],
  "negative": ["..."],
  "selected_keys": [["character", "copyright", "hair"]]
}
```

运行时节点以现有 `meta.yaml` 为基础，再用编辑后的 Prompt 同步 `prompt.positive` 和 `tags.action`，最后附加角色选择 profile。

- [ ] **Step 5: Character Adapter 测试与实现**

Character Edit Model：

```json
{
  "id": "homura",
  "name": "Homura",
  "description": "...",
  "positive": ["..."],
  "negative": ["..."],
  "identity_minimal": ["character", "copyright"],
  "relations": {},
  "tags": {}
}
```

Writer 读取原 YAML，保留 `agent/clothing` 等源字段，移除 `path/renderers/generation/legacy` 等运行时快照字段，再覆盖 Form 管理字段。

- [ ] **Step 6: 验证 Adapter**

Run: `uv run python -m unittest tests.test_web_node_source_adapters -v`

Expected: Artist、Action、Character 来源测试全部通过。

---

### Task 3: 保存预演、哈希保护与原子提交

**Files:**
- Create: `src/tags_machine_core/web/services/node_save_preview_store.py`
- Modify: `src/tags_machine_core/web/services/node_workspace.py`
- Modify: `src/tags_machine_core/web/routes/nodes.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_node_save.py`

**Interfaces:**
- Produces: `POST /api/nodes/editor-preview`、`POST /api/nodes/save-preview`、`PUT /api/nodes/save-commit`。
- Consumes: Adapter registry 和 `FileMutation[]`。

- [ ] **Step 1: 写接口失败测试**

覆盖：

- editor preview 不写磁盘。
- save preview 返回 Unified Diff 和 `preview_id`，不写磁盘。
- commit 后写回源文件。
- 源文件在预演后变化返回 `409 source_changed`。
- preview 过期返回 `409 save_preview_expired`。
- 多文件临时写入失败时不覆盖正式文件。

- [ ] **Step 2: 实现预演存储**

`NodeSavePreviewStore` 使用进程内字典，保存：

```python
preview_id, ref, role, adapter, mutations, created_at, expires_at
```

默认有效期 10 分钟；读取时清理过期记录；成功 commit 后立即删除。

- [ ] **Step 3: 实现 Unified Diff**

使用 `difflib.unified_diff`，文件名使用相对节点目录路径。响应不返回内部 `before_text`，返回 `diff` 和 `after_text`。

- [ ] **Step 4: 实现原子提交**

1. 校验所有源文件当前 sha256。
2. 写同目录 `.<name>.promptatelier.tmp`。
3. 所有临时文件成功后调用 `Path.replace`。
4. 任一临时写入失败时清理临时文件并不替换正式文件。

- [ ] **Step 5: 接口错误映射**

返回明确错误：`unsupported_node_source`、`invalid_editor_values`、`source_changed`、`save_preview_expired`、`source_write_failed`。

- [ ] **Step 6: 验证后端 Web**

Run: `uv run python -m unittest tests.test_web_node_save tests.test_web_node_editing tests.test_web_node_source_adapters tests.test_web_nodes -v`

Expected: 全部通过。

---

### Task 4: 前端编辑会话与角色化 Form

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/nodes/types.ts`
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/storage.ts`
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Modify: `web/src/components/NodeSlot.tsx`
- Create: `web/src/components/nodeForms/ArtistNodeForm.tsx`
- Create: `web/src/components/nodeForms/ActionNodeForm.tsx`
- Create: `web/src/components/nodeForms/CharacterNodeForm.tsx`
- Create: `web/src/components/nodeForms/NodeFormFields.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.tsx`
- Test: `web/src/components/NodeWorkspaceEditor.test.tsx`
- Test: `web/src/workspace/CustomWorkspaceProvider.test.tsx`

**Interfaces:**
- Consumes: `NodeReadResponse.editor`。
- Produces: 每个 slot 的 `sourceEditor` 和 editor 的 `editValues/baselineValues`。

- [ ] **Step 1: 扩展前端类型与 workspace**

`NodeVariantSlot` 新增 `sourceEditor`；选择节点时同时保存 response.editor；Compare 镜像时深拷贝 editor；还原时恢复 baseline values。

旧 localStorage 数据缺少 `sourceEditor` 时兼容为 `null`，不重置整个工作台。

- [ ] **Step 2: NodeSlot 传递完整读取响应**

`onSelect` 改为接收 `{ref, node, editor}`，不再丢弃后端 Form 编辑协议。

- [ ] **Step 3: 实现角色化 Form**

- Artist：Prompt Prefix/Suffix、Negative、After Negative、模型、Sampler、Steps、Scale、Noise Schedule、flags。
- Action：Prompt、Negative、selected_keys 角色行。
- Character：基础信息、Prompt、identity_minimal、relations、tags。

普通 Form 不渲染 `path/legacy/renderers/generation`。JSON 页继续显示临时运行时 `NodeDocument`。

- [ ] **Step 4: Form 修改生成临时节点**

编辑 values 后以 200ms debounce 调用 `/nodes/editor-preview`。成功后更新当前 slot `draftNode`，因此已有 Preview、Generate 和 Compare 主链路无需修改。

请求失败时保留当前 values，并在 Form 内显示错误，不能静默回退到旧节点。

- [ ] **Step 5: 验证 Form**

Run: `npm run test -- NodeWorkspaceEditor.test.tsx CustomWorkspaceProvider.test.tsx`

Expected: 角色化字段、临时运行节点和缓存恢复测试通过。

---

### Task 5: 保存 Diff 弹窗与端到端验收

**Files:**
- Create: `web/src/components/NodeSaveDiffDialog.tsx`
- Create: `web/src/components/NodeSaveDiffDialog.test.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.tsx`
- Modify: `web/src/styles.css`
- Modify: `docs/web_control_console_readme.md`

**Interfaces:**
- Consumes: `/nodes/save-preview` 和 `/nodes/save-commit`。
- Produces: 文件页签、Unified Diff、完整目标文件折叠区及二次确认保存流程。

- [ ] **Step 1: 写弹窗交互测试**

覆盖：

- 第一次点击保存只调用 save-preview。
- 多文件按页签展示。
- Unified Diff 新增绿色、删除红色、上下文灰色。
- 取消不调用 commit，草稿保持。
- 确认调用 commit，并用响应中的 node/editor 更新 slot。
- `source_changed` 提示重新生成 Diff。
- 无变化时不显示确认按钮。

- [ ] **Step 2: 实现 Diff 行解析**

前端按行前缀渲染：

- `+++`、`---`：文件头。
- `@@`：区块头。
- `+`：新增。
- `-`：删除。
- 其他：上下文。

不在前端重新计算 Diff。

- [ ] **Step 3: 接入保存按钮**

点击“保存节点”后打开 Diff 弹窗。确认成功后更新 `sourceNode/draftNode/sourceEditor`、清除 `*` 标记并保留编辑器打开状态，显示“已保存到原数据源”。

- [ ] **Step 4: 完整自动验证**

Run: `uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_node_editing tests.test_web_node_source_adapters tests.test_web_node_save tests.test_web_compose tests.test_web_results -v`

Run: `npm run test`

Run: `npm run build`

Run: `git diff --check`

Expected: 所有相关后端测试、14+ 前端测试文件、生产构建和空白检查通过。

- [ ] **Step 5: 浏览器业务验收**

使用复制到临时 design_root 的真实节点样本完成：

1. Artist 修改一个 Prompt tag，取消一次，验证 sha256 不变；再次确认后验证只更新 `tags.txt`，没有创建 `meta.yaml`。
2. Action 修改 Prompt 和一组 selected_keys，验证 Diff 分文件展示并写回真实来源，`classify.yaml` 不变。
3. Character 修改 Prompt，验证保存后的 `meta.yaml` 不包含运行时字段。
4. 在 Diff 弹窗打开后外部修改源文件，验证确认保存返回 `source_changed`。
