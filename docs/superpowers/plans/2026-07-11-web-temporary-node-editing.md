# Web Temporary Node Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Custom 页面支持已有节点临时编辑与空白临时节点，并保证 Preview、Generate 和 AgentComposer 使用同一份未落盘的节点内容。

**Architecture:** 前端用 `useTemporaryNodes` 维护 Artist、Character、Action 三个槽位的来源节点和会话草稿；`NodeEditorDrawer` 只编辑标准 `NodeDocument`。请求序列化时，原始未修改节点只传 `ref`，临时修改或空白节点传 `{role, ref, node}`，继续进入现有 `GenerationJsonApi -> ResolvedNodeSet -> Composer -> Renderer` 链路。

**Tech Stack:** React 19、TypeScript、Vitest、FastAPI、Pydantic v2、现有 `GenerationJsonApi` 与 `NodeDocument`。

## Global Constraints

- 临时草稿只存在于当前浏览器标签页内，刷新即清空。
- Preview 和 Generate 不得自动调用 `/api/nodes/save`。
- 不创建后端 session cache、临时节点文件或新的临时节点领域模型。
- ScriptComposer、AgentComposer、PromptPolicyPipeline 和 Renderer 不增加临时节点业务分支。
- 用户明确点击保存后才写入节点库。
- 业务验收优先：最终必须通过浏览器完成临时编辑、预览和真实生成链路验证。

---

## File Structure

- Create `web/src/nodes/types.ts`: Web 使用的 `NodeDocument`、节点读取响应和节点槽位类型。
- Create `web/src/nodes/temporaryNodes.ts`: 空白模板、dirty 比较和 compose 请求序列化纯函数。
- Create `web/src/nodes/useTemporaryNodes.ts`: 管理三个节点槽位的会话状态。
- Create `web/src/components/NodeSlot.tsx`: 节点搜索、状态标识和操作入口。
- Replace `web/src/components/NodeEditor.tsx` with `NodeEditorDrawer.tsx`: 节点查看、临时编辑、校验、恢复和显式保存。
- Modify `web/src/pages/CustomStudio.tsx`: 接入节点模式、临时节点、Preview 快照失效和 Generate。
- Modify `web/src/api/types.ts`: 引用统一节点类型，扩充节点读取响应。
- Modify `web/src/styles.css`: 节点槽位、抽屉、状态标识和响应式布局。
- Modify `src/tags_machine_core/web/routes/nodes.py`: 把节点预览和保存的校验错误转换为稳定 JSON 错误。
- Modify focused frontend/backend tests and Web 使用文档。

---

### Task 1: Temporary Node State and Serialization

**Files:**
- Create: `web/src/nodes/types.ts`
- Create: `web/src/nodes/temporaryNodes.ts`
- Create: `web/src/nodes/temporaryNodes.test.ts`
- Create: `web/src/nodes/useTemporaryNodes.ts`
- Test: `web/src/nodes/temporaryNodes.test.ts`

**Interfaces:**
- Produces: `NodeDocument`, `NodeSlotState`, `createTemporaryNode(role)`, `nodeSlotStatus(slot)`, `serializeNodeSlot(slot)`, `hasUsablePositivePrompt(node)`, `useTemporaryNodes()`.
- Consumes: existing `/api/nodes/read` response and `compose.nodes[]` request contract.

- [ ] **Step 1: Define the frontend node and slot contracts**

Create `web/src/nodes/types.ts` with the JSON shape actually accepted by Pydantic:

```ts
export type NodeRole = "artist" | "character" | "action";

export type PromptFragment = {
  text: string;
  role?: string | null;
  weight?: number | null;
  include_scopes?: string[];
  exclude_scopes?: string[];
  notes?: string[];
};

export type NodeDocument = {
  schema: "tags-machine-core.node/v1";
  kind: NodeRole | "background" | "vibe" | "story" | "unknown";
  id: string;
  name?: string | null;
  description?: string | null;
  prompt: {
    positive: PromptFragment[];
    negative: PromptFragment[];
  };
  [key: string]: unknown;
};

export type NodeSlotState = {
  role: NodeRole;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
};

export type NodeSlotStatus = "empty" | "original" | "modified" | "temporary";

export type ComposeNodeInput = {
  role: NodeRole;
  ref: string;
  node?: NodeDocument;
};
```

