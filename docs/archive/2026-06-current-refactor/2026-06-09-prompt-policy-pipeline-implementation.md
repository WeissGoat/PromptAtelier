# Prompt Policy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `docs/superpowers/specs/2026-06-09-prompt-policy-pipeline-design.md` without changing the default AgentComposer behavior.

**Architecture:** Add a `tags_machine_core.policies` package that can transform a draft `PromptBundle` only when explicitly enabled. Wire it through `GenerationService`, JSON API, and CLI as opt-in configuration; leave AgentComposer bypassed by default.

**Tech Stack:** Python, Pydantic v2 models, existing `PromptBundle`, `ResolvedNodeSet`, unittest.

---

## Files

- Create `src/tags_machine_core/policies/config.py`: policy config, profiles, target switches.
- Create `src/tags_machine_core/policies/tokens.py`: prompt token parser, canonicalizer, serializer.
- Create `src/tags_machine_core/policies/context.py`: rule context and trace entry models.
- Create `src/tags_machine_core/policies/rules/*.py`: concrete rules.
- Create `src/tags_machine_core/policies/pipeline.py`: rule registry and execution.
- Modify `src/tags_machine_core/config.py`: add optional `prompt_policy`.
- Modify `src/tags_machine_core/services/generation_service.py`: opt-in policy application for script/full-prompt paths only.
- Modify `src/tags_machine_core/services/json_api.py`: parse `prompt_policy` request object.
- Modify `src/tags_machine_core/cli.py`: expose minimal opt-in policy arguments.
- Add tests under `tests/test_prompt_policy*.py`.

## Tasks

### Task 1: Policy Models And Token Parser

- [x] Create config, context, and token models.
- [x] Parse comma-separated prompt tags while preserving `{}`, `[]`, and `2.0::tag::` wrappers.
- [x] Serialize with `output_style=underscore` and `output_style=preserve`.

### Task 2: Rule Implementations

- [x] Implement `tag_normalize`.
- [x] Implement `dedupe`.
- [x] Implement `tag_conflict` with built-in footwear conflict rules and optional `masks.txt` loading.
- [x] Implement `character_count`.
- [x] Implement `clothing_policy` with advisory/enforce modes.
- [x] Implement `visibility_policy` with advisory/enforce modes.

### Task 3: Pipeline

- [x] Register rules in phase order.
- [x] Honor `enabled`, `apply_to`, `profile`, `enabled_rules`, and `disabled_rules`.
- [x] Write `meta.extra.policy` and `meta.extra.policy_trace`.
- [x] Keep `profile=off` as a no-op that returns the original bundle unchanged.

### Task 4: Service/API/CLI Opt-In

- [x] Add `PromptPolicyConfig` to `AppConfig`.
- [x] Add optional `prompt_policy` parameters to `GenerationService.compose_full_prompt`, `compose_nodes`, and `compose_resolved_nodes`.
- [x] Do not add policy application to `compose_nodes_with_agent` or `compose_resolved_nodes_with_agent`.
- [x] Let JSON API accept `prompt_policy`.
- [x] Add minimal CLI flags for script/full-prompt opt-in.

### Task 5: Verification

- [x] Verify AgentComposer default cache key and output remain unchanged.
- [x] Verify full prompt default remains unchanged.
- [x] Verify enabled policy normalizes spaces/underscores and writes trace.
- [x] Verify tag conflict removes footwear when barefoot is present.
- [x] Verify ScriptComposer can enforce foot-detail visibility/clothing cleanup.
