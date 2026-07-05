# NAI Const Action Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把旧 `nai_const.py` 里常用 action group 和标准分辨率以 refactor 项目配置形式复刻出来。

**Architecture:** action group 作为 `collections.actions` 配置片段提供，batch 通过 `require` 引入后继续走现有 collection selector、BatchPlanner、BatchRunner。resolution 只补旧名 alias，仍由 `BatchPlanner._resolve_dimensions()` 统一解析。

**Tech Stack:** Python 3、Pydantic batch models、YAML project config、unittest。

---

### Task 1: Project Action Group Config

**Files:**
- Create: `examples/project/nai_const_action_groups.yaml`
- Modify: `examples/batches/blackboard_style_rounds_require.yaml`
- Modify: `docs/project_batch_config_spec_v1.md`
- Modify: `docs/batch_generation_readme.md`

- [ ] **Step 1: 新增配置片段**

创建 `examples/project/nai_const_action_groups.yaml`，把旧 `nai_const` 中的常用动作组写入 `collections.actions`。列表值使用旧 design 的真实目录路径，例如：

```yaml
collections:
  actions:
    action_ft:
      - F:/my_project/new/tags_machine/design/动作改2/st_ft_bare
      - F:/my_project/new/tags_machine/design/动作改2/st_ft_cs
    action_new:
      - F:/my_project/new/tags_machine/design/动作改2/pn_act_gangbang
```

- [ ] **Step 2: 接入示例 batch**

在 `examples/batches/blackboard_style_rounds_require.yaml` 的 `require` 中增加：

```yaml
  - ../project/nai_const_action_groups.yaml
```

- [ ] **Step 3: 更新文档**

在项目配置文档和 batch README 中说明 `nai_const_action_groups.yaml` 提供的 action collections，以及 `special_next_select` 这类角色目录可以通过 `collections.characters` 的 folder selector 间接加载。

### Task 2: Resolution Aliases

**Files:**
- Modify: `src/tags_machine_core/batch/planner.py`
- Modify: `tests/test_batch_generation.py`
- Modify: `docs/project_batch_config_spec_v1.md`
- Modify: `docs/batch_generation_readme.md`

- [ ] **Step 1: 增加旧名 alias**

在 `STANDARD_RESOLUTIONS` 中加入：

```python
"normal_square": (1024, 1024)
"normal_landscape": (1216, 832)
"normal_portrait": (832, 1216)
```

保留已有 `square`、`landscape`、`portrait`。

- [ ] **Step 2: 增加覆盖测试**

在 `tests/test_batch_generation.py` 增加一个 batch planning 测试，设置 `defaults.resolution: normal_landscape`，断言生成任务的 `render.width == 1216` 且 `render.height == 832`。

### Task 3: Verification

**Files:**
- Test command only.

- [ ] **Step 1: 运行窄范围测试**

```powershell
uv run python -m unittest tests.test_batch_generation.BatchGenerationTest.test_batch_resolution_accepts_nai_const_alias tests.test_batch_generation.BatchGenerationTest.test_batch_shorthand_plans_blackboard_rounds_from_collections
```

- [ ] **Step 2: 运行真实配置预览**

```powershell
uv run python -m tags_machine_core plan-batch examples\batches\blackboard_style_rounds_require.yaml --full
```

预期能展开任务并打印 `task_count`，证明新 require 不影响现有批量编排。
