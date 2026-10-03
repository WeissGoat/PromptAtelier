# Custom 节点启用与排序 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本计划按当前会话内直接执行，不使用子 agent。

**Goal:** 将 Custom 工作台的 Artist、Character、Action 节点统一为可启用、可关闭、可排序的有序槽位列表，并让普通 Generate 与 Compare Generate 使用同一套选择规则。

**Architecture:** 用 `RoleNodeGroup.slots` 取代节点级 `primary/compares`，槽位使用 `enabled` 表示是否参与运行。Storage 将旧 v1/v2 快照的 `primary + compares` 迁移为列表；Provider 提供列表操作；Matrix 和 Generate Panel 通过统一的 active-slot 选择器取节点。Prompt Behavior 继续使用原有独立结构。

**Tech Stack:** React 18, TypeScript 5.6, Vitest, Testing Library, 原生 HTML5 Drag and Drop, Vite。

## Global Constraints

- 只修改 `refactor/web` 及本实现对应的 Web 测试和文档。
- 不修改旧 `tags_machine`、AgentComposer、Prompt Behavior 数据模型和 NovelAI 请求协议。
- 保留工作区现有未提交变更，不回滚、不重排无关文件。
- 注释使用中文；新增 UI 文案使用中文或现有界面风格。
- 关闭节点保留内容；关闭节点不参与普通 Generate、Compare Matrix、随机解析和数量统计。
- 新工作区每个 Artist、Character、Action 初始化一个空白启用槽位。

## 文件范围

- 修改 `web/src/workspace/types.ts`：节点槽位和节点组类型。
- 修改 `web/src/workspace/storage.ts`：v3 schema、默认状态、旧快照迁移和校验。
- 修改 `web/src/workspace/CustomWorkspaceProvider.tsx`：列表查找、节点增删、启用切换、排序。
- 修改 `web/src/compare/matrix.ts`：统一 active-slot 选择和顺序展开。
- 修改 `web/src/compare/useCompareRunController.ts`：使用新的 active-slot 校验和矩阵输入。
- 修改 `web/src/components/NodeRoleGroup.tsx`、`NodeSlot.tsx`：列表 UI、开关、拖动和上下移。
- 修改 `web/src/components/NodeWorkspaceEditor.tsx`、`RandomNodeEditor.tsx`：删除节点级 Primary/Compare 文案。
- 修改 `web/src/components/CustomGeneratePanel.tsx`、`web/src/pages/CustomStudio.tsx`：普通生成节点选择和字符 section 聚合。
- 修改相关 `*.test.tsx`、`*.test.ts`：迁移、选择、排序、矩阵、组件验收。

---

### Task 1: 更新节点数据模型和工作区快照迁移

**Files:**
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/storage.ts`
- Test: `web/src/workspace/storage.test.ts`

**Interfaces:**
- `NodeVariantSlot` 移除 `mode`，增加 `enabled: boolean`。
- `RoleNodeGroup` 改为 `{ slots: NodeVariantSlot[] }`。
- `createEmptySlot(role)` 创建一个启用的空白槽位。
- `createEmptyWorkspace()` 每个 role 的 group 初始化为一个空白槽位。
- 新 schema 使用 `promptatelier.custom-workspace/v3`。

- [ ] **Step 1: 先更新测试，覆盖新结构和旧快照迁移**

在 `storage.test.ts` 增加以下测试行为：

```ts
const state = createEmptyWorkspace();
expect(state.groups.artist.slots).toHaveLength(1);
expect(state.groups.artist.slots[0].enabled).toBe(true);

const legacy = {
  ...legacyWorkspaceSnapshot,
  schema: "promptatelier.custom-workspace/v2",
};
localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify(legacy));
const loaded = loadWorkspaceSnapshot(localStorage);
expect(loaded.state.schema).toBe(CUSTOM_WORKSPACE_SCHEMA);
expect(loaded.state.groups.artist.slots.map((slot) => slot.slotId)).toEqual([
  "primary-artist",
  "compare-artist-1",
]);
expect(loaded.state.groups.artist.slots.every((slot) => slot.enabled)).toBe(true);
```

同时把当前直接访问 `primary/compares` 的存储测试改成访问 `slots`，保留临时节点、编辑值、随机配置和编辑器恢复覆盖。

- [ ] **Step 2: 运行存储测试，确认新断言失败**

Run: `npm --prefix web test -- --run web/src/workspace/storage.test.ts`

Expected: FAIL，原因是类型、默认结构和迁移逻辑仍然使用旧字段。

- [ ] **Step 3: 实现类型和存储迁移**

在 `types.ts` 中改成：

```ts
export type NodeVariantSlot = {
  slotId: string;
  role: NodeRole;
  enabled: boolean;
  sourceKind?: "fixed" | "random";
  randomSpec?: NodePoolSpec | null;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  sourceEditor?: NodeEditorDocument | null;
  draftEditorValues?: Record<string, unknown> | null;
};

