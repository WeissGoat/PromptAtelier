# Blackboard Rounds Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加 blackboard 式目标数量任务编排：角色轮询、动作组按策略选择、选中动作组后完整跑完组内 action。

**Architecture:** 在 batch planner 层新增 `blackboard_rounds` 展开模式，继续产出普通 `BatchTask`，Composer、Renderer、Executor 不需要知道新模式。selector 统一改为 natural sort，保证旧动作目录按人类数字顺序展开。

**Tech Stack:** Python 3.12、Pydantic、unittest、现有 `tags_machine_core.batch` 包。

---

## Files

- Modify: `src/tags_machine_core/batch/models.py`
- Modify: `src/tags_machine_core/batch/selectors.py`
- Modify: `src/tags_machine_core/batch/planner.py`
- Modify: `tests/test_batch_generation.py`
- Create: `examples/batches/blackboard_style_rounds_400.yaml`
- Create: `docs/batch_blackboard_style_rounds_400_plan.md`

## Tasks

- [ ] 在 `ExpandMode` 增加 `blackboard_rounds`。
- [ ] selector 排序改为 natural sort，让 `1_xxx` 排在 `10_xxx` 前面。
- [ ] planner 校验 `blackboard_rounds` 必须有 `select.characters`、`select.action_groups`、`expand.max_tasks`。
- [ ] 实现 `blackboard_rounds`：
  - 第 N 轮角色为 `characters[N % len(characters)]`。
  - 每轮动作组由 `action_group_strategy` 选择。
  - 选中动作组后，按 natural sort 顺序完整展开该组所有 action。
  - `expand.max_tasks` 是目标数量，不硬截断已选中的动作组。
  - 写入 `source.round_index`、`source.action_group`、`source.action_index_in_group`、`source.action_count_in_group`。
- [ ] 添加测试覆盖 natural sort、角色轮询、动作组 ordered 策略、400 条计划命令。
- [ ] 用 1 个 artist、3 个 character、4 个 action_group 重生成 400 条任务编排文档。
