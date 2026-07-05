# Collection Expressions Action Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 batch project config 像旧 `nai_const.py` 一样支持动作组的动态匹配和组合，并验证 `ACTION_SFW`、`ACTION_BODY`、`ACTION_FT`、`ACTION_SEX`、`ACTION_MOUTH`、`ACTION_NEW` 等价。

**Architecture:** 扩展 `collections` 的值类型，让它既能保存旧的路径字符串，也能保存 selector item 和 collection reference item。展开仍发生在 `batch/selectors.py`，下游 `BatchPlanner`、Composer、Renderer 不感知新语法。

**Tech Stack:** Python 3、Pydantic、YAML、unittest、mock batch run。

---

### Task 1: Collection Expression Expansion

**Files:**
- Modify: `src/tags_machine_core/batch/models.py`
- Modify: `src/tags_machine_core/batch/selectors.py`
- Test: `tests/test_batch_generation.py`

- [ ] 扩展 `BatchSpec.collections` 和 `SelectorContext.collections`，允许 `list[Any]`。
- [ ] 在 collection 展开中支持字符串路径、`{"selector": "folder", ...}` 和 `{"collection": "name"}`。
- [ ] 增加循环引用检测，出现 `a -> b -> a` 时抛出明确错误。
- [ ] 让 `include.names` 支持通配符，例如 `pn_*` 和 `st_other*`。

### Task 2: Dynamic NAI Const Config

**Files:**
- Modify: `examples/project/nai_const_action_groups.yaml`
- Modify: `docs/project_batch_config_spec_v1.md`
- Modify: `docs/batch_generation_readme.md`

- [ ] 把 `action_new`、`action_other`、`action_prepare`、`action_dress_topic` 改成 `selector: folder` 动态匹配。
- [ ] 把 `action_body`、`action_sex`、`select_action` 改成 `collection` 组合。
- [ ] 保留基础静态组，避免过度抽象。

### Task 3: Acceptance Verification

**Files:**
- Test command only.

- [ ] 用脚本从旧 `nai_const.py` 计算目标动作组对应的动作节点集合。
- [ ] 用 refactor collection 展开对应组。
- [ ] 比较 `ACTION_SFW`、`ACTION_BODY`、`ACTION_FT`、`ACTION_SEX`、`ACTION_MOUTH`、`ACTION_NEW` 的集合差异。
- [ ] 用 mock batch 跑 `action_sex`，确认新配置能走完整 batch 链路。
