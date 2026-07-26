# Web Random Node Role Root And Filter UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Web 随机节点的 Folder/Glob 相对当前节点类型根目录解析，并把 Action 分类过滤改成可搜索、可多选、可逐项取消的按需筛选器。

**Architecture:** 将 `NodeWorkspace` 现有角色目录定义抽到公共 `role_paths` 模块，普通节点搜索与 `NodePoolResolver` 共用。直接 Folder/Glob 在进入公共 Selector 前解析为角色根目录下的受限绝对路径，Collection 保持原语义。前端新增独立 `ClassifyFilterEditor`，继续只读写现有 `ClassifyFilter` 数组结构。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、React 18、TypeScript、Vitest、Testing Library、NovelAI 真实生成链路。

## Global Constraints

- 直接在当前 `main` 开发，不创建新分支。
- 不修改或提交工作区中与本功能无关的现有变更。
- Folder/Glob 只接受相对当前节点类型根目录的路径。
- Collection 保持当前工程配置语义。
- `NodePoolSpec`、随机抽取、Compare、NT、AgentComposer 和 Hash 不修改。
- 中文文档和必要的中文注释。
- 完成功能后集中执行业务验收，NovelAI 真实出图优先于大量单元测试。

---

## File Structure

- Create `src/tags_machine_core/nodes/role_paths.py`：角色目录候选、根目录选择、相对路径与 Glob 边界校验。
- Modify `src/tags_machine_core/web/services/node_workspace.py`：普通节点搜索改用公共角色目录定义。
- Modify `src/tags_machine_core/node_pools/resolver.py`：直接 Folder/Glob 使用角色根目录，Collection 保持原路径基准。
- Modify `tests/test_node_pools.py`：覆盖角色相对 Folder/Glob、绝对路径和越界拒绝、Collection 回归。
- Modify `tests/test_web_node_pools.py`：覆盖 Web API 输入 `new` 的真实目录解析。
- Create `web/src/components/ClassifyFilterEditor.tsx`：按需字段、多选复选下拉、标签取消和清空。
- Create `web/src/components/ClassifyFilterEditor.test.tsx`：覆盖多选、取消、字段删除和清空全部。
- Modify `web/src/components/RandomNodeEditor.tsx`：接入新筛选器并更新角色相对路径文案。
- Modify `web/src/styles.css`：新筛选器布局、标签、弹层和响应式样式。
- Create `docs/web_random_node_role_root_filter_business_test_20260726.md`：记录浏览器与 NovelAI 业务验收结果。

---

### Task 1: 公共角色根目录解析

**Files:**
- Create: `src/tags_machine_core/nodes/role_paths.py`
- Modify: `src/tags_machine_core/web/services/node_workspace.py`
- Test: `tests/test_node_pools.py`

**Interfaces:**
- Produces: `role_dir_names(role: str) -> tuple[str, ...]`
- Produces: `role_roots(design_root: str | Path, role: str) -> list[Path]`
- Produces: `primary_role_root(design_root: str | Path, role: str) -> Path`
- Produces: `resolve_role_relative_path(design_root: str | Path, role: str, value: str) -> Path`
- Consumes: existing Artist、Character、Action、Background directory names from `NodeWorkspace.ROLE_DIRS`.

- [ ] **Step 1: Add focused role-root tests**

在 `tests/test_node_pools.py` 增加测试，临时 design 下创建 `动作改2/new` 和其他类型目录，断言 Action 根目录选择 `动作改2`，并断言绝对路径及 `../角色` 被拒绝。

```python
def test_role_relative_path_uses_action_root_and_rejects_escape(self):
    with tempfile.TemporaryDirectory() as tmp:
        design_root = Path(tmp)
        action_root = design_root / "动作改2"
        action_root.mkdir()

        self.assertEqual(
            resolve_role_relative_path(design_root, "action", "new"),
            action_root / "new",
        )
        with self.assertRaisesRegex(ValueError, "relative action root"):
            resolve_role_relative_path(design_root, "action", str(action_root))
        with self.assertRaisesRegex(ValueError, "inside action root"):
            resolve_role_relative_path(design_root, "action", "../角色")
```

