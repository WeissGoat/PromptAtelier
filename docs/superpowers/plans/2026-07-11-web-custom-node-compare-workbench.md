# Web Custom Node Compare Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Custom 页面重构为可持久化的节点工作台，提供浮动搜索、中央结构化编辑器、多个节点级 Compare 和笛卡尔积批量出图。

**Architecture:** `CustomWorkspaceProvider` 在 App 导航之上持有主节点、Compare 节点、编辑草稿、参数和运行状态，并把可恢复输入写入版本化 localStorage。普通 Generate 与 Compare Generate 共用请求构造器；Compare 通过纯函数展开节点笛卡尔积，再由 App 级控制器以并发 2 顺序提交 Preview、Generate 和 Job 轮询。

**Tech Stack:** React 19、TypeScript、Vitest、FastAPI 现有 Web API、NovelAI 现有 Renderer、浏览器 localStorage。

## Global Constraints

- 本计划在当前任务内直接执行，不使用子 agent。
- Compare 是节点级能力，删除独立 Compare 页面和导航入口。
- 每种 role 使用一个 primary 和任意数量 compare slots。
- 普通 Generate 只使用 primary，并继续使用 NT。
- Compare Generate 每组合固定 `n_samples=1`，总图片数严格等于笛卡尔积数量。
- 某 role 没有节点时按一个 `null` 参与组合；Character 和 Action 至少有一类存在。
- 临时编辑和 Compare 删除不得自动写节点库；只有显式 Save 才调用 `/nodes/save`。
- 节点搜索和界面标题只显示文件夹名称，内部仍使用精确 ref。
- 工作台输入写入 `promptatelier.custom-workspace/v1`；运行中的 Job 不写 localStorage。
- Negative 初始为空字符串。
- 不修改 ScriptComposer、AgentComposer、Renderer 或 NodeDocument 后端语义。
- 最终业务验收使用 fresh backend 和真实 NovelAI `2 × 1 × 2 = 4` 小矩阵。

---

## File Structure

- Create `web/src/workspace/types.ts`: 工作台、节点组、编辑器和参数类型。
- Create `web/src/workspace/storage.ts`: v1 localStorage 序列化、恢复和校验。
- Create `web/src/workspace/CustomWorkspaceProvider.tsx`: App 级状态、节点操作、编辑草稿和持久化。
- Create `web/src/workspace/requestBuilder.ts`: 普通和 Compare 共用 compose/render 请求构造。
- Create `web/src/compare/matrix.ts`: 纯笛卡尔积展开和数量计算。
- Create `web/src/compare/useCompareRunController.ts`: 并发 2 的 Preview、Generate、Job 轮询控制。
- Create `web/src/components/NodeRoleGroup.tsx`: primary 与多个 compare slots。
- Create `web/src/components/NodeWorkspaceEditor.tsx`: 中栏表单/JSON 编辑器。
- Create `web/src/components/StructuredValueEditor.tsx`: 扩展字段递归键值编辑。
- Create `web/src/components/CustomGeneratePanel.tsx`: 普通和 Compare 生成按钮及结果。
- Modify `web/src/components/NodePicker.tsx`: 聚焦浮层、前 6 条、名称显示和关闭交互。
- Modify `web/src/components/NodeSlot.tsx`: 适配稳定 slotId 与 primary/compare 模式。
- Modify `web/src/pages/CustomStudio.tsx`: 只负责三栏布局和组件协调。
- Modify `web/src/App.tsx` and `web/src/components/Layout.tsx`: Provider 提升并删除 Compare 导航。
- Delete `web/src/pages/CompareStudio.tsx` and its tests/imports。
- Modify `web/src/styles.css`: 浮层搜索、中栏编辑器和矩阵结果布局。
- Modify `docs/web_control_console_readme.md`: 新工作台使用说明。

---

### Task 1: Workspace State, Navigation and Persistence

**Files:**
- Create: `web/src/workspace/types.ts`
- Create: `web/src/workspace/storage.ts`
- Create: `web/src/workspace/storage.test.ts`
- Create: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Create: `web/src/workspace/CustomWorkspaceProvider.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/Layout.tsx`
- Delete: `web/src/pages/CompareStudio.tsx`

**Interfaces:**
- Produces: `NodeVariantSlot`, `RoleNodeGroup`, `CustomWorkspaceState`, `useCustomWorkspace()`, `loadWorkspaceSnapshot()`, `saveWorkspaceSnapshot()`.
- Consumes: existing `NodeDocument`, `NodeRole`, `ComposePreviewResponse` and localStorage.

- [ ] **Step 1: Define the workspace contracts**

