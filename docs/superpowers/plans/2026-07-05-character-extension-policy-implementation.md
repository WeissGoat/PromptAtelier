# Character Extension Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `PromptPolicyPipeline` 中实现 `character_extension` 规则，复刻旧版 `formula.py:extend_character_in_the_end` 的核心角色扩展效果，同时不影响 AgentComposer 和 full prompt 链路。

**Architecture:** 新规则只作为 policy rule 接入，读取 `ResolvedNodeSet` 中的 character/action 节点和 ScriptComposer 写入的 `character_materials`。Renderer 不承载旧 formula 逻辑，AgentComposer 继续绕过 PromptPolicyPipeline。

**Tech Stack:** Python 3、Pydantic、现有 `tags_machine_core.policies`、现有 `NodeDocument.legacy.raw_sections`。

---

### Task 1: Legacy Extension Parser

**Files:**
- Create: `src/tags_machine_core/policies/rules/character_extension.py`
- Test: `tests/test_character_extension_policy.py`

- [ ] **Step 1: Add parser models**

Create dataclasses:

```python
@dataclass(frozen=True)
class ExtensionDeclaration:
    slot: str
    materials: tuple[str, ...]

@dataclass(frozen=True)
class ExtensionOperation:
    name: str
    args: tuple[str, ...]

@dataclass(frozen=True)
class ExtensionRuleLine:
    slot: str
    legacy_triggers: tuple[str, ...]
    operations: tuple[ExtensionOperation, ...]
```

- [ ] **Step 2: Parse legacy raw sections**

Read `node.legacy.raw_sections["extension"]` and split:

```text
ext_legwear,argyle_legwear,pantyhose
weapon, weapon|sword, include_replace|weapon|sword|gun, add_after|gun|weapon, add|gun|shield
```

Declaration lines start with `ext_`; rule lines start with known slot names such as `leg_wear`, `weapon`, `shoes`, `extend_func_pantyhose`。

- [ ] **Step 3: Verify parser behavior**

Run:

```bash
uv run python -m pytest tests/test_character_extension_policy.py -q
```

Expected: parser tests pass.

### Task 2: Rule Execution

**Files:**
- Modify: `src/tags_machine_core/policies/rules/character_extension.py`
- Modify: `src/tags_machine_core/policies/rules/__init__.py`
- Modify: `src/tags_machine_core/policies/config.py`
- Test: `tests/test_character_extension_policy.py`

- [ ] **Step 1: Implement `CharacterExtensionPolicyRule`**

Rule metadata:

```python
id = "character_extension"
version = "v1"
phase = "compose_selection"
default_enabled = False
```

Options:

```yaml
trigger_mode: fixed
include_declaration_materials: true
```

- [ ] **Step 2: Trigger detection**

Build canonical token set from `context.positive_tokens` after normalizing spaces to underscores. A slot triggers when:

- fixed trigger registry matches current prompt tokens。
- `trigger_mode: legacy` uses legacy triggers from the character rule line。
- `trigger_mode: fixed_plus_legacy` uses both。

- [ ] **Step 3: Apply operations**

Support first-version operations:

```text
include_replace|old_a|old_b|target
replace|old_a|old_b|target
fuzzy_replace|old_a|old_b|target
add|trigger|new_a|new_b
add_after|anchor|new_a|new_b
add_if_not_exist|blocked_a|blocked_b|new_value
```

Each mutation writes a trace entry with rule id, action, token/from/to/reason/mode.

- [ ] **Step 4: Register the rule**

Add `CharacterExtensionPolicyRule()` to `DEFAULT_RULES` and add `character_extension` to `legacy_compat` profile only.

- [ ] **Step 5: Verify AgentComposer is not affected**

Run:

```bash
uv run python -m pytest tests/test_agent_composer.py tests/test_character_extension_policy.py -q
```

Expected: AgentComposer tests pass, new policy tests pass.

### Task 3: Business Acceptance Case

**Files:**
- Create: `examples/batches/character_extension_homura_legwear_weapon.yaml`
- Test: real NovelAI generation through existing CLI/batch command

- [ ] **Step 1: Add acceptance batch config**

Config uses:

```yaml
artist: 20260412
character: danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女
action: st_ft_leg/22_20240506_1715007679
prompt_policy:
  enabled: true
  profile: legacy_compat
  rules:
    character_extension:
      enabled: true
      trigger_mode: fixed
      include_declaration_materials: true
```

- [ ] **Step 2: Run one real core image**

Generate one NovelAI image with the acceptance config and save output under:

```text
acceptance_compare/character_extension_homura_legwear_weapon/core/
```

- [ ] **Step 3: Compare with old formula image**

Use the old tags_machine output for the same character/action/style and record:

```text
acceptance_compare/character_extension_homura_legwear_weapon/report.md
```

Pass condition: both images preserve Homura identity, legwear theme, weapon semantics, and close action/camera theme.