- [ ] **Step 2: Run the focused test and confirm the missing module failure**

Run: `uv run python -m pytest tests/test_node_pools.py -q`

Expected: FAIL because `tags_machine_core.nodes.role_paths` does not exist.

- [ ] **Step 3: Implement the shared role path module**

核心结构：

```python
ROLE_DIRS: dict[str, tuple[str, ...]] = {
    "artist": ("画风", "artist", "artists"),
    "character": ("角色", "character", "characters"),
    "action": ("动作改2", "动作", "action", "actions"),
    "background": ("背景", "background", "backgrounds"),
}

def primary_role_root(design_root: str | Path, role: str) -> Path:
    roots = role_roots(design_root, role)
    return next((root for root in roots if root.is_dir()), roots[0])

def resolve_role_relative_path(design_root: str | Path, role: str, value: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"node pool path must be relative to {role} root")
    root = primary_role_root(design_root, role).resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"node pool path must stay inside {role} root") from exc
    return resolved
```

- [ ] **Step 4: Make NodeWorkspace consume the shared definition**

删除 `node_workspace.py` 内部 `ROLE_DIRS` 副本，将：

```python
roots = [self.design_root / item for item in ROLE_DIRS.get(role, [role])]
```

替换为：

```python
roots = role_roots(self.design_root, role)
```

- [ ] **Step 5: Run focused backend tests**

Run: `uv run python -m pytest tests/test_node_pools.py tests/test_web_nodes.py -q`

Expected: PASS，普通节点分页结果保持不变。

- [ ] **Step 6: Commit only Task 1 files**

```powershell
git add src/tags_machine_core/nodes/role_paths.py src/tags_machine_core/web/services/node_workspace.py tests/test_node_pools.py
git commit --only src/tags_machine_core/nodes/role_paths.py src/tags_machine_core/web/services/node_workspace.py tests/test_node_pools.py -m "refactor: share node role roots"
```

---

### Task 2: Random Folder And Glob 使用角色根目录

**Files:**
- Modify: `src/tags_machine_core/node_pools/resolver.py`
- Modify: `tests/test_node_pools.py`
- Modify: `tests/test_web_node_pools.py`

**Interfaces:**
- Consumes: `resolve_role_relative_path(design_root, role, value) -> Path` from Task 1.
- Produces: `NodePoolResolver._resolve_direct_source(role: str, spec: NodePoolSpec) -> NodePoolSpec`.
- Preserves: Collection path expansion and `NodePoolSpec` JSON shape.

- [ ] **Step 1: Add failing direct-source tests**

覆盖：

```python
def test_folder_source_is_relative_to_action_root(self):
    action_root = root / "动作改2"
    self._node(action_root / "new", "a")
    result = self._resolver(root).scan(
        "action",
        NodePoolSpec.model_validate({"source": {"type": "folder", "value": "new"}}),
    )
    self.assertEqual([item.relative for item in result.candidates], ["new/a"])
```

另加 Glob `new/*足部*`、绝对路径 400、`../` 400，以及 Collection 原有测试保持通过。

- [ ] **Step 2: Run tests and confirm current design-root behavior fails**

Run: `uv run python -m pytest tests/test_node_pools.py tests/test_web_node_pools.py -q`

Expected: FAIL because direct Folder currently resolves from `design_root`.

- [ ] **Step 3: Normalize only direct Folder/Glob sources**

在 `NodePoolResolver.scan()` 调用 Selector 前：

```python
source = spec.source
relative_root = None
if source.type in {"folder", "glob"}:
    resolved = resolve_role_relative_path(self.design_root, role, source.value)
    source = source.model_copy(update={"value": str(resolved)})
    relative_root = primary_role_root(self.design_root, role).resolve()
```

Collection 不经过该分支，继续传入原 `spec.source`。

- [ ] **Step 4: Return candidate.relative from the role root**

调整 `_relative()` 接收可选 `relative_root`：

```python
def _relative(self, path: Path, *, root: Path | None = None) -> str | None:
    base = root or self.design_root
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return None
```

直接 Folder/Glob 使用角色根目录，Collection 使用 design root，保持现有工程引用可追踪。

