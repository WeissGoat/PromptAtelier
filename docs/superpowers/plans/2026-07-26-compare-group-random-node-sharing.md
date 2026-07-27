# Compare Group Random Node Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Compare 同一 NT 组内随机 Action 不一致的问题，同时保持 Primary Generate 的逐任务抽取行为。

**Architecture:** 为通用 `resolveRandomItems()` 输入增加可选 `randomScope`。未设置作用域时沿用现有逐项消费队列；设置后以 `randomScope + slotId` 为共享键，每个键只抽一次并将节点与选择记录复用给同组任务。Compare Controller 传入 Group 作用域，其他调用方不变。

**Tech Stack:** React 18、TypeScript、Vitest。

## Global Constraints

- 不修改 AgentComposer 或后端 compose 链路。
- 不改变 Primary Generate 的随机节点行为。
- 同组共享随机节点与 seed，不同组重新抽取。

---

### Task 1: Scoped Random Resolution

**Files:**
- Modify: `web/src/randomNodes/resolve.ts`
- Test: `web/src/randomNodes/resolve.test.ts`

**Interfaces:**
- Consumes: `SlotSetItem<T> { value, slots, randomScope? }`
- Produces: 同一 `randomScope + slotId` 复用的 `ResolvedRandomItem<T>`。

- [x] **Step 1:** 增加失败测试，验证同一 scope 复用候选、不同 scope 分别抽取、无 scope 保持逐项抽取。
- [x] **Step 2:** 运行目标测试，确认新增用例在旧实现上失败。
- [x] **Step 3:** 实现 scoped 抽取队列和选择记录复用。
- [x] **Step 4:** 重新运行该测试文件并确认通过。

### Task 2: Compare Group Integration

**Files:**
- Modify: `web/src/compare/useCompareRunController.ts`
- Test: `web/src/compare/useCompareRunController.test.tsx`

**Interfaces:**
- Consumes: `CompareRunItem.groupIndex`。
- Produces: `randomScope: group-${groupIndex}`，以及组内一致的 `randomSelections`。

- [x] **Step 1:** 增加 Compare 回归测试，验证 `NT=2` 时每组矩阵任务共享 Action ref，组间使用不同 ref，seed 仍按组一致。
- [x] **Step 2:** 运行目标测试并确认失败。
- [x] **Step 3:** Compare 调用 `resolveRandomItems()` 时传入 Group scope。
- [x] **Step 4:** 运行目标测试、完整前端测试和生产构建。

### Task 3: Business Verification

**Files:**
- Create: `docs/web_compare_random_node_group_business_test_20260726.md`

**Interfaces:**
- Consumes: Web Compare、随机 Action、`NT=2`、至少两个矩阵组合。
- Produces: 组内 Action ref、组间 Action ref、seed 和 PNG `random_nodes` 的验证记录。

- [x] **Step 1:** 启动 Web 服务并执行真实 Compare Generate。
- [x] **Step 2:** 从生成 PNG 读取元数据，确认同组 Action ref 一致、组间重新抽取、同组 seed 一致。
- [x] **Step 3:** 记录图片绝对路径和验证结论。
