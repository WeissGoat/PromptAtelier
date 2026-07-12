# Web Image Detail Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Web 生成结果增加大图详情、实际 PNG 元数据和资源管理器定位能力。

**Architecture:** 后端在请求时通过安全结果索引解析图片，并直接读取磁盘 PNG 文本块。前端使用一个共享 `ImageDetailDialog`，由普通和 Compare 图片卡传入图片路径。

**Tech Stack:** FastAPI、Python `subprocess`、现有 PNG verification reader、React 19、TypeScript、Vitest。

## Global Constraints

- 元数据必须从实际图片读取，不能使用 GenerationResult 请求参数代替。
- 所有路径必须限制在 ResultIndex roots 内。
- Windows 打开目录时自动选中图片。

---

### Task 1: 后端图片详情接口

**Files:**
- Modify: `src/tags_machine_core/web/services/result_index.py`
- Modify: `src/tags_machine_core/web/routes/results.py`
- Modify: `tests/test_web_results.py`

- [ ] 增加 `ResultIndex.image_metadata(path)`，读取文件 stat、PNG 尺寸和文本参数。
- [ ] 增加 `GET /results/image-metadata`。
- [ ] 增加 `POST /results/open-image-folder`，校验后调用 `explorer.exe /select,`。
- [ ] 覆盖真实 PNG 参数、越界路径和 subprocess 参数测试。

### Task 2: 图片详情弹窗

**Files:**
- Create: `web/src/components/ImageDetailDialog.tsx`
- Create: `web/src/components/ImageDetailDialog.test.tsx`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/styles.css`

- [ ] 请求并展示实际图片元数据。
- [ ] 展示大图、文件信息、常用参数和折叠完整 JSON。
- [ ] 实现关闭交互和打开文件夹反馈。

### Task 3: 生成结果接入

**Files:**
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`

- [ ] 普通和 Compare 缩略图点击均打开共享弹窗。
- [ ] 保留现有 seed 和路径摘要。

### Task 4: 验收

- [ ] 运行后端 Web Results 测试。
- [ ] 运行全部前端测试与构建。
- [ ] 浏览器打开一张真实生成图，确认大图、PNG seed 和打开文件夹按钮。
