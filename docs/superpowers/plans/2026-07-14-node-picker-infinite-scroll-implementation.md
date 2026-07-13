# Node Picker Infinite Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将节点搜索改为每页 20 条的自动续页浮层，并改善长节点名称与后续表单重叠时的视觉层级。

**Architecture:** 后端保留现有 `list_nodes()` 兼容接口，新增分页查询方法，由 HTTP 路由返回 `offset`、`limit` 和 `has_more`。前端 `NodePicker` 使用底部 `IntersectionObserver` 哨兵加载下一页，搜索词变化时重置分页并通过现有请求编号隔离过期响应。

**Tech Stack:** Python、FastAPI、React、TypeScript、IntersectionObserver、Vitest、Testing Library

## Global Constraints

- 每页固定 20 条。
- 下拉菜单保持绝对定位浮层。
- 不建立节点全量缓存。
- 不修改节点读取和保存协议。
- 不影响现有临时节点、Compare 和生图链路。

---

### Task 1: 后端节点分页契约

**Files:**
- Modify: `src/tags_machine_core/web/services/node_workspace.py`
- Modify: `src/tags_machine_core/web/routes/nodes.py`
- Test: `tests/test_web_nodes.py`

**Interfaces:**
- Consumes: `role: str`、`query: str | None`、`offset: int`、`limit: int`。
- Produces: `(nodes: list[dict[str, Any]], has_more: bool)` 和 HTTP 分页字段。

- [ ] **Step 1: 增加失败测试，验证两页结果不重复且 `has_more` 正确**
- [ ] **Step 2: 运行 `uv run python -m pytest tests/test_web_nodes.py -q` 并确认失败**
- [ ] **Step 3: 新增 `NodeWorkspace.list_nodes_page()`，跳过 offset 后读取 limit + 1 条**
- [ ] **Step 4: 扩展 `/api/nodes` 的 offset、limit 和 has_more 响应**
- [ ] **Step 5: 重新运行后端节点测试并确认通过**

### Task 2: 前端增量加载状态

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/components/NodePicker.tsx`
- Test: `web/src/components/NodePicker.test.tsx`

**Interfaces:**
- Consumes: `NodeListResponse.nodes/offset/limit/has_more`。
- Produces: 首屏 20 条、哨兵触发续页、分页错误重试的节点选择器。

- [ ] **Step 1: 更新响应测试助手并增加首屏、续页、搜索重置测试**
- [ ] **Step 2: 运行 `npm --prefix web run test -- --run src/components/NodePicker.test.tsx` 并确认失败**
- [ ] **Step 3: 扩展 `NodeListResponse` 分页字段**
- [ ] **Step 4: 实现第一页加载、按 ref 去重追加、续页错误和请求隔离**
- [ ] **Step 5: 使用列表底部 IntersectionObserver 哨兵触发下一页**
- [ ] **Step 6: 运行 NodePicker 测试并确认通过**

### Task 3: 浮层视觉整理与业务验收

**Files:**
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `.node-picker-results`、结果按钮、加载和重试状态。
- Produces: 高层级、固定高度、单行省略且不推动表单的搜索浮层。

- [ ] **Step 1: 提高聚焦 Node Picker 层级并扩展菜单遮挡范围**
- [ ] **Step 2: 固定结果行尺寸，节点名使用单行省略**
- [ ] **Step 3: 运行完整前后端测试和前端生产构建**
- [ ] **Step 4: 在真实页面搜索 Action，确认首次 20 条，滚动后自动追加下一页且浮层不与表单混杂**