Create `web/src/workspace/types.ts`:

```ts
import type { ComposePreviewResponse } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";

export type SlotMode = "primary" | "compare";

export type NodeVariantSlot = {
  slotId: string;
  role: NodeRole;
  mode: SlotMode;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
};

export type RoleNodeGroup = {
  primary: NodeVariantSlot;
  compares: NodeVariantSlot[];
};

export type RenderWorkspaceParams = {
  negative: string;
  width: number;
  height: number;
  nt: number;
  seed: string;
};

export type WorkspaceEditorState = {
  slotId: string | null;
  tab: "form" | "json";
  draftNode: NodeDocument | null;
  baselineNode: NodeDocument | null;
};

export type CustomWorkspaceState = {
  schema: "promptatelier.custom-workspace/v1";
  groups: Record<NodeRole, RoleNodeGroup>;
  params: RenderWorkspaceParams;
  editor: WorkspaceEditorState;
  preview: ComposePreviewResponse | null;
  revision: number;
};
```

Use `crypto.randomUUID()` for new compare slot IDs, with a deterministic fallback `slot-${Date.now()}-${counter}` for test/jsdom environments.

- [ ] **Step 2: Write storage behavior tests**

Create tests covering:

```ts
it("round-trips primary, compare and temporary nodes");
it("restores negative as an empty string by default");
it("rejects malformed JSON without deleting the stored value");
it("rejects a snapshot with a different schema");
it("does not persist compare jobs or async controller state");
```

The expected storage key is exactly:

```ts
export const CUSTOM_WORKSPACE_STORAGE_KEY = "promptatelier.custom-workspace/v1";
```

- [ ] **Step 3: Implement versioned localStorage**

Create `storage.ts` with:

```ts
export type WorkspaceLoadResult =
  | { status: "empty"; state: CustomWorkspaceState }
  | { status: "loaded"; state: CustomWorkspaceState }
  | { status: "invalid"; state: CustomWorkspaceState; message: string };

export function createEmptyWorkspace(): CustomWorkspaceState;
export function loadWorkspaceSnapshot(storage: Storage): WorkspaceLoadResult;
export function saveWorkspaceSnapshot(storage: Storage, state: CustomWorkspaceState): void;
export function clearWorkspaceSnapshot(storage: Storage): void;
```

`createEmptyWorkspace()` must create three primary slots and initialize:

```ts
params: { negative: "", width: 1024, height: 1024, nt: 1, seed: "-1" }
```

Before saving, project the state to serializable input fields only; omit runtime controller state and in-flight jobs.

- [ ] **Step 4: Implement CustomWorkspaceProvider**

Expose these operations:

```ts
selectNode(slotId: string, ref: string, node: NodeDocument): void;
createBlank(slotId: string): void;
updateDraft(slotId: string, node: NodeDocument): void;
restoreSlot(slotId: string): void;
clearSlot(slotId: string): void;
addCompare(role: NodeRole): string;
removeCompare(slotId: string): void;
openEditor(slotId: string): void;
closeEditor(): void;
setEditorTab(tab: "form" | "json"): void;
setParams(patch: Partial<RenderWorkspaceParams>): void;
setPreview(preview: ComposePreviewResponse | null): void;
resetWorkspace(): void;
findSlot(slotId: string): NodeVariantSlot | null;
```

Persist state with a 250ms debounce. Keep the provider mounted above page navigation so switching tabs does not reset it.

- [ ] **Step 5: Remove Compare navigation and mount Provider**

Change PageKey to:

```ts
export type PageKey = "custom" | "batch" | "results";
```

Wrap Layout with `CustomWorkspaceProvider` in `App.tsx`. Delete the Compare import, route mapping and navigation button. Delete `CompareStudio.tsx`.

- [ ] **Step 6: Verify persistence and navigation**

Run:

```powershell
cd web
npm run test -- src/workspace/storage.test.ts src/workspace/CustomWorkspaceProvider.test.tsx
npm run build
```

Expected: storage/provider tests pass and the app builds without CompareStudio references.

- [ ] **Step 7: Commit Task 1**

```powershell
git add web/src/workspace web/src/App.tsx web/src/components/Layout.tsx web/src/pages/CompareStudio.tsx
git commit -m "feat: persist custom workspace state"
```

---

### Task 2: Floating Search and Multiple Node Slots