- [ ] **Step 2: Write focused serialization tests**

Create `web/src/nodes/temporaryNodes.test.ts` covering the business contract:

```ts
import { describe, expect, it } from "vitest";
import {
  createTemporaryNode,
  hasUsablePositivePrompt,
  nodeSlotStatus,
  serializeNodeSlot,
} from "./temporaryNodes";

describe("temporary node slots", () => {
  it("serializes an unchanged library node as a ref only", () => {
    const node = createTemporaryNode("character", "homura");
    const slot = { role: "character" as const, sourceRef: "F:/design/homura", sourceNode: node, draftNode: node };
    expect(nodeSlotStatus(slot)).toBe("original");
    expect(serializeNodeSlot(slot)).toEqual({ role: "character", ref: "F:/design/homura" });
  });

  it("serializes modified content inline", () => {
    const source = createTemporaryNode("action", "standing");
    const draft = structuredClone(source);
    draft.prompt.positive = [{ text: "standing, looking_at_viewer" }];
    const slot = { role: "action" as const, sourceRef: "F:/design/standing", sourceNode: source, draftNode: draft };
    expect(nodeSlotStatus(slot)).toBe("modified");
    expect(serializeNodeSlot(slot)).toEqual({ role: "action", ref: "F:/design/standing", node: draft });
  });

  it("serializes a blank-origin draft with a web temporary ref", () => {
    const draft = createTemporaryNode("character", "temporary-character");
    draft.prompt.positive = [{ text: "1girl, black_hair" }];
    const slot = { role: "character" as const, sourceRef: null, sourceNode: null, draftNode: draft };
    expect(nodeSlotStatus(slot)).toBe("temporary");
    expect(serializeNodeSlot(slot)?.ref).toBe("web-temporary:character:temporary-character");
  });

  it("requires non-empty positive prompt before generation", () => {
    const node = createTemporaryNode("character", "draft");
    expect(hasUsablePositivePrompt(node)).toBe(false);
    node.prompt.positive = [{ text: "  " }, { text: "1girl" }];
    expect(hasUsablePositivePrompt(node)).toBe(true);
  });
});
```

- [ ] **Step 3: Run the focused test and confirm it fails**

Run:

```powershell
cd web
npm run test -- src/nodes/temporaryNodes.test.ts
```

Expected: FAIL because `temporaryNodes.ts` does not exist.

- [ ] **Step 4: Implement pure temporary-node helpers**

Create `web/src/nodes/temporaryNodes.ts`. Use stable JSON comparison after recursively sorting object keys, so node property order does not create false dirty state. Implement:

```ts
export function createTemporaryNode(role: NodeRole, id = `temporary-${role}`): NodeDocument;
export function nodeSlotStatus(slot: NodeSlotState): NodeSlotStatus;
export function hasUsablePositivePrompt(node: NodeDocument | null): boolean;
export function serializeNodeSlot(slot: NodeSlotState): ComposeNodeInput | null;
export function cloneNode(node: NodeDocument): NodeDocument;
```

`serializeNodeSlot()` rules:

```ts
if (!slot.draftNode) return null;
if (nodeSlotStatus(slot) === "original" && slot.sourceRef) {
  return { role: slot.role, ref: slot.sourceRef };
}
return {
  role: slot.role,
  ref: slot.sourceRef ?? `web-temporary:${slot.role}:${slot.draftNode.id}`,
  node: slot.draftNode,
};
```

- [ ] **Step 5: Implement the state hook**

Create `web/src/nodes/useTemporaryNodes.ts` exposing:

```ts
export function useTemporaryNodes(): {
  slots: Record<NodeRole, NodeSlotState>;
  selectNode(role: NodeRole, ref: string, node: NodeDocument): void;
  createBlank(role: NodeRole): void;
  updateDraft(role: NodeRole, node: NodeDocument): void;
  restore(role: NodeRole): void;
  clear(role: NodeRole): void;
  composeNodes: ComposeNodeInput[];
  revision: number;
};
```

Increment `revision` whenever any slot content changes. Do not use `localStorage`, URL state or backend storage.

- [ ] **Step 6: Run frontend tests**

Run:

```powershell
cd web
npm run test -- src/nodes/temporaryNodes.test.ts
```

Expected: all temporary-node serialization tests PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add web/src/nodes
git commit -m "feat: add temporary node state model"
```

---

### Task 2: Node Slot and Editor Drawer

**Files:**
- Create: `web/src/components/NodeSlot.tsx`
- Create: `web/src/components/NodeEditorDrawer.tsx`
- Create: `web/src/components/NodeEditorDrawer.test.tsx`
- Delete: `web/src/components/NodeEditor.tsx`
- Modify: `web/src/components/NodePicker.tsx`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `NodeSlotState`, `NodeDocument`, helper functions and `apiGet/apiPost`.
- Produces: reusable `NodeSlot` selection UI and `NodeEditorDrawer` draft editor.

- [ ] **Step 1: Extend API response types**

Add to `web/src/api/types.ts`:

```ts
import type { NodeDocument } from "../nodes/types";

export type NodeReadResponse = {
  schema: "tags-machine-core.web.node/v1";
  ref: string;
  node: NodeDocument;
  form: Record<string, unknown>;
  raw?: { filename: string; text: string } | null;
};
```

- [ ] **Step 2: Make NodePicker report an explicit selected ref**

Change `NodePicker` so selecting a result invokes `onSelect(node: NodeSummary)`. Keep `onChange` only for search text if needed; do not treat arbitrary unselected text as a valid node ref.

Required props:

```ts
type NodePickerProps = {
  label: string;
  role: NodeRole;
  value: string;
  placeholder: string;
  minSearchLength?: number;
  onSelect: (node: NodeSummary) => void;
  onClear: () => void;
};
```

- [ ] **Step 3: Create NodeSlot**

`NodeSlot` must:

- render `NodePicker`;
- fetch `/api/nodes/read?ref=...` after selection;
- call `selectNode(role, ref, response.node)`;
- display `原始节点`、`临时修改`、`空白临时节点` or `未选择`;
- expose icon actions for edit, create blank, restore and clear;
- confirm before replacing or clearing a modified/temporary draft.

Use Lucide icons with tooltips; do not place a permanent editor below the selector.

- [ ] **Step 4: Write editor drawer interaction tests**

Create tests that assert:

```tsx
it("keeps edits local until apply is clicked", async () => { /* edit JSON, expect onApply only after click */ });
it("shows validation error for malformed JSON", async () => { /* invalid JSON remains in drawer */ });
it("restores the source node", async () => { /* restore calls onRestore */ });
it("does not call save while applying a temporary edit", async () => { /* apiPut is not invoked */ });
```

Use a concise JSON editor in this iteration because it preserves the full `NodeDocument` without dropping optional fields. Label the actions `应用到本次运行` and `保存到节点库` so the two meanings cannot be confused.

- [ ] **Step 5: Implement NodeEditorDrawer**

Required props:

```ts
type NodeEditorDrawerProps = {
  open: boolean;
  slot: NodeSlotState | null;
  onClose: () => void;
  onApply: (role: NodeRole, node: NodeDocument) => void;
  onRestore: (role: NodeRole) => void;
  onSaved: (role: NodeRole, ref: string, node: NodeDocument) => void;
};
```

Behavior:

- initialize text from `slot.draftNode` when opened;
- parse JSON and verify `kind === slot.role`;
- require non-empty `id`;
- call `/api/nodes/preview` before applying, using `{node: parsedNode}` only if the backend route is adjusted to that envelope; otherwise send the node directly and document the chosen contract consistently;
- apply the normalized node returned by backend validation;
- save only after explicit confirmation and a valid target ref;
- retain text and show errors when validation/save fails.

- [ ] **Step 6: Style the slot and drawer**

Add stable styles for `.node-slot`, `.node-status`, `.drawer-backdrop`, `.node-editor-drawer`, `.drawer-actions` and mobile full-width behavior. The drawer must not resize the main three-column Custom layout when opened.

- [ ] **Step 7: Run component tests and build**

Run:

```powershell
cd web
npm run test -- src/components/NodeEditorDrawer.test.tsx
npm run build
```

Expected: component tests PASS and Vite production build succeeds.

- [ ] **Step 8: Commit Task 2**

```powershell
git add web/src/components web/src/api/types.ts web/src/styles.css
git commit -m "feat: add temporary node editor drawer"
```

---

### Task 3: Custom Studio Preview and Generate Integration

**Files:**
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Modify: `src/tags_machine_core/web/routes/nodes.py`
- Modify: `tests/test_web_nodes.py`

**Interfaces:**
- Consumes: `useTemporaryNodes`, `NodeSlot`, `NodeEditorDrawer`, `/api/compose-preview`, `/api/generate`.
- Produces: Custom node mode where Preview and Generate receive the same inline node drafts.

- [ ] **Step 1: Add stable node-route validation tests**

Add backend tests for:

```python
def test_preview_node_returns_normalized_node(client):
    response = client.post("/api/nodes/preview", json={"node": valid_character_node})
    assert response.status_code == 200
    assert response.json()["node"]["kind"] == "character"