export type RoleNodeGroup = { slots: NodeVariantSlot[] };
```

在 `storage.ts` 中：

1. 将 `CUSTOM_WORKSPACE_SCHEMA` 设置为 v3。
2. `createEmptySlot(role)` 返回启用槽位。
3. `createEmptyGroup(role)` 返回 `{ slots: [createEmptySlot(role)] }`。
4. 校验 v3 的 `group.slots` 和 `slot.enabled`。
5. 迁移 v1/v2 时将旧 `primary` 和 `compares` 拼接为 `slots`，去掉 `mode`，补齐 `enabled: true`。
6. 迁移编辑器中的 `slotId` 时从 `group.slots` 查找。
7. 保存时仅写入 v3 的 `groups`，不写 `primary/compares`。

- [ ] **Step 4: 运行存储测试确认通过**

Run: `npm --prefix web test -- --run web/src/workspace/storage.test.ts`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add web/src/workspace/types.ts web/src/workspace/storage.ts web/src/workspace/storage.test.ts
git commit -m "refactor(web): 统一 Custom 节点槽位模型"
```

### Task 2: 提供统一的 active-slot 选择器和 Provider 列表操作

**Files:**
- Modify: `web/src/compare/matrix.ts`
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Test: `web/src/compare/matrix.test.ts`
- Test: `web/src/workspace/CustomWorkspaceProvider.test.tsx`

**Interfaces:**
- `activeSlots(group: RoleNodeGroup): NodeVariantSlot[]`：按 `group.slots` 顺序返回启用且有效的固定/随机节点。
- `firstActiveSlot(group): NodeVariantSlot | null`：返回 `activeSlots(group)[0] ?? null`。
- Provider 暴露 `addNode(role)`, `removeNode(slotId)`, `toggleNode(slotId, enabled)`, `reorderNodes(role, activeSlotId, overSlotId)`。

- [ ] **Step 1: 写选择、禁用和排序测试**

覆盖这些场景：

```ts
expect(activeSlots({ slots: [enabledA, disabledB, enabledC] })).toEqual([enabledA, enabledC]);
expect(activeSlots({ slots: [emptyEnabled, enabledC] })).toEqual([enabledC]);
expect(buildCompareMatrix(groups, behavior).map((item) => item.artist?.slotId)).toEqual([
  "artist-a", "artist-a", "artist-c", "artist-c",
]);
```

Provider 测试覆盖：新增节点复制第一个槽位、关闭节点、按 slotId 重排、删除任意节点和编辑器在重排后仍定位同一个 slotId。

- [ ] **Step 2: 运行目标测试确认失败**

Run: `npm --prefix web test -- --run web/src/compare/matrix.test.ts web/src/workspace/CustomWorkspaceProvider.test.tsx`

Expected: FAIL，原因是 `RoleNodeGroup` 和 Provider 仍使用旧字段。

- [ ] **Step 3: 实现 active-slot 选择器**

在 `matrix.ts` 中使用统一有效性判断：

```ts
export function activeSlots(group: RoleNodeGroup): NodeVariantSlot[] {
  return group.slots.filter((slot) => {
    if (!slot.enabled) return false;
    if (slot.sourceKind === "random") return Boolean(slot.randomSpec?.source.value.trim());
    return Boolean(slot.draftNode);
  });
}

export function firstActiveSlot(group: RoleNodeGroup): NodeVariantSlot | null {
  return activeSlots(group)[0] ?? null;
}
```

`compareDimensions`、`factor` 和 `buildCompareMatrix` 全部调用 `activeSlots`，保留没有节点时的 `null` 占位行为。

- [ ] **Step 4: 重写 Provider 的节点遍历和操作**

将 `mapSlot`、`findSlotInState`、编辑器定位全部改为遍历 `group.slots`。实现：

```ts
toggleNode: (slotId, enabled) => setState((current) =>
  mapSlot(current, slotId, (slot) => ({ ...slot, enabled }))
),
reorderNodes: (role, activeSlotId, overSlotId) => setState((current) => {
  const slots = [...current.groups[role].slots];
  const from = slots.findIndex((slot) => slot.slotId === activeSlotId);
  const to = slots.findIndex((slot) => slot.slotId === overSlotId);
  if (from < 0 || to < 0 || from === to) return current;
  const [moved] = slots.splice(from, 1);
  slots.splice(to, 0, moved);
  return {
    ...current,
    groups: { ...current.groups, [role]: { slots } },
    revision: current.revision + 1,
  };
}),
```

`addNode` 复制当前列表第一项的节点内容但生成新 `slotId`，新槽位 `enabled: true`；`removeNode` 可删除列表中任意槽位。Prompt Behavior 的 Provider 逻辑保持不变。