**Files:**
- Modify: `web/src/components/NodePicker.tsx`
- Modify: `web/src/components/NodeSlot.tsx`
- Create: `web/src/components/NodeRoleGroup.tsx`
- Modify: `web/src/components/NodePicker.test.tsx`
- Modify: `web/src/components/NodeSlot.test.tsx`
- Create: `web/src/components/NodeRoleGroup.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `NodeVariantSlot`, Provider node operations, `/api/nodes?role=...&q=...&limit=6`.
- Produces: floating `NodePicker` and role groups with primary plus multiple compare slots.

- [ ] **Step 1: Write floating-search interaction tests**

Cover these exact behaviors:

```tsx
it("loads at most six nodes when the input receives focus");
it("debounces typed queries by 300ms");
it("shows only NodeSummary.name for every option");
it("closes after selecting an exact NodeSummary ref");
it("closes on Escape and outside pointer down");
it("ignores a stale response from an older query");
```

Assert that `relative` and full `ref` text are absent from rendered option text.

- [ ] **Step 2: Rewrite NodePicker as a combobox**

Use state:

```ts
const [open, setOpen] = useState(false);
const requestId = useRef(0);
const rootRef = useRef<HTMLDivElement>(null);
```

On focus, set open and call search with current text, including an empty query. Send `limit=6`. Use a document `pointerdown` listener and `Escape` key handler to close. Use `onMouseDown` on an option so selection completes before input blur.

Render the result container with absolute positioning under `.node-picker` and display only:

```tsx
<span>{node.name}</span>
```

Remove RefreshCw and the permanent loaded-count hint.

- [ ] **Step 3: Adapt NodeSlot to NodeVariantSlot**

Change the component contract:

```ts
type NodeSlotProps = {
  slot: NodeVariantSlot;
  onSelect(ref: string, node: NodeDocument): void;
  onCreateBlank(): void;
  onRestore(): void;
  onClear(): void;
  onEdit(): void;
  onRemove?: () => void;
};
```

Primary slots show restore/clear and Compare slots show a `Compare` badge plus delete. Both support edit and exact-ref selection. Preserve pending-read invalidation when the slot identity changes.

- [ ] **Step 4: Implement NodeRoleGroup**

Render one role heading, `Plus` icon with tooltip `新增 Compare`, primary NodeSlot and all compare NodeSlots. `addCompare(role)` appends an empty slot; `removeCompare(slotId)` confirms only when the slot contains temporary modifications.

- [ ] **Step 5: Style the dropdown and compact groups**

Set `.node-picker { position: relative; }` and `.node-picker-results` to absolute positioning with a stable max height and z-index. Ensure opening results does not change Nodes column height. Compare rows must retain stable button dimensions.

- [ ] **Step 6: Run focused UI verification**

```powershell
cd web
npm run test -- src/components/NodePicker.test.tsx src/components/NodeSlot.test.tsx src/components/NodeRoleGroup.test.tsx
npm run build
```

Expected: search, exact ref selection and multiple compare slots pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add web/src/components/NodePicker.tsx web/src/components/NodePicker.test.tsx web/src/components/NodeSlot.tsx web/src/components/NodeSlot.test.tsx web/src/components/NodeRoleGroup.tsx web/src/components/NodeRoleGroup.test.tsx web/src/styles.css
git commit -m "feat: add floating node compare slots"
```

---

### Task 3: Central Structured Node Editor