def test_preview_node_returns_json_error_for_invalid_node(client):
    response = client.post("/api/nodes/preview", json={"node": {"kind": "character"}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_node"
```

- [ ] **Step 2: Normalize node preview/save API errors**

Update `nodes.py` so `/nodes/preview` expects `{ "node": {...} }`, catches `ValidationError` and raises:

```python
ApiError(code="invalid_node", message=str(exc), status_code=400)
```

Apply the same error mapping to `/nodes/save`. Keep `NodeWorkspace.preview_node()` and `save_node()` responsible only for model validation and persistence.

- [ ] **Step 3: Rewrite CustomStudio node request construction**

Replace the independent `artist`, `character`, `action`, and unused `nodeDraft` state with `useTemporaryNodes()`.

Construct the compose body from the hook:

```ts
compose: {
  nodes: composeNodes,
  negative,
},
render: {
  backend: "novelai",
  artist: artistSlot.sourceRef ?? undefined,
  width,
  height,
  seed: parsedSeed >= 0 ? parsedSeed : undefined,
  params: { n_samples: nt },
}
```

When Artist is modified or temporary, do not pass only `render.artist`; ensure the inline artist node remains in `compose.nodes` and is copied into render context by `GenerationJsonApi._copy_render_context_nodes()`. Verify the resulting render request contains the effective artist node.

- [ ] **Step 4: Add Preview snapshot invalidation**

Store the `revision` used for the successful preview:

```ts
const [previewRevision, setPreviewRevision] = useState<number | null>(null);
const previewIsCurrent = previewRevision === revision;
```

Whenever the node revision or render parameters change, mark the preview stale. Generate must call `/compose-preview` again when `previewIsCurrent` is false.

- [ ] **Step 5: Add node-mode validation**

Before Preview or Generate:

- require at least one usable Character or Action slot;
- reject temporary/modified slots with no non-empty positive prompt;
- show the failing slot name in the visible page alert;
- leave Artist optional for debugging;
- do not block an unchanged legacy node solely because its normalized prompt is populated from legacy fields after backend read.

- [ ] **Step 6: Update CustomStudio tests**

Add scenarios:

```tsx
it("previews an inline modified character node", async () => { /* inspect POST body */ });
it("previews an inline blank-origin action node", async () => { /* web-temporary ref */ });
it("re-previews before generate after a draft changes", async () => { /* compose-preview called twice */ });
it("blocks generation for a fully empty temporary node", async () => { /* visible error */ });
it("never calls nodes/save during preview or generate", async () => { /* no PUT */ });
```

- [ ] **Step 7: Run focused backend and frontend tests**

Run:

```powershell
uv run python -m unittest tests.test_web_nodes tests.test_web_compose -v
cd web
npm run test -- src/pages/CustomStudio.test.tsx src/nodes/temporaryNodes.test.ts src/components/NodeEditorDrawer.test.tsx
npm run build
```

Expected: all focused tests PASS and the frontend builds.

- [ ] **Step 8: Commit Task 3**

```powershell
git add src/tags_machine_core/web/routes/nodes.py tests/test_web_nodes.py web/src/pages/CustomStudio.tsx web/src/pages/CustomStudio.test.tsx
git commit -m "feat: use temporary nodes in custom generation"
```

---

### Task 4: Business Verification and Documentation

**Files:**
- Modify: `docs/web_control_console_readme.md`
- Modify only if verification exposes a defect: files from Tasks 1-3.

**Interfaces:**
- Consumes: running FastAPI/Vite Web console, configured NovelAI token and existing design root.
- Produces: verified user workflow and operating documentation.

- [ ] **Step 1: Update the Web guide**

Document:

- how to start with `uv run python scripts/dev_web.py`;
- how to select a node and choose `临时编辑`;
- difference between `应用到本次运行` and `保存到节点库`;
- how to create an empty Character or Action node;
- that refresh clears unsaved drafts;
- how state labels identify original, modified and temporary nodes.

- [ ] **Step 2: Start the real Web service**

Run:

```powershell
uv run python scripts/dev_web.py
```

Expected: backend and frontend start without compile/runtime errors, and the browser can open the Custom page.

- [ ] **Step 3: Verify an existing-node temporary edit**

In Custom:

1. Select the configured common Artist.
2. Select one real Character node and one real Action node.
3. Open Character, append a harmless visible tag such as `smile` to positive prompt, and click `应用到本次运行`.
4. Preview and confirm the final positive prompt contains the edit.
5. Confirm the source `meta.yaml` modification time and Git status do not change.

- [ ] **Step 4: Verify a blank-origin temporary action**

Clear Action, click `新建空白`, enter a valid action positive prompt, apply it and Preview. Inspect the browser request and confirm it contains:

```json
{
  "role": "action",
  "ref": "web-temporary:action:temporary-action",
  "node": { "kind": "action" }
}
```

- [ ] **Step 5: Run one real NovelAI generation**

Generate one image with `n_samples=1`. Verify:

- the job reaches `succeeded`;
- the generated image is shown or linked by the Web result area;
- `GenerationResult.request_body` uses the prompt from the current Preview;
- the source node files remain unchanged;
- no `/api/nodes/save` request occurs.

- [ ] **Step 6: Verify AgentComposer cache behavior without changing its implementation**

Use AgentComposer mode with a known cached node combination:

1. Preview the unchanged node combination and record cache result/key.
2. Modify one node prompt temporarily and Preview again.
3. Confirm the Agent task/cache key changes or the old cached composition is not reused.
4. Restore the original node and confirm the original content hash is recovered.

- [ ] **Step 7: Run the final regression commands**

Run:

```powershell
uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_compose tests.test_web_results tests.test_web_batch -v
cd web
npm run test
npm run build
```

Expected: backend Web tests PASS, frontend tests PASS, and production build succeeds.

- [ ] **Step 8: Commit documentation and any verification fixes**

```powershell
git add docs/web_control_console_readme.md
git commit -m "docs: explain temporary node workflow"
```

If business verification required a code fix, amend the responsible Task 1-3 commit with only that task's explicitly listed files before making this documentation commit. Do not stage generated images, Web runtime output, local config or unrelated dirty files.
