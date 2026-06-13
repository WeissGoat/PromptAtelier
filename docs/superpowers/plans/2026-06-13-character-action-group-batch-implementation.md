# Character Action Group Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `character_action_group` batch 展开模式，让每个角色按策略选择一个动作分类，并跑完该分类下所有动作。

**Architecture:** 只扩展 batch 规划层。`BatchSpec` 增加 `select.action_groups` 和 `expand` 策略字段；新增 `batch/action_groups.py` 负责动作组解析、策略和 record；`BatchPlanner` 根据 `expand.mode` 分流并产出普通 `BatchTask`。Composer、Renderer、Executor 不感知 action group。

**Tech Stack:** Python 3.12、Pydantic、unittest、现有 `tags_machine_core.batch` 包、NovelAI 真实业务验证。

---

## Files

- Modify: `src/tags_machine_core/batch/models.py`
- Create: `src/tags_machine_core/batch/action_groups.py`
- Modify: `src/tags_machine_core/batch/planner.py`
- Modify: `src/tags_machine_core/batch/runner.py`
- Modify: `src/tags_machine_core/batch/report.py`
- Modify: `src/tags_machine_core/batch/__init__.py`
- Modify: `tests/test_batch_generation.py`
- Create: `examples/batches/character_action_group_20260412.yaml`
- Modify: `docs/batch_generation_readme.md`
- Create or update: `docs/batch_generation_business_test_20260613.md`

## Task 1: Models

- [ ] Extend `ExpandMode` with `character_action_group`.
- [ ] Add `ActionGroupStrategyName = Literal["random", "ordered", "balanced_random"]`.
- [ ] Add `BatchSelect.action_groups: list[SelectorSpec]`.
- [ ] Add `ExpandConfig.action_group_strategy`, `action_group_record`, and `seed`.
- [ ] Validate no schema breaking changes for existing specs.

## Task 2: Action Group Module

- [ ] Add `ResolvedActionGroup` with `name`, `actions`, and `source`.
- [ ] Add `ActionGroupRecord` helpers to read/write JSON record files.
- [ ] Add `resolve_action_groups(specs, context)` that reuses `expand_selector(role="action", ...)`.
- [ ] Add strategies:
  - `random`: seeded random choice, allows repeats.
  - `ordered`: role index modulo group count.
  - `balanced_random`: choose least `selected_count`, seeded random among ties, then increment `selected_count`.
- [ ] Fail fast on empty group, duplicate group names, broken record JSON, or invalid strategy.

## Task 3: Planner

- [ ] Add `_validate_expand_select_contract`.
- [ ] Keep `select.actions` behavior unchanged for `product` and `zip`.
- [ ] For `character_action_group`, require `select.action_groups` and reject `select.actions`.
- [ ] Add `_plan_character_action_group`.
- [ ] For each character, select a group, then emit one `BatchTask` per action in that group.
- [ ] Write scheduling metadata to `task.source`.

## Task 4: Logs And Report

- [ ] Add planner info logs for resolved group count and selected group.
- [ ] Add runner info logs with `index/total`, `character`, `action_group`, `action`, `nt`, `resolution`, and image paths.
- [ ] Add retry logs with `attempt/max_attempts`.
- [ ] Add report detail for `source.action_group`, `source.character`, and `source.action`.

## Task 5: Tests

- [ ] Add `ordered` planning test with deterministic task order.
- [ ] Add `random + seed` reproducibility test.
- [ ] Add `balanced_random` record read/write test.
- [ ] Add conflict tests:
  - `character_action_group` + `select.actions` fails.
  - non-`character_action_group` + `select.action_groups` fails.
- [ ] Add report source detail test.
- [ ] Run `uv run --with pytest --with-editable . pytest tests\test_batch_generation.py -q`.

## Task 6: Example And Docs

- [ ] Add `examples/batches/character_action_group_20260412.yaml`.
- [ ] Update `docs/batch_generation_readme.md` with field meanings, YAML sample, strategies, logs, and result structure.
- [ ] Run `uv run python -m tags_machine_core plan-batch examples\batches\character_action_group_20260412.yaml --full`.

## Task 7: Business Validation

- [ ] Run a small real NovelAI case with `--limit 1` or a tiny local fixture if agent cache is missing.
- [ ] Verify output has readable PNG params when real generation succeeds.
- [ ] Record command, result path, report path, and conclusion in `docs/batch_generation_business_test_20260613.md`.
- [ ] Run `git diff --check`.

