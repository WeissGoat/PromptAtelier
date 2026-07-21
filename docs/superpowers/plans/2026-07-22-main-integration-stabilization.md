# Main Integration Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 `codex/refactor-core-gateway-integration` 当前契约为准修复过时门禁，验证通过后 fast-forward 合入 `main`，最后恢复合并前 stash 为未提交状态。

**Architecture:** 不向实现层恢复 `style_ref`、固定 `character_ref` 或 v1 schema 等旧兼容字段。稳定化只同步测试、响应示例、示例节点与当前 `PromptBundle v2`、`AgentCompositionTask v2`、artist 节点和多后端能力；只有验证证明实现确有错误时才修改业务代码。

**Tech Stack:** Python 3.11、Pydantic v2、unittest、pytest、FastAPI、React、TypeScript、Vitest、Git submodule。

## Global Constraints

- 当前开发分支是实现事实标准，不恢复已删除的 `style_ref` 兼容层。
- AgentComposer 继续使用结构化 nodes 和 v2 task schema。
- ScriptComposer 继续输出 underscore-normalized prompt。
- Artist 节点允许 NovelAI 或 ComfyUI renderer，不强制所有 artist 都包含 NovelAI 配置。
- 合并前必须通过 `verify-core`、Web 测试和 Web 构建。
- 合并前 stash 的内容不得提交；合并完成后必须重新应用并保持未提交。

---

### Task 1: 同步 PromptBundle 与 AgentComposer v2 契约

**Files:**
- Modify: `tests/test_agent_composer.py`
- Modify: `tests/test_cli_prompt.py`
- Modify: `tests/test_cli_nodes.py`
- Modify: `tests/test_json_api.py`
- Modify: `tests/test_verification.py`
- Modify: `examples/responses/json_api_response_shapes.json`
- Modify: `src/tags_machine_core/verification/acceptance.py`

**Interfaces:**
- Consumes: `PromptBundle.schema == tags-machine-core.prompt-bundle/v2`
- Consumes: `AgentCompositionTask.schema == tags-machine-core.agent-composition-task/v2`
- Produces: 与运行时结构一致的测试和 JSON API 响应示例。

- [ ] 将 v1 schema 断言更新为 v2。
- [ ] 将固定 `meta.character_ref/action_ref/style_ref` 断言改为 `meta.nodes` 角色引用。
- [ ] 将 agent 元数据断言改为 `meta.agent.agent_model/task_schema`。
- [ ] 将 ScriptComposer 的空格 token 断言更新为 underscore-normalized token。
- [ ] 更新 backend support 对 ComfyUI 默认执行能力的期望。
- [ ] 运行 JSON API、AgentComposer、CLI、verification 定向测试。

### Task 2: 正式化 artist 节点示例与迁移测试

**Files:**
- Modify: `examples/nodes/artists/comfyui_cunyfunky/node.yaml`
- Move: `examples/nodes/styles/anime_comfy/` -> `examples/nodes/artists/anime_comfy/`
- Modify: `src/tags_machine_core/nodes/validation.py`
- Modify: `tests/test_node_reader.py`
- Modify: `tests/test_novelai_style.py`
- Modify: `tests/test_resolved_nodes.py`
- Modify: CLI/JSON API 测试中的内联 style YAML fixture。

**Interfaces:**
- Consumes: `kind: artist`、`schema: tags-machine.artist/v1`
- Produces: NovelAI 与 ComfyUI artist 都可通过 v1 节点校验。

- [ ] 将旧 style fixture 更新为 artist。
- [ ] 为 ComfyUI artist 使用正确 schema 和结构化 `tags` mapping。
- [ ] 校验器改为要求 artist 至少声明一个 renderer，而不是固定要求 NovelAI。
- [ ] 将 `long_sleeves` 迁移期望更新到当前 `hands` section。
- [ ] 更新示例路径和 node tree issue count 断言。
- [ ] 运行 NodeReader、NovelAI artist、resolved nodes 定向测试。

### Task 3: 更新 acceptance 与 backend 边界断言

**Files:**
- Modify: `tests/test_verification.py`
- Modify: `examples/acceptance/**`
- Modify: `examples/responses/json_api_response_shapes.json`

**Interfaces:**
- Consumes: 当前 backend support report、PromptBundle v2 和 artist payload。
- Produces: 能识别公共 prompt 数据与 backend-specific artist payload 的验收记录。

- [ ] 更新禁止 backend 字段路径期望。
- [ ] 更新 acceptance prompt/token normalization 期望。
- [ ] 运行 `verify-acceptance-suite examples/acceptance/suite.yaml --require-minimum-set`。

### Task 4: 完整门禁和本地合并

**Files:**
- Verify only: Python、Web、Batch 示例和 Git 状态。

**Interfaces:**
- Consumes: 稳定化后的开发分支 HEAD。
- Produces: fast-forward 后的本地 `main` 和重新应用的未提交 stash。

- [ ] 运行 `uv run python -m tags_machine_core verify-core`。
- [ ] 运行 `uv run --with pytest --with-editable . pytest tests -q`。
- [ ] 运行 `npm ci`、`npm test`、`npm run build`。
- [ ] 使用 mock client 展开并执行 `blackboard_action_new.yaml` 的最小业务 case。
- [ ] 提交稳定化变更。
- [ ] `git switch main` 并 `git merge --ff-only codex/refactor-core-gateway-integration`。
- [ ] 在 `main` 上重新运行核心门禁。
- [ ] 重新应用 `pre-main-merge-20260722` stash，确认内容保持未提交。