**Files:**
- Create: `web/src/components/StructuredValueEditor.tsx`
- Create: `web/src/components/StructuredValueEditor.test.tsx`
- Create: `web/src/components/NodeWorkspaceEditor.tsx`
- Create: `web/src/components/NodeWorkspaceEditor.test.tsx`
- Delete: `web/src/components/NodeEditorDrawer.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: active `NodeVariantSlot`, Provider editor state, `/api/nodes/preview`, `/api/nodes/save`.
- Produces: central table/JSON editor with lossless NodeDocument updates.

- [ ] **Step 1: Write lossless structured editing tests**

Create a NodeDocument fixture containing prompt fragments, tags, renderers, composition, generation and an unknown extra key. Verify:

```tsx
it("edits core fields without dropping unknown keys");
it("adds and removes prompt fragments and tag groups");
it("edits nested objects, arrays, booleans and numbers");
it("syncs form changes into the JSON tab");
it("parses valid JSON back into the form");
it("keeps invalid JSON and displays validation errors");
it("confirms before switching or closing with unapplied edits");
```

- [ ] **Step 2: Implement StructuredValueEditor**

Use a recursive immutable update contract:

```ts
type StructuredValueEditorProps = {
  value: unknown;
  path: Array<string | number>;
  onChange(next: unknown): void;
  onRemove?(): void;
};
```

Render:

- object as key/value rows with add-property command;
- array as indexed rows with add/remove commands;
- boolean as checkbox;
- number as numeric input;
- string as input or textarea when long;
- null with a type selector.

Never stringify the whole document to apply a single form change.

- [ ] **Step 3: Implement NodeWorkspaceEditor form sections**

Keep one `NodeDocument` draft and one JSON text representation. Render fixed core fields and prompt/tags sections directly. Pass extension fields to StructuredValueEditor. Determine extension keys by excluding:

```ts
new Set(["schema", "kind", "id", "name", "description", "prompt", "tags"])
```

Preserve every other property in the draft object.

- [ ] **Step 4: Implement Apply, Save and close semantics**

- Apply calls `/nodes/preview`, then Provider `updateDraft(slotId, normalizedNode)`.
- Save uses the current sourceRef or a target-ref field for blank nodes, calls `/nodes/save`, then Provider `selectNode(slotId, saved.ref, saved.node)`.
- Changing active slot or closing with dirty draft requires confirmation.
- Successful Apply/Save updates the baseline before returning to Prompt Preview.

- [ ] **Step 5: Replace drawer styles with central workspace styles**

Delete backdrop/drawer CSS. Add stable tabs, section tables, prompt rows and a scrollable editor body. The middle column must retain its dimensions when switching Preview and Editor.

- [ ] **Step 6: Run editor tests and build**

```powershell
cd web
npm run test -- src/components/StructuredValueEditor.test.tsx src/components/NodeWorkspaceEditor.test.tsx
npm run build
```

Expected: lossless round trip tests pass and no NodeEditorDrawer imports remain.

- [ ] **Step 7: Commit Task 3**

```powershell
git add web/src/components/StructuredValueEditor.tsx web/src/components/StructuredValueEditor.test.tsx web/src/components/NodeWorkspaceEditor.tsx web/src/components/NodeWorkspaceEditor.test.tsx web/src/styles.css
git add -u web/src/components/NodeEditorDrawer.tsx
git commit -m "feat: add central structured node editor"
```

---

### Task 4: Shared Request Builder and Compare Matrix Generation

**Files:**
- Create: `web/src/workspace/requestBuilder.ts`
- Create: `web/src/workspace/requestBuilder.test.ts`
- Create: `web/src/compare/matrix.ts`
- Create: `web/src/compare/matrix.test.ts`
- Create: `web/src/compare/useCompareRunController.ts`
- Create: `web/src/compare/useCompareRunController.test.tsx`
- Create: `web/src/components/CustomGeneratePanel.tsx`
- Create: `web/src/components/CustomGeneratePanel.test.tsx`
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`

**Interfaces:**
- Consumes: workspace groups/params, existing compose-preview/generate/jobs API.
- Produces: exact matrix combinations, normal/compare request payloads, App-level compare progress/results.

- [ ] **Step 1: Write matrix expansion tests**

Define:

```ts
export type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};

export function selectedSlots(group: RoleNodeGroup): NodeVariantSlot[];
export function compareCount(groups: Record<NodeRole, RoleNodeGroup>): number;
export function buildCompareMatrix(groups: Record<NodeRole, RoleNodeGroup>): CompareCombination[];
```

Verify:

```ts
2 artists * 3 characters * 2 actions === 12;
0 artists * 1 character * 2 actions === 2; // artist null factor is one
empty compare slots are excluded;
same ref in different slotIds creates separate combinations;
combinationId is stable for the same ordered slotIds;
```

- [ ] **Step 2: Extract the shared request builder**

Define:

```ts
type SelectedNodes = {
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};

export function buildComposeRenderRequest(
  selected: SelectedNodes,
  params: RenderWorkspaceParams,
  options: { compare: boolean },
): Record<string, unknown>;
```

Rules:

- original slots serialize as ref only;
- modified/temporary slots serialize inline;
- inline Artist is not also passed as `render.artist`;
- normal mode uses `params.nt`;
- compare mode forces `n_samples: 1`;
- negative defaults to empty string;
- seed `-1` is omitted.

- [ ] **Step 3: Write compare controller tests**

Use fake API promises to prove:

```tsx
it("runs no more than two combinations concurrently");
it("previews before generating every combination");
it("polls each job to a terminal state");
it("continues after one combination fails");
it("keeps running when CustomStudio unmounts");
it("records node names and slotIds with every result");
it("does not persist runtime jobs to localStorage");
```

- [ ] **Step 4: Implement useCompareRunController**

Expose:

```ts
type CompareRunSummary = {
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
};

start(groups: Record<NodeRole, RoleNodeGroup>, params: RenderWorkspaceParams): Promise<void>;
reset(): void;
summary: CompareRunSummary;
results: CompareCombinationResult[];
running: boolean;
```

