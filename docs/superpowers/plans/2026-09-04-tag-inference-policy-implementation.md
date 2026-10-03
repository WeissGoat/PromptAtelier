# Tag Inference Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PromptPolicyPipeline 中维护完全配置驱动的 `tag_inference`，由默认模板把裸足标签推导为 `bare_legs`，并把 `pussy` 推导为 `uncensored`。

**Architecture:** 新规则位于 Prompt Policy 层的 `post_compose_cleanup` 阶段，使用 Pydantic 配置模型解析模板和调用方提供的推导规则。规则只修改 positive tokens，通过现有 `PromptRuleContext` 写入 trace；Registry、模板和 GenerationService 链路保持现有边界。

**Tech Stack:** Python 3、Pydantic v2、现有 `PromptPolicyPipeline`、`GenerationService`、unittest、YAML 内置模板。

## Global Constraints

- 不修改旧 `tags_machine` 主链路。
- 不修改 AgentComposer 实现、AgentComposer cache key 或 NovelAI Renderer 协议。
- 不修改 `PromptBundle` 数据结构。
- 规则使用现有 `canonicalize_tag()` 和 `PromptToken`。
- 只处理 positive prompt，不处理 negative prompt。
- Rule 类 `default_enabled` 保持 `false`，由模板显式启用。
- 业务验收优先走 `GenerationService` 完整 compose + policy 链路。

---

### Task 1: Implement Tag Inference Rule

**Files:**
- Create: `src/tags_machine_core/policies/rules/tag_inference.py`
- Modify: `src/tags_machine_core/policies/rules/__init__.py`
- Modify: `src/tags_machine_core/policies/templates/balanced.yaml`

**Interfaces:**
- Produces `TagInferenceSpec`, `TagInferenceOptions`, `TagInferenceRule`。
- `TagInferenceRule` 提供 `id="tag_inference"`、`version="v1"`、`phase="post_compose_cleanup"`、`default_enabled=False`。
- `TagInferenceOptions.rules` 保存当前生效的完整配置规则列表，默认规则由模板提供。

- [x] **Step 1: Define strict configuration models**

实现 `TagInferenceSpec`，字段为 `id`、`when_any`、`add`、`unless_any`、`position`；列表字段统一 canonicalize，空规则抛 `ValueError`，未知字段由 `extra="forbid"` 拒绝。

- [x] **Step 2: Implement exact trigger matching and insertion**

规则只对 `context.positive_tokens` 操作。`when_any` 和 `unless_any` 都精确匹配 canonical key；`after_trigger` 插入第一个触发 token 后，`append` 追加到尾部；目标已存在时保留原 token 和权重。

- [x] **Step 3: Register and configure in balanced template**

在 `DEFAULT_RULES` 中把 `TagInferenceRule()` 放到 `TagConflictRule()` 前面，并在 `balanced.yaml` 显式启用 `tag_inference` 及其默认 `options.rules`。

- [x] **Step 4: Run focused import/config check**

运行：`uv run python -c "from tags_machine_core.policies.rules import DEFAULT_RULES; print([rule.id for rule in DEFAULT_RULES])"`

预期输出包含 `tag_inference`，且位于 `tag_conflict` 之前。

### Task 2: Add Prompt Business Coverage

**Files:**
- Modify: `tests/test_prompt_policy.py`
- Modify: `docs/prompt_policy_configuration.md`

**Interfaces:**
- 测试通过 `GenerationService.compose_full_prompt()` 进入完整 PromptPolicyPipeline。
- 文档提供 `tag_inference` 配置、默认状态和完整规则替换示例。

- [x] **Step 1: Add behavior cases**

覆盖默认模板规则、裸足别名、`pussy` 推导、权重、已有目标标签、无触发词、相似标签误触发、negative prompt 隔离、Policy 关闭和自定义规则替换。

- [x] **Step 2: Add order/template assertions**

确认 `balanced/default` 开启，`normalize_only` 不开启，且 `tag_inference` 排在 `tag_conflict` 前。

- [x] **Step 3: Document usage**

在 Prompt Policy 配置文档中说明 `tag_inference` 的职责、配置格式、精确匹配规则、插入位置和 trace。

### Task 3: Verify Full Render Boundary

**Files:**
- Modify: `tests/test_prompt_policy.py` if an integration assertion is needed.

- [x] **Step 1: Verify GenerationService output**

使用 `GenerationService` 生成带 `barefoot` 或 `pussy` 的完整 Prompt，确认输出分别包含 `barefoot, bare_legs` 或 `pussy, uncensored`，而模型和 Renderer 参数不在该规则中改变。

- [x] **Step 2: Verify AgentComposer bypass**

复用现有 AgentComposer 测试，确认 `tag_inference` 不写入 Agent 结果的 Policy metadata。

- [x] **Step 3: Run regression tests**

运行：`uv run pytest tests/test_prompt_policy.py tests/test_prompt_policy_acceptance.py -q`

预期：全部通过；若 acceptance 文件不存在，只运行存在的测试文件。

- [x] **Step 4: Inspect diff**

运行：`git diff --check`，确认仅包含本功能相关文件的改动。
