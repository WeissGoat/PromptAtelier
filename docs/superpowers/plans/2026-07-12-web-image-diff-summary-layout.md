# Image Diff Summary Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将图片参数 Diff 移到元数据面板底部并默认折叠，同时让 Prompt 摘要只显示新增和移除的 tag。

**Architecture:** 后端继续提供两张 PNG 的全量归一化参数 Diff。前端在展示层识别 Prompt 类字段，对逗号分隔的 tag 序列计算最长公共子序列，只在摘要卡中展示新增和移除片段；完整前后值继续保留在“完整参数 Diff”中。

**Tech Stack:** React、TypeScript、Vitest、Testing Library、CSS

## Global Constraints

- Diff 数据必须来自实际 PNG 文件。
- 后端全量参数比较语义保持不变。
- 参数 Diff 整体位于右侧元数据面板末尾并默认折叠。
- Prompt 摘要只显示差异 tag，完整值只出现在完整 Diff 中。

---

### Task 1: Prompt 差异摘要与折叠布局

**Files:**
- Modify: `web/src/components/ImageDetailDialog.tsx`
- Modify: `web/src/components/ImageDetailDialog.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `ImageParameterDiffItem[]`，由 `/api/results/image-parameter-diff` 返回。
- Produces: Prompt 类字段的 `{ removed: string[]; added: string[] }` 摘要，以及默认折叠的底部 Diff 面板。

- [ ] **Step 1: 更新组件测试**

增加包含 Prompt、重复 V4 Prompt 和普通 sampler 差异的响应，断言 Diff 默认折叠、位于完整 PNG 信息之后，展开后只显示新增/移除 tag，不在摘要中显示完整 Prompt。

- [ ] **Step 2: 运行测试确认旧实现不满足要求**

Run: `npm run test -- ImageDetailDialog.test.tsx`

Expected: 新增断言失败，因为当前 Diff 默认展开并显示完整 Prompt。

- [ ] **Step 3: 实现最小变更**

在 `ImageDetailDialog.tsx` 中增加逗号 tag 分词和最长公共子序列差异函数；Prompt 类 Diff 使用片段摘要，重复 Prompt 差异按摘要内容去重。将 Diff `<section>` 移到右侧面板末尾并改为默认关闭的 `<details>`。

- [ ] **Step 4: 调整样式**

为折叠标题、数量徽标、新增/移除 tag 列表增加紧凑样式，删除摘要卡中完整 Prompt 的滚动文本框布局。

- [ ] **Step 5: 验证**

Run: `npm run test`

Expected: 14 个测试文件全部通过。

Run: `npm run build`

Expected: TypeScript 与 Vite 构建成功。

Run: `git diff --check`

Expected: 无空白错误。

- [ ] **Step 6: 浏览器业务验收**

使用现有 Compare 两张真实 PNG 打开第二张详情，确认 Diff 位于最底部且默认折叠；展开后 Prompt 摘要仅显示 `compare_edit_marker`，完整 Diff 仍可查看原始前后值。