Implement a two-worker queue. Each worker takes the next combination, calls `/compose-preview`, then `/generate`, then polls `/jobs/{id}` every 500ms. Store controller state in the Provider, not in CustomStudio.

- [ ] **Step 5: Implement CustomGeneratePanel**

Render:

- ordinary Preview and Generate controls;
- `Compare Generate · N` button;
- confirmation text `Artist n × Character m × Action k = N 张`;
- compare aggregate progress;
- result cards with three node names, seed, status, image and error.

Ordinary controls must use only primary nodes. Compare controls use the full matrix.

- [ ] **Step 6: Run matrix/controller tests**

```powershell
cd web
npm run test -- src/compare/matrix.test.ts src/compare/useCompareRunController.test.tsx src/workspace/requestBuilder.test.ts src/components/CustomGeneratePanel.test.tsx
npm run build
```

Expected: `2 × 3 × 2` produces 12 tasks, concurrency never exceeds 2, and normal NT remains independent.

- [ ] **Step 7: Commit Task 4**

```powershell
git add web/src/compare/matrix.ts web/src/compare/matrix.test.ts web/src/compare/useCompareRunController.ts web/src/compare/useCompareRunController.test.tsx web/src/workspace/requestBuilder.ts web/src/workspace/requestBuilder.test.ts web/src/workspace/CustomWorkspaceProvider.tsx web/src/components/CustomGeneratePanel.tsx web/src/components/CustomGeneratePanel.test.tsx
git commit -m "feat: add node matrix compare generation"
```

---

### Task 5: Custom Layout Integration and Business Acceptance

**Files:**
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Modify: `web/src/styles.css`
- Modify: `docs/web_control_console_readme.md`

**Interfaces:**
- Consumes: Provider, NodeRoleGroup, NodeWorkspaceEditor, PromptPreview, CustomGeneratePanel.
- Produces: final three-column Custom workbench and user documentation.

- [ ] **Step 1: Rewrite CustomStudio as layout composition**

The page should primarily compose components:

```tsx
<CustomNodesPanel />
<CustomWorkspaceCenter />
<CustomGeneratePanel />
```

`CustomWorkspaceCenter` renders NodeWorkspaceEditor when `editor.slotId` exists, otherwise PromptPreview. Remove local ownership of nodes, params, preview and compare jobs from CustomStudio.

- [ ] **Step 2: Add full workflow tests**

Cover:

```tsx
it("does not reset workspace after navigating Custom -> Batch -> Custom");
it("restores workspace after remount from localStorage");
it("opens node editing in the center column");
it("adds and deletes multiple compare nodes");
it("ordinary Generate uses primary slots and NT");
it("Compare Generate expands all selected slots and fixes n_samples to one");
it("starts with an empty Negative prompt");
it("has no Compare navigation entry");
```

- [ ] **Step 3: Update responsive styles**

Desktop uses three columns with a wider central editor. At widths below 1100px use two rows; below 760px stack all panels. Search floating layers must stay within viewport and editor text must not overlap controls.

- [ ] **Step 4: Update the Web guide**

Document:

- focus-search behavior;
- primary and Compare nodes;
- form/JSON node editing;
- localStorage recovery and reset;
- ordinary Generate versus Compare Generate;
- exact matrix count and `n_samples=1` rule;
- start command using an allowed backend port on this machine:

```powershell
uv run python scripts/dev_web.py --backend-port 8877
```

- [ ] **Step 5: Run fresh automated verification**

```powershell
uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_compose tests.test_web_results tests.test_web_batch tests.test_novelai_artist_dedup -v
cd web
npm run test
npm run build
```

Expected: all scoped backend tests, all frontend tests and production build pass.

- [ ] **Step 6: Perform real browser workflow verification**

Start a fresh service:

```powershell
uv run python scripts/dev_web.py --backend-port 8877
```

Verify in the browser:

1. Focus each search box and confirm at most six filename-only results.
2. Select primary nodes, add multiple Compare slots and temporarily edit one in the central form.
3. Navigate to Batch and back; confirm state remains.
4. Reload the page; confirm localStorage restores input.
5. Run ordinary Generate with NT 1 and confirm exactly one image.
6. Configure `2 Artist × 1 Character × 2 Action` and run Compare Generate.
7. Confirm exactly four succeeded image results, each showing the correct node names and seed.
8. Confirm no source node file changes unless Save was explicitly clicked.

- [ ] **Step 7: Commit Task 5**

```powershell
git add web/src/pages/CustomStudio.tsx web/src/pages/CustomStudio.test.tsx web/src/styles.css docs/web_control_console_readme.md
git add -u web/src/pages
git commit -m "feat: complete custom compare workbench"
```
