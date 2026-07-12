# Web Image Navigation And Parameter Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为图片详情增加有边界的左右导航，并显示当前 PNG 相对上一张 PNG 的归一化参数差异。

**Architecture:** CustomGeneratePanel 负责建立普通或 Compare 图片序列；ImageDetailDialog 负责当前索引和交互；ResultIndex 与 results route 负责安全读取两张实际 PNG 并调用现有 verification diff 工具。

**Tech Stack:** FastAPI、Python、React、TypeScript、Vitest、PNG metadata utilities。

## Global Constraints

- 导航到首尾时停住，不循环。
- Diff 只使用实际 PNG 元数据。
- 不把 reference image 原始 base64 返回前端。
- 普通 Generate 和 Compare 共用同一个详情组件。

---

### Task 1: PNG 参数 Diff API

**Files:**
- Modify: `src/tags_machine_core/web/services/result_index.py`
- Modify: `src/tags_machine_core/web/routes/results.py`
- Modify: `tests/test_web_results.py`

**Interfaces:**
- Produces: `ResultIndex.image_parameter_diff(previous_path, current_path)`
- Produces: `GET /api/results/image-parameter-diff`

- [ ] 添加实际 PNG Diff、路径越界和 reference image 摘要测试。
- [ ] 复用 `compare_render_parameters` 和 `normalize_render_parameters` 实现服务。
- [ ] 运行 `uv run python -m unittest tests.test_web_results -v`。

### Task 2: 图片序列与导航

**Files:**
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/components/ImageDetailDialog.tsx`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/pages/CustomStudio.test.tsx`

**Interfaces:**
- Consumes: `paths: string[]`, `initialIndex: number`
- Produces: 当前 path、上一张 path 和边界导航状态

- [ ] 将普通 Job 和 Compare 结果分别展平为有序图片序列。
- [ ] 增加按钮、位置计数和方向键导航。
- [ ] 验证首尾按钮禁用且不循环。

### Task 3: Diff 面板视觉

**Files:**
- Modify: `web/src/components/ImageDetailDialog.tsx`
- Modify: `web/src/components/ImageDetailDialog.test.tsx`
- Modify: `web/src/styles.css`
- Modify: `docs/web_control_console_readme.md`

**Interfaces:**
- Consumes: `ImageParameterDiffResponse`
- Produces: 分组 Diff 卡片与折叠原始数据

- [ ] 渲染一致、第一张、加载、错误和有差异状态。
- [ ] 为短值、长 Prompt、移动端和独立滚动补充样式。
- [ ] 运行前端全量测试和生产构建。

### Task 4: 浏览器业务验收

- [ ] 打开同一 Compare 目录中的两张真实 PNG。
- [ ] 验证左右按钮、键盘方向键、边界停住和位置计数。
- [ ] 验证第二张显示相对第一张的实际 PNG 参数 Diff。
