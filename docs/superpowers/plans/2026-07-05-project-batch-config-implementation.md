# Project Batch Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-level batch config composition with ordered `require` files and a small `batch` shorthand for characters/action_groups.

**Architecture:** Keep the feature in the batch config reading layer. `spec_reader.py` resolves required YAML files, applies deterministic merge rules, expands the optional `batch` shorthand into existing `defaults` / `select` / `expand` fields, then returns a normal `BatchSpec`. Planner, Runner, Composer, Renderer, and AgentComposer stay unchanged.

**Tech Stack:** Python, PyYAML, Pydantic v2, existing `tags_machine_core.batch` modules.

---

### Task 1: Config Merge Reader

**Files:**
- Modify: `src/tags_machine_core/batch/spec_reader.py`
- Modify: `src/tags_machine_core/batch/models.py`
- Test: `tests/test_batch_generation.py`

- [ ] Add `require` to `BatchSpec` as `list[str]`.
- [ ] Add ordered YAML loading in `load_batch_spec()`.
- [ ] Resolve relative require paths from the file that declares them.
- [ ] Detect circular require chains and raise `ValueError`.
- [ ] Implement merge rules: scalar replace, dict recursive merge, list replace.
- [ ] Add focused tests for merge behavior and cycle detection.

### Task 2: Batch Shorthand Expansion

**Files:**
- Modify: `src/tags_machine_core/batch/spec_reader.py`
- Test: `tests/test_batch_generation.py`

- [ ] Add `_expand_batch_shorthand()` before `BatchSpec.model_validate()`.
- [ ] Translate `batch.characters` into `select.characters` collection selectors.
- [ ] Translate `batch.action_groups` into named action collection selectors.
- [ ] Translate simple default fields into `defaults`.
- [ ] Translate strategy/max_tasks/mode fields into `expand`.
- [ ] Add tests that `BatchPlanner` can plan from shorthand after loading.

### Task 3: Examples And Docs

**Files:**
- Create: `examples/project/base.yaml`
- Create: `examples/project/collections.yaml`
- Create: `examples/batches/blackboard_style_rounds_require.yaml`
- Modify: `docs/batch_generation_readme.md`
- Reference: `docs/project_batch_config_spec_v1.md`

- [ ] Add project config examples.
- [ ] Add a concise require-based blackboard batch example.
- [ ] Document how to run `plan-batch` with the new example.
- [ ] Keep old explicit batch examples valid.

### Task 4: Verification

**Files:**
- Test: `tests/test_batch_generation.py`

- [ ] Run targeted tests for batch config reader and planner.
- [ ] Run `plan-batch` against the new require-based example.
- [ ] Confirm output task count and selector summary are sensible.

### Self-Review Notes

- The plan is scoped to config loading and batch planning only.
- No Composer or Renderer behavior changes are required.
- No AgentComposer cache behavior changes are allowed.
- Real NovelAI output is not required for this config-layer change; business verification is `plan-batch` task expansion.