- [ ] **Step 5: Update Web API fixtures and assertions**

`test_sample_returns_full_nodes_without_replacement` 的输入从：

```json
{"source": {"type": "folder", "value": "动作改2"}}
```

改为：

```json
{"source": {"type": "folder", "value": "."}}
```

并断言返回 `candidate.relative` 不包含 `动作改2/` 前缀。

- [ ] **Step 6: Run backend regression**

Run: `uv run python -m pytest tests/test_node_pools.py tests/test_web_node_pools.py tests/test_web_nodes.py -q`

Expected: PASS；Collection 测试输出不变，Folder/Glob 使用角色根目录。

- [ ] **Step 7: Commit only Task 2 files**

```powershell
git add src/tags_machine_core/node_pools/resolver.py tests/test_node_pools.py tests/test_web_node_pools.py
git commit --only src/tags_machine_core/node_pools/resolver.py tests/test_node_pools.py tests/test_web_node_pools.py -m "fix: resolve random pools from role roots"
```

---

### Task 3: 可搜索多选分类过滤器

**Files:**
- Create: `web/src/components/ClassifyFilterEditor.tsx`
- Create: `web/src/components/ClassifyFilterEditor.test.tsx`
- Modify: `web/src/components/RandomNodeEditor.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `ClassifyFilter`, `CLASSIFY_FIELDS`, `CLASSIFY_OPTIONS`.
- Produces: `ClassifyFilterEditor({ value, facets, onChange })`.
- Preserves: `NodePoolSpec.filters.classify` as ten string arrays.

- [ ] **Step 1: Add focused interaction tests**

测试组件：

```tsx
render(<ClassifyFilterEditor value={emptyFilter} facets={{}} onChange={onChange} />);
fireEvent.click(screen.getByRole("button", { name: "添加筛选" }));
fireEvent.click(screen.getByRole("button", { name: "Domain" }));
fireEvent.click(screen.getByRole("button", { name: "选择 Domain 值" }));
fireEvent.click(screen.getByRole("checkbox", { name: "foot" }));
fireEvent.click(screen.getByRole("checkbox", { name: "body" }));
expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ domain: ["foot", "body"] }));
```

另覆盖标签 `×`、字段清空、清空全部、搜索值和最后一个值移除字段。

- [ ] **Step 2: Run the component test and confirm missing component failure**

Run: `cd web; npm test -- ClassifyFilterEditor.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement ClassifyFilterEditor**

组件状态：

```ts
const persistedFields = CLASSIFY_FIELDS.filter((field) => value[field].length > 0);
const [draftFields, setDraftFields] = useState<Array<keyof ClassifyFilter>>([]);
const activeFields = [...new Set([...persistedFields, ...draftFields])];
```

值来源：

```ts
const options = [...new Set([
  ...CLASSIFY_OPTIONS[field],
  ...(facets[field] ?? []),
  ...value[field],
])].sort();
```

复选框点击生成完整下一状态并调用 `onChange`；取消最后一个值时从 `draftFields` 移除该字段。

- [ ] **Step 4: Integrate into RandomNodeEditor**

删除 `labels`、`facetValues()` 和原生 `<select multiple>` 网格，替换为：

```tsx
<ClassifyFilterEditor
  facets={scan?.facets ?? {}}
  onChange={(classify) => update({ ...spec, filters: { classify } })}
  value={spec.filters.classify}
/>
```

Folder/Glob 文案改为：

```tsx
<span>{spec.source.type === "folder" ? `相对 ${roleLabel(slot.role)} 根目录` : `相对 ${roleLabel(slot.role)} 根目录的 Glob`}</span>
```

Action placeholder 使用 `new` 和 `new/*足部*`，不再包含 `动作改2/`。

- [ ] **Step 5: Add restrained component styling**

增加：

```css
.classify-filter-list { display: grid; gap: 8px; }
.classify-filter-row { border: 1px solid #d9e0e9; border-radius: 6px; padding: 10px; }
.classify-filter-chip { align-items: center; display: inline-flex; gap: 4px; }
.classify-option-popover { max-height: 240px; overflow-y: auto; position: absolute; z-index: 20; }
```