- [ ] **Step 5: 更新 Compare Controller 校验**

将 `selectedSlots` 引用替换为 `activeSlots`。生成前校验改为：`activeSlots(character).length === 0 && activeSlots(action).length === 0` 时抛出当前中文错误；只关闭其中一个类型时仍允许使用另一个类型。

- [ ] **Step 6: 运行目标测试确认通过**

Run: `npm --prefix web test -- --run web/src/compare/matrix.test.ts web/src/workspace/CustomWorkspaceProvider.test.tsx`

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add web/src/compare/matrix.ts web/src/compare/useCompareRunController.ts web/src/workspace/CustomWorkspaceProvider.tsx web/src/compare/matrix.test.ts web/src/workspace/CustomWorkspaceProvider.test.tsx
git commit -m "feat(web): 支持节点启用和列表排序"
```

### Task 3: 改造节点列表 UI 和排序交互

**Files:**
- Modify: `web/src/components/NodeRoleGroup.tsx`
- Modify: `web/src/components/NodeSlot.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/components/NodeRoleGroup.test.tsx`
- Test: `web/src/components/NodeSlot.test.tsx`

**Interfaces:**
- `NodeRoleGroup` 根据 `group.slots` 渲染。
- `NodeSlot` 接收 `onToggle(enabled)`, `onDragStart`, `onDragOver`, `onDrop`, `onMoveUp`, `onMoveDown`。
- 节点删除按钮对所有槽位可见，不再依赖 `slot.mode`。

- [ ] **Step 1: 更新组件测试**

测试改成：

- 点击“新增 Artist 节点”后列表数量增加，且不出现 Compare 文案。
- 关闭节点后开关为未选中并显示“已关闭”。
- 拖动 `slot-a` 到 `slot-b` 后调用 `reorderNodes("artist", "slot-a", "slot-b")`。
- 上移/下移按钮调用同一个重排接口。
- 删除任何节点都调用 `removeNode`。

- [ ] **Step 2: 运行组件测试确认失败**

Run: `npm --prefix web test -- --run web/src/components/NodeRoleGroup.test.tsx web/src/components/NodeSlot.test.tsx`

Expected: FAIL，原因是组件仍依赖 `mode` 和 `addCompare/removeCompare`。

- [ ] **Step 3: 实现 NodeRoleGroup 列表和拖动**

`NodeRoleGroup` 维护当前拖动的 `slotId`，渲染：

```tsx
{group.slots.map((slot, index) => (
  <NodeSlot
    key={slot.slotId}
    slot={slot}
    onToggle={(enabled) => workspace.toggleNode(slot.slotId, enabled)}
    onDragStart={() => setDragging(slot.slotId)}
    onDragOver={(event) => event.preventDefault()}
    onDrop={() => {
      if (dragging) workspace.reorderNodes(role, dragging, slot.slotId);
      setDragging(null);
    }}
    onMoveUp={() => moveRelative(index, -1)}
    onMoveDown={() => moveRelative(index, 1)}
    onRemove={() => workspace.removeNode(slot.slotId)}
  />
))}
```

拖动只在当前 `NodeRoleGroup` 内发生。顶部统计启用数量/总数量，并将按钮文案改为“新增节点”。

- [ ] **Step 4: 实现 NodeSlot 控件**

增加 checkbox 或 switch：

```tsx
<label className="node-enabled-toggle">
  <input
    aria-label={`${label} 节点启用`}
    checked={slot.enabled}
    onChange={(event) => onToggle(event.target.checked)}
    type="checkbox"
  />
  <span>{slot.enabled ? "启用" : "已关闭"}</span>
</label>
```

增加拖动手柄和上下移动按钮；保留现有节点搜索、随机节点、编辑、临时编辑、还原和删除功能。节点标题只显示状态和文件名，不显示 Primary/Compare。

- [ ] **Step 5: 增加关闭和拖动样式**

关闭节点使用低强调样式但不隐藏内容；拖动目标显示边框/背景提示；列表卡片保持稳定尺寸，不因开关或状态文案发生布局跳动。

- [ ] **Step 6: 运行组件测试确认通过**

Run: `npm --prefix web test -- --run web/src/components/NodeRoleGroup.test.tsx web/src/components/NodeSlot.test.tsx`

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add web/src/components/NodeRoleGroup.tsx web/src/components/NodeSlot.tsx web/src/styles.css web/src/components/NodeRoleGroup.test.tsx web/src/components/NodeSlot.test.tsx
git commit -m "feat(web): 增加节点开关和拖动排序 UI"
```

### Task 4: 更新普通 Generate、字符 section 聚合和编辑器文案

