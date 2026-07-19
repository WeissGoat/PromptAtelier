# Character Section Filter Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增默认屏蔽 character `copyright` section 的来源感知 Prompt Policy。

**Architecture:** 新规则通过 resolved character nodes 和 character materials 统计被屏蔽 section 的 token 次数，在 dedupe 前删除角色贡献并同步 bundle 元数据。默认模板启用规则，AgentComposer 不接入。

**Tech Stack:** Python、Pydantic、现有 PromptPolicyPipeline、pytest、Batch Mock Client。

## Global Constraints

- 仅修改 `refactor`。
- 默认屏蔽 `copyright`，但允许配置替换或关闭。
- 不修改 ScriptComposer selected_keys 优先级。
- 不影响 AgentComposer。
- 业务 Mock Batch 验收优先于扩大单元测试范围。

---

### Task 1: 实现规则与默认配置

**Files:**
- Create: `src/tags_machine_core/policies/rules/character_section_filter.py`
- Modify: `src/tags_machine_core/policies/rules/__init__.py`
- Modify: `src/tags_machine_core/policies/templates/balanced.yaml`

- [ ] 增加 `CharacterSectionFilterOptions(blocked_sections=["copyright"])`。
- [ ] 按 character material 的 used sections 统计并删除 token。
- [ ] 同步 composition、character materials 和 policy trace。
- [ ] 将规则加入 compose_selection 默认顺序并在 balanced 模板启用。

### Task 2: 定向验证

**Files:**
- Create: `tests/test_character_section_filter_policy.py`

- [ ] 验证默认删除 character copyright。
- [ ] 验证 action 同名 token 被保留。
- [ ] 验证 material 和 composition 元数据同步。
- [ ] 验证规则关闭后不处理。

Run: `uv run --with pytest --with-editable . pytest tests/test_character_section_filter_policy.py -q`

### Task 3: Batch 业务验收

- [ ] 用 `blackboard_action_new.yaml --fresh --mock-client --limit 1` 运行完整链路。
- [ ] 检查 prompt_bundle、render_request 和 generation_result。
- [ ] 确认 copyright 不在 base prompt 和 character captions。
- [ ] 运行 Prompt Policy 相关定向回归。