移除旧 `.classify-filter-grid` 和 `.classify-filter-grid select` 样式。

- [ ] **Step 6: Run frontend tests and build**

Run: `cd web; npm test -- ClassifyFilterEditor.test.tsx`

Expected: PASS.

Run: `cd web; npm test`

Expected: all frontend tests PASS.

Run: `cd web; npm run build`

Expected: TypeScript and Vite build PASS.

- [ ] **Step 7: Commit only Task 3 files**

```powershell
git add web/src/components/ClassifyFilterEditor.tsx web/src/components/ClassifyFilterEditor.test.tsx web/src/components/RandomNodeEditor.tsx web/src/styles.css
git commit --only web/src/components/ClassifyFilterEditor.tsx web/src/components/ClassifyFilterEditor.test.tsx web/src/components/RandomNodeEditor.tsx web/src/styles.css -m "feat: improve random node classify filters"
```

---

### Task 4: Web 业务验收与 NovelAI 真实出图

**Files:**
- Create: `docs/web_random_node_role_root_filter_business_test_20260726.md`

**Interfaces:**
- Consumes: existing `scripts/dev_web.py`, Web Custom Generate, PNG metadata inspector.
- Produces: concrete browser results, output image paths and PNG metadata conclusions.

- [ ] **Step 1: Start the real Web service**

Run: `uv run python scripts/dev_web.py`

Expected: backend and frontend both start; use the printed ports rather than assuming `8765` is available.

- [ ] **Step 2: Verify role-relative Folder and Glob in the browser**

Action 随机节点分别输入：

```text
Folder: new
Glob: new/*足部*
```

确认候选可加载、候选辅助路径不含 `动作改2/`，绝对路径和 `../角色` 显示明确错误。

- [ ] **Step 3: Verify filter interaction in the browser**

添加 `Domain`，多选 `foot`、`body`，取消 `body`；再添加 `Subtype=sole_focus`。确认候选统计即时更新。点击清空全部，确认未标注节点重新参与原始候选扫描。

- [ ] **Step 4: Run one real NovelAI generation**

使用固定 Artist、固定 Character、Action Folder=`new`，加入 `Domain=foot` 和 `Subtype=sole_focus`，生成一张图片。记录实际输出路径。

- [ ] **Step 5: Inspect PNG metadata from the generated file**

Run:

```powershell
uv run python -m tags_machine_core inspect-image-params '<generated.png>' --normalized
```

确认：

- PNG 可读取。
- `tags_machine_core.random_nodes` 包含本次实际 Action ref。
- Action ref 位于 `<design_root>/动作改2/new`。
- 选中 Action 的 `classify.yaml` 满足 `domain=foot` 和 `subtype=sole_focus`。

- [ ] **Step 6: Run AgentComposer regression through the existing fixed-node path**

固定 Artist、Character、Action 执行一次 Preview；确认最终 Prompt 正常，后端日志中 AgentComposer 输入仍为普通 `NodeDocument`，没有 `NodePoolSpec` 或分类 UI 状态。

- [ ] **Step 7: Write the business acceptance report**

报告包含：

```markdown
- Web URL
- Folder/Glob 扫描结果
- 多选与取消结果
- 候选统计变化
- NovelAI 图片绝对路径
- PNG random_nodes 摘要
- AgentComposer 回归结论
- 已知限制
```

- [ ] **Step 8: Commit only the report**

```powershell
git add docs/web_random_node_role_root_filter_business_test_20260726.md
git commit --only docs/web_random_node_role_root_filter_business_test_20260726.md -m "docs: validate random node role roots and filters"
```

---

## Final Verification

- [ ] `uv run python -m pytest tests/test_node_pools.py tests/test_web_node_pools.py tests/test_web_nodes.py -q`
- [ ] `cd web; npm test`
- [ ] `cd web; npm run build`
- [ ] 浏览器完成 Folder、Glob、多选、取消、清空全部流程。
- [ ] NovelAI 至少真实生成一张图片并从 PNG 读取随机节点元数据。
- [ ] `git status --short` 中用户原有无关变更仍存在且未混入本功能提交。