**Files:**
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.tsx`
- Modify: `web/src/components/RandomNodeEditor.tsx`
- Test: `web/src/pages/CustomStudio.test.tsx`
- Test: `web/src/compare/useCompareRunController.test.tsx`

**Interfaces:**
- 普通 Generate 通过 `firstActiveSlot(groups[role])` 构造 `primary` request。
- Character sections 通过所有 active character slots 聚合。
- 编辑器仅显示 role 和节点名称，不显示 Primary/Compare。

- [ ] **Step 1: 更新测试中的节点组构造**

将测试 fixture 从：

```ts
{ primary: slot, compares: [compare] }
```

改为：

```ts
{ slots: [{ ...slot, enabled: true }, { ...compare, enabled: true }] }
```

增加测试：第一个节点关闭时普通请求使用第二个节点；关闭 Compare 节点不改变普通请求；Character sections 只包含启用且有效节点。

- [ ] **Step 2: 运行目标测试确认失败**

Run: `npm --prefix web test -- --run web/src/pages/CustomStudio.test.tsx web/src/compare/useCompareRunController.test.tsx`

Expected: FAIL，原因是页面和生成面板仍直接访问 `primary/compares`。

- [ ] **Step 3: 更新 CustomGeneratePanel**

把 `primary` memo 改为：

```ts
const primary = useMemo(() => ({
  artist: firstActiveSlot(groups.artist),
  character: firstActiveSlot(groups.character),
  action: firstActiveSlot(groups.action),
}), [groups]);
```

保留 `buildComposeRenderRequest` 的输入类型和 `null` 节点行为；普通随机生成仅依据这三个 active slot 判断；Compare 继续把完整 groups 交给 controller。

- [ ] **Step 4: 更新 CustomStudio 和编辑器文案**

Character sections 改为：

```ts
const characterSections = [...new Set(
  activeSlots(groups.character).flatMap((slot) => nodeSections(slot.draftNode)),
)];
```

`NodeWorkspaceEditor` 和 `RandomNodeEditor` 删除 `slot.mode` 判断，标题显示 `编辑 ${slot.role} 节点` 或 `Random ${slot.role}`。

- [ ] **Step 5: 运行目标测试确认通过**

Run: `npm --prefix web test -- --run web/src/pages/CustomStudio.test.tsx web/src/compare/useCompareRunController.test.tsx`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add web/src/components/CustomGeneratePanel.tsx web/src/pages/CustomStudio.tsx web/src/components/NodeWorkspaceEditor.tsx web/src/components/RandomNodeEditor.tsx web/src/pages/CustomStudio.test.tsx web/src/compare/useCompareRunController.test.tsx
git commit -m "refactor(web): 统一普通生成和 Compare 节点选择"
```

### Task 5: 全量验证和业务验收

**Files:**
- Modify: `web/src/compare/matrix.test.ts`
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Modify: `web/src/components/NodeRoleGroup.test.tsx`
- Modify: `web/src/components/NodeSlot.test.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.test.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Modify: `web/src/workspace/CustomWorkspaceProvider.test.tsx`
- Modify: `web/src/workspace/requestBuilder.test.ts`
- Modify: `web/src/workspace/storage.test.ts`
- Test: all Web tests and build output.

- [ ] **Step 1: 搜索残留节点级旧字段**

Run: `rg -n "groups\\..*primary|groups\\..*compares|slot\\.mode|mode: \"primary\"|mode: \"compare\"|addCompare\\(|removeCompare\\(" web/src`

Expected: 仅保留 Prompt Behavior 的 `primary/compares`、`mode` 和对应 API；节点组、节点槽位、节点 UI 不应再命中旧字段。

- [ ] **Step 2: 运行完整 Web 测试**

Run: `npm --prefix web test -- --run`

Expected: PASS。

- [ ] **Step 3: 运行 TypeScript/Vite 构建**

Run: `npm --prefix web run build`

Expected: `tsc` 和 Vite build 均成功。

- [ ] **Step 4: 进行浏览器业务验收**

启动现有 Web 开发流程，验证：

1. 每个节点类型默认显示一个空白槽位。
2. 选择两个同类型节点，关闭其中一个，确认数量统计只计算一个。
3. 拖动两个启用节点，确认列表顺序和 Compare 结果卡片顺序一致。
4. 普通 Generate 使用第一个启用且有效节点。
5. 刷新后启用状态、顺序、临时节点和编辑状态仍保留。
6. Character/Action 都没有可用节点时，前端显示错误且不提交 `/compose-preview`。
7. Prompt Behavior Compare 仍可以独立添加和生成。

- [ ] **Step 5: 检查改动范围并提交**

Run: `git status --short; git diff --check`

Expected: 只有本功能相关提交留下的改动；不修改已有无关变更。

```bash
git add web docs/superpowers/plans/2026-08-21-custom-node-enable-order-implementation.md
git commit -m "feat(web): 完成 Custom 节点启用排序"
```
