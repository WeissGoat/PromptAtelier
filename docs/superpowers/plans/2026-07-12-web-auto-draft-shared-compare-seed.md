# Web Auto Draft And Shared Compare Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让节点编辑自动进入运行草稿，并让 Compare 的所有组合共享同一份生图参数和 seed。

**Architecture:** `NodeWorkspaceEditor` 在合法编辑发生时同步更新 editor 与 slot draft，磁盘写入仍由 Save 独立完成。`useCompareRunController` 在 `start()` 边界冻结参数并解析一次共享 seed，再把同一个参数对象传给所有请求构造调用。

**Tech Stack:** React 19、TypeScript、Vitest、现有 FastAPI Web API、NovelAI Renderer。

## Global Constraints

- 不修改后端 NodeDocument、Composer 或 Renderer 语义。
- 不自动写入节点库。
- 旧 Artist `kind: unknown` 必须可临时编辑和生成。
- Compare 每组合保持 `n_samples=1`。

---

### Task 1: 自动同步编辑草稿

**Files:**
- Modify: `web/src/components/NodeWorkspaceEditor.tsx`
- Modify: `web/src/components/NodeWorkspaceEditor.test.tsx`

- [ ] Form 合法编辑时调用 `workspace.setEditorDraft(next)` 与 `workspace.updateDraft(slotId, next)`。
- [ ] JSON 结构合法时同步 slot draft；无效 JSON 不覆盖最后合法节点。
- [ ] 删除 Apply 按钮、Apply handler 和节点 kind 强制匹配。
- [ ] 验证旧 Artist `kind: unknown` 编辑后可直接进入运行草稿。

### Task 2: 临时节点星号标记

**Files:**
- Modify: `web/src/components/NodeSlot.tsx`
- Modify: `web/src/components/NodeSlot.test.tsx`

- [ ] 根据 `nodeSlotStatus()` 在 modified/temporary 名称后追加 ` *`。
- [ ] 保证原始节点名称不变，精确 ref 选择逻辑不变。

### Task 3: Compare 共享参数快照

**Files:**
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`

- [ ] 在 `start()` 中创建不可变参数副本。
- [ ] `seed=-1` 时生成一次随机 uint32 seed；显式 seed 原样使用。
- [ ] 所有组合使用同一参数副本且 `n_samples=1`。
- [ ] 验证四个 compose 请求 seed 完全一致。

### Task 4: 业务验收

**Files:**
- Modify: `docs/web_control_console_readme.md`

- [ ] 运行 `npm run test` 与 `npm run build`。
- [ ] 使用真实 NovelAI 运行至少两个 Compare 组合。
- [ ] 从结果卡或 PNG 参数确认 seed 一致。
