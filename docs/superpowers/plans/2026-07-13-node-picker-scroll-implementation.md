# Node Picker Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让节点搜索下拉框保持约 6 条结果的可视高度，并通过滚轮浏览最多 100 条匹配节点。

**Architecture:** 保留现有 `NodePicker` 的服务端模糊搜索、防抖和关闭逻辑，仅扩大单次查询结果数量并移除前端六条裁剪。结果容器通过固定最大高度和 `overflow-y: auto` 提供原生滚动，不引入分页状态或新的依赖。

**Tech Stack:** React 18、TypeScript、CSS、Vitest、Testing Library

## Global Constraints

- 搜索结果可视高度保持约 6 条。
- 单次最多加载 100 条匹配节点。
- 保持现有 300ms 防抖、选中、清除和关闭行为。
- 不修改节点 API 协议，不引入分页或无限加载。

---

### Task 1: 扩大节点候选集并增加滚动容器

**Files:**
- Modify: `web/src/components/NodePicker.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/components/NodePicker.test.tsx`

**Interfaces:**
- Consumes: `GET /nodes?role=<role>&limit=<number>&q=<query>` 返回的 `NodeListResponse.nodes`。
- Produces: 最多包含 100 个 `role="option"` 的可滚动 `role="listbox"`。

- [ ] **Step 1: 修改组件测试，要求加载 100 条且保留第 6 条以后结果**

```tsx
it("loads up to one hundred results so the list can scroll", async () => {
  vi.useFakeTimers();
  const nodes = Array.from({ length: 8 }, (_, index) => ({
    role: "action",
    name: `node-${index}`,
    ref: `F:/path/${index}`,
  }));
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(nodes));
  renderPicker();
  fireEvent.focus(screen.getByRole("combobox", { name: "Action" }));
  await runSearchDebounce();
  expect(screen.getAllByRole("option")).toHaveLength(8);
  expect(String(fetchMock.mock.calls[0][0])).toContain("limit=100");
});
```

- [ ] **Step 2: 运行组件测试并确认旧实现失败**

Run: `npm run test -- --run web/src/components/NodePicker.test.tsx`

Expected: FAIL，因为旧实现请求 `limit=6` 并裁剪为 6 条。

- [ ] **Step 3: 修改节点查询上限并移除前端裁剪**

```tsx
const search = new URLSearchParams({ role, limit: "100" });
// ...
setNodes(result.nodes);
```

- [ ] **Step 4: 为结果容器增加固定最大高度和纵向滚动**

```css
.node-picker-results {
  max-height: 240px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
```

- [ ] **Step 5: 运行组件测试和前端完整测试**

Run: `npm run test -- --run web/src/components/NodePicker.test.tsx`

Expected: NodePicker 测试全部 PASS。

Run: `npm run test`

Expected: 前端测试全部 PASS。

- [ ] **Step 6: 构建并进行浏览器业务验收**

Run: `npm run build`

Expected: TypeScript 和 Vite 构建成功。

浏览器验收：聚焦 Character 或 Action 搜索框，确认下拉框高度不超过约 6 条，可滚动到第 7 条以后并成功选中。
