# Web Compare Artist Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Web 临时 Artist 参数丢失与提示词重复，并让 Compare 使用独立目录和 Primary 镜像槽位。

**Architecture:** 在节点读取边界按角色选择 Artist 专用 Repository；Compare 控制器只负责任务矩阵和本轮归档上下文；Workspace 负责深拷贝 Primary。Renderer 不增加路径回查或 Compare 特殊分支。

**Tech Stack:** Python 3.12、FastAPI、React、TypeScript、Vitest、NovelAI。

## Global Constraints

- 不修改旧 `tags_machine/design` 文件。
- 不在 NovelAI Renderer 增加旧路径硬编码。
- Compare 继续串行请求 NovelAI。
- 真实 PNG 参数和输出路径是最终业务验收依据。

---

### Task 1: Artist 节点读取

**Files:**
- Modify: `src/tags_machine_core/web/services/node_workspace.py`
- Modify: `src/tags_machine_core/web/routes/nodes.py`
- Modify: `src/tags_machine_core/web/app.py`
- Modify: `web/src/components/NodeSlot.tsx`
- Test: `tests/test_web_nodes.py`

**Interfaces:**
- Consumes: `NovelAIArtistRepository.load_node(artist_ref)`
- Produces: `NodeWorkspace.read_node(ref, role=None)`

- [ ] 添加失败测试，断言 legacy Artist Web 节点包含 `renderers.novelai.params` 且 Prompt 不重复。
- [ ] 让节点读取请求传递 `role`，Artist 使用专用 Repository。
- [ ] 运行 `uv run python -m unittest tests.test_web_nodes -v`。

### Task 2: Primary 镜像 Compare

**Files:**
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Test: `web/src/workspace/CustomWorkspaceProvider.test.tsx`
- Test: `web/src/components/NodeRoleGroup.test.tsx`

**Interfaces:**
- Consumes: 当前 `RoleNodeGroup.primary`
- Produces: 深拷贝的 `NodeVariantSlot`

- [ ] 添加失败测试，断言 `addCompare(role)` 镜像 Primary 且对象互不共享。
- [ ] 使用 `cloneNode` 构造 Compare 槽位。
- [ ] 运行相关 Vitest。

### Task 3: Compare 独立输出目录

**Files:**
- Modify: `web/src/compare/useCompareRunController.ts`
- Test: `web/src/compare/useCompareRunController.test.tsx`

**Interfaces:**
- Consumes: Compare 本轮 seed 和一次性 run id
- Produces: 所有 `/generate` 请求共享的 `output_dir`

- [ ] 添加失败测试，断言同轮请求目录相同、下一轮目录不同。
- [ ] 在 `start()` 创建 `outputs/compare_<timestamp>_<seed>_<short-id>` 并传给每个 Generate。
- [ ] 运行 Compare 控制器测试。

### Task 4: 综合与真实出图验收

**Files:**
- Modify: `docs/web_control_console_readme.md`

**Interfaces:**
- Consumes: Web Custom Compare 工作流
- Produces: 同目录真实 PNG 与参数核对结果

- [ ] 运行后端 Web 测试、全部前端测试和生产构建。
- [ ] 使用目标 Artist 镜像一个 Compare Artist，临时修改后生成两张图。
- [ ] 读取两张 PNG，确认 Artist 参数保留、提示词不重复、seed 相同且路径同属本轮目录。
