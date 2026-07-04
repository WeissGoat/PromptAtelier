# Action Selected Keys Character Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ScriptComposer 优先使用 action 侧声明的 `selected_keys` 精确选择 character `meta.yaml` 里的 tags 分组，并让 `character_scope` 退为兼容 fallback。

**Architecture:** 新增 action profile 读取层，把 `action_profile.yaml` 或 `run-prompt-prompt.md` YAML front matter 解析成 action 节点的结构化 composition metadata。ScriptComposer 拼接 character 时先查 action profile 的 `selected_keys`，没有时再使用旧 `character_scope` policy，最终输出仍然是标准 `PromptBundle`。

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, 当前 `tags_machine_core` NodeReader / ScriptComposer / PromptBundle 架构。

---

## 设计边界

这次只接 ScriptComposer，不改 AgentComposer 链路。

`selected_keys` 是新的主选择规则，表示“本次 action 需要从某个 character 节点取哪些 tags section”。`character_scope` 不再继续扩展新规则，只作为旧 action 元数据和未声明 `selected_keys` 时的 fallback。

优先级固定为：

```text
action_profile.character_selection.characters[index].selected_keys
> action_profile.character_selection.default_selected_keys
> action.character_scope 对应的旧 CHARACTER_SCOPE_POLICY
> default: character 所有 tags section
```

`classify.yaml` 不直接参与 character tags 过滤。它继续作为动作事实分类，例如 `cast/domain/pose/clothing/environment`，以后可以给 batch 筛选、日志、agent 材料使用。

## 文件结构

- Create: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/action_profile.py`
  - 定义 action profile 数据结构。
  - 解析 `action_profile.yaml`。
  - 解析 `run-prompt-prompt.md` YAML front matter。
  - 提供 `load_action_profile(node_dir)`。

- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/models.py`
  - 给 `NodeDocument` 增加通用 `composition: dict[str, Any]` 字段。
  - 不把该字段塞进 `agent`，避免误导 AgentComposer。

- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/reader.py`
  - 读取目录节点后，如果目录里存在 action profile，就写入 `NodeDocument.composition["character_selection"]`。
  - YAML 节点和 tags.txt fallback 都支持。

- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/character_scope.py`
  - 新增按 `selected_keys` 选择 character sections 的函数。
  - 保留旧 `character_positive(node, character_scope)` 行为，降低影响面。

- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/composers/script.py`
  - `compose_resolved_nodes` 多角色拼接时，按 character index 取 action profile 的 selected keys。
  - `compose_nodes` 单角色拼接也走同一规则。
  - `PromptBundle.meta.composition` 继续记录 included/suppressed sections。
  - `PromptBundle.meta.extra["character_selection"]` 记录本次使用的 profile 来源和每个角色实际 selected keys。

- Test: `F:/my_project/new/tags_machine/refactor/tests/test_action_profile.py`
  - 覆盖 profile 文件和 markdown front matter 解析。

- Test: `F:/my_project/new/tags_machine/refactor/tests/test_script_composer.py`
  - 覆盖 selected keys 优先级、多角色逐 index 选择、fallback 到 character_scope。

- Docs: `F:/my_project/new/tags_machine/refactor/docs/action_yaml_spec_v1.md`
  - 标注 `character_scope` 为兼容字段。
  - 增加 `action_profile.yaml` 规范。

- Docs: `F:/my_project/new/tags_machine/refactor/docs/refactor_architecture_v2.md`
  - 更新 ScriptComposer 数据流。

---

### Task 1: Action Profile 数据结构与解析器

**Files:**
- Create: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/action_profile.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_action_profile.py`

- [ ] **Step 1: 新增解析测试**

在 `tests/test_action_profile.py` 写入：

```python
from pathlib import Path

from tags_machine_core.nodes.action_profile import load_action_profile


def test_load_action_profile_yaml_selected_keys(tmp_path: Path):
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    (action_dir / "action_profile.yaml").write_text(
        """
schema: tags-machine.action-profile/v1
character_selection:
  source: action_profile.yaml
  default_selected_keys:
    - character
    - copyright
  characters:
    - selected_keys:
        - character
        - hair
    - selected_keys:
        - character
        - feet
""".strip(),
        encoding="utf-8",
    )

    profile = load_action_profile(action_dir)

    assert profile is not None
    assert profile.character_selection.source == "action_profile.yaml"
    assert profile.character_selection.default_selected_keys == ["character", "copyright"]
    assert profile.character_selection.characters[0].selected_keys == ["character", "hair"]
    assert profile.character_selection.characters[1].selected_keys == ["character", "feet"]


def test_load_action_profile_from_run_prompt_prompt_front_matter(tmp_path: Path):
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    (action_dir / "run-prompt-prompt.md").write_text(
        """
---
schema_version: 1
characters:
  - selected_keys:
      - character
      - copyright
      - hair
  - selected_keys:
      - character
      - copyright
      - feet
---

正文不参与解析。
""".strip(),
        encoding="utf-8",
    )

    profile = load_action_profile(action_dir)

    assert profile is not None
    assert profile.character_selection.source == "run-prompt-prompt.md"
    assert profile.character_selection.characters[0].selected_keys == [
        "character",
        "copyright",
        "hair",
    ]
    assert profile.character_selection.characters[1].selected_keys == [
        "character",
        "copyright",
        "feet",
    ]


def test_load_action_profile_returns_none_when_missing(tmp_path: Path):
    assert load_action_profile(tmp_path) is None
```

- [ ] **Step 2: 运行测试确认缺模块**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_action_profile.py -q
```

Expected: FAIL，报 `ModuleNotFoundError: No module named 'tags_machine_core.nodes.action_profile'`。

- [ ] **Step 3: 实现 `action_profile.py`**

创建 `src/tags_machine_core/nodes/action_profile.py`：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class CharacterSelectionEntry(BaseModel):
    selected_keys: list[str] = Field(default_factory=list)

    @field_validator("selected_keys", mode="before")
    @classmethod
    def normalize_selected_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


class CharacterSelectionProfile(BaseModel):
    source: str | None = None
    default_selected_keys: list[str] = Field(default_factory=list)
    characters: list[CharacterSelectionEntry] = Field(default_factory=list)

    @field_validator("default_selected_keys", mode="before")
    @classmethod
    def normalize_default_selected_keys(cls, value: Any) -> list[str]:
        return CharacterSelectionEntry.normalize_selected_keys(value)


class ActionProfile(BaseModel):
    schema_id: str = "tags-machine.action-profile/v1"
    character_selection: CharacterSelectionProfile = Field(
        default_factory=CharacterSelectionProfile
    )
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_node_composition(self) -> dict[str, Any]:
        return {
            "character_selection": self.character_selection.model_dump(
                mode="json",
                exclude_none=True,
            )
        }


def load_action_profile(node_dir: str | Path) -> ActionProfile | None:
    node_dir = Path(node_dir)
    profile_yaml = node_dir / "action_profile.yaml"
    if profile_yaml.exists():
        data = _read_yaml_mapping(profile_yaml)
        selection_data = data.get("character_selection") or {}
        if isinstance(selection_data, dict):
            selection_data = {**selection_data, "source": selection_data.get("source") or profile_yaml.name}
        return ActionProfile(
            schema_id=str(data.get("schema") or data.get("schema_id") or "tags-machine.action-profile/v1"),
            character_selection=CharacterSelectionProfile.model_validate(selection_data),
            raw=data,
        )

    prompt_md = node_dir / "run-prompt-prompt.md"
    if prompt_md.exists():
        data = _read_markdown_front_matter(prompt_md)
        if data is None:
            return None
        characters = data.get("characters") or []
        return ActionProfile(
            character_selection=CharacterSelectionProfile(
                source=prompt_md.name,
                characters=[
                    CharacterSelectionEntry.model_validate(item)
                    for item in characters
                    if isinstance(item, dict)
                ],
            ),
            raw=data,
        )

    return None


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return data


def _read_markdown_front_matter(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None
    yaml_text = "\n".join(lines[1:end_index])
    data = yaml.safe_load(yaml_text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML front matter mapping: {path}")
    return data
```

- [ ] **Step 4: 运行解析测试**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_action_profile.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交解析器**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add src/tags_machine_core/nodes/action_profile.py tests/test_action_profile.py
git commit -m "feat: add action character selection profile parser"
```

---

### Task 2: NodeReader 注入 action profile

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/models.py`
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/reader.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_node_reader.py`

- [ ] **Step 1: 写 NodeReader 行为测试**

在 `tests/test_node_reader.py` 增加：

```python
def test_reader_attaches_action_profile_from_run_prompt_prompt(tmp_path):
    action_dir = tmp_path / "foot_action"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("foot focus, soles\n", encoding="utf-8")
    (action_dir / "run-prompt-prompt.md").write_text(
        """
---
characters:
  - selected_keys:
      - character
      - copyright
      - feet
---
""".strip(),
        encoding="utf-8",
    )

    node = NodeReader().read(action_dir)

    assert node.composition["character_selection"]["source"] == "run-prompt-prompt.md"
    assert node.composition["character_selection"]["characters"][0]["selected_keys"] == [
        "character",
        "copyright",
        "feet",
    ]
```

- [ ] **Step 2: 运行测试确认缺字段**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_node_reader.py::test_reader_attaches_action_profile_from_run_prompt_prompt -q
```

Expected: FAIL，报 `NodeDocument` 没有 `composition` 或没有注入 profile。

- [ ] **Step 3: 给 NodeDocument 增加 composition 字段**

在 `src/tags_machine_core/nodes/models.py` 的 `NodeDocument` 中增加：

```python
    composition: dict[str, Any] = Field(default_factory=dict)
```

放在 `renderers` 和 `agent` 附近，表示这是节点级拼接元数据，不属于 backend，也不属于 AgentComposer。

- [ ] **Step 4: 修改 NodeReader 注入 profile**

在 `src/tags_machine_core/nodes/reader.py`：

1. 增加 import：

```python
from .action_profile import load_action_profile
```

2. `_read_yaml` 返回前改为：

```python
        node = NodeDocument.model_validate(data)
        return self._attach_action_profile(node, node_dir)
```

3. `_read_tags_txt` 末尾改为先赋值再返回：

```python
        node = NodeDocument(
            kind="unknown",
            id=node_dir.name,
            name=node_dir.name,
            path=node_dir,
            tags={"legacy": prompt_lines},
            prompt={"positive": prompt_lines},
            legacy=LegacyNodeMeta(
                source_file=str(path),
                raw_lines=lines,
                raw_sections=raw_sections,
            ),
        )
        return self._attach_action_profile(node, node_dir)
```

4. 增加方法：

```python
    def _attach_action_profile(self, node: NodeDocument, node_dir: Path) -> NodeDocument:
        profile = load_action_profile(node_dir)
        if profile is None:
            return node
        composition = dict(node.composition)
        composition.update(profile.to_node_composition())
        return node.model_copy(update={"composition": composition})
```

- [ ] **Step 5: 运行 NodeReader 测试**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_node_reader.py::test_reader_attaches_action_profile_from_run_prompt_prompt -q
```

Expected: PASS。

- [ ] **Step 6: 用真实动作目录做一次解析检查**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run python - <<'PY'
from pathlib import Path
from tags_machine_core.nodes.reader import NodeReader

path = Path(r"F:/my_project/new/tags_machine/design/动作改2/new/20260506_3P后入趴卧")
node = NodeReader().read(path)
print(node.id)
print(node.composition.get("character_selection"))
PY
```

Expected: 输出 action id，并能看到 `source: run-prompt-prompt.md` 和 3 个 `selected_keys` 角色条目。

- [ ] **Step 7: 提交 NodeReader 注入**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add src/tags_machine_core/nodes/models.py src/tags_machine_core/nodes/reader.py tests/test_node_reader.py
git commit -m "feat: attach action character selection metadata"
```

---

### Task 3: Character section selection 统一入口

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/character_scope.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_script_composer.py`

- [ ] **Step 1: 写 selected_keys 选择测试**

在 `tests/test_script_composer.py` 增加：

```python
def test_selected_keys_override_character_scope_for_character_sections():
    character = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "copyright": ["puella magi madoka magica"],
            "hair": ["black hair"],
            "eyes": ["purple eyes"],
            "feet": ["black shoes"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="foot_action",
        character_scope="foot_detail",
        tags={"action": ["foot focus"]},
        composition={
            "character_selection": {
                "source": "run-prompt-prompt.md",
                "characters": [
                    {"selected_keys": ["character", "copyright", "hair"]}
                ],
            }
        },
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "puella magi madoka magica" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "purple eyes" not in bundle.prompt.positive
    assert "black shoes" not in bundle.prompt.positive
    assert "foot focus" in bundle.prompt.positive
    assert bundle.meta.composition.included_character_sections == [
        "character",
        "copyright",
        "hair",
    ]
```

- [ ] **Step 2: 实现 selected_keys 选择函数**

在 `src/tags_machine_core/nodes/character_scope.py` 增加：

```python
def character_positive_with_selected_keys(
    node: NodeDocument | None,
    character_scope: str | None,
    selected_keys: list[str] | None,
) -> tuple[list[str], list[str], list[str]]:
    if node is None:
        return [], [], []
    normalized_keys = [str(key).strip() for key in selected_keys or [] if str(key).strip()]
    if not normalized_keys:
        return character_positive(node, character_scope)
    if node.prompt.positive:
        return _character_prompt_fragments_by_selected_keys(node, normalized_keys)
    sections = list(node.tags.keys())
    include_set = set(normalized_keys)
    included_sections = [section for section in sections if section in include_set]
    suppressed_sections = [section for section in sections if section not in include_set]
    texts: list[str] = []
    for section in included_sections:
        texts.extend(node.tags.get(section, []))
    return texts, included_sections, suppressed_sections


def _character_prompt_fragments_by_selected_keys(
    node: NodeDocument,
    selected_keys: list[str],
) -> tuple[list[str], list[str], list[str]]:
    include_set = set(selected_keys)
    texts: list[str] = []
    included_roles: list[str] = []
    suppressed_roles: list[str] = []
    for fragment in node.prompt.positive:
        role = fragment.role or "prompt"
        if role in include_set:
            texts.append(fragment.text)
            included_roles.append(role)
        else:
            suppressed_roles.append(role)
    return texts, dedupe(included_roles), dedupe(suppressed_roles)
```

- [ ] **Step 3: 暂不接 Composer，先确保 import 层无语法错误**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run python - <<'PY'
from tags_machine_core.nodes.character_scope import character_positive_with_selected_keys
print(character_positive_with_selected_keys)
PY
```

Expected: 打印函数对象。

---

### Task 4: ScriptComposer 接入 selected_keys

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/composers/script.py`
- Modify: `F:/my_project/new/tags_machine/refactor/src/tags_machine_core/nodes/character_scope.py`
- Test: `F:/my_project/new/tags_machine/refactor/tests/test_script_composer.py`

- [ ] **Step 1: 增加多角色逐 index 测试**

在 `tests/test_script_composer.py` 增加：

```python
def test_selected_keys_apply_per_character_index():
    homura = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "hair": ["black hair"],
            "feet": ["black shoes"],
        },
    )
    madoka = NodeDocument(
        kind="character",
        id="madoka",
        tags={
            "character": ["kaname madoka"],
            "hair": ["pink hair"],
            "feet": ["bare feet"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="duo_action",
        tags={"action": ["2girls, sitting"]},
        composition={
            "character_selection": {
                "source": "action_profile.yaml",
                "characters": [
                    {"selected_keys": ["character", "hair"]},
                    {"selected_keys": ["character", "feet"]},
                ],
            }
        },
    )
    nodes = ResolvedNodeSet(
        [
            ResolvedNode(role="character", ref="homura", index=0, node=homura),
            ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
            ResolvedNode(role="action", ref="duo_action", index=0, node=action),
        ]
    )

    bundle = ScriptComposer().compose_resolved_nodes(nodes)

    assert "akemi homura" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "black shoes" not in bundle.prompt.positive
    assert "kaname madoka" in bundle.prompt.positive
    assert "bare feet" in bundle.prompt.positive
    assert "pink hair" not in bundle.prompt.positive
    assert bundle.meta.extra["character_selection"]["source"] == "action_profile.yaml"
    assert bundle.meta.extra["character_materials"][0]["used_sections"] == ["character", "hair"]
    assert bundle.meta.extra["character_materials"][1]["used_sections"] == ["character", "feet"]
```

- [ ] **Step 2: 在 ScriptComposer 中增加 selected_keys resolver**

在 `src/tags_machine_core/composers/script.py` import 增加：

```python
    character_positive_with_selected_keys,
```

在类内增加：

```python
    def _character_selected_keys(
        self,
        action: NodeDocument | None,
        character_index: int,
    ) -> list[str] | None:
        if action is None:
            return None
        selection = action.composition.get("character_selection")
        if not isinstance(selection, dict):
            return None
        characters = selection.get("characters") or []
        if isinstance(characters, list) and characters:
            entry = characters[character_index] if character_index < len(characters) else characters[-1]
            if isinstance(entry, dict):
                keys = entry.get("selected_keys") or []
                if isinstance(keys, list):
                    return [str(key).strip() for key in keys if str(key).strip()]
        default_keys = selection.get("default_selected_keys") or []
        if isinstance(default_keys, list) and default_keys:
            return [str(key).strip() for key in default_keys if str(key).strip()]
        return None

    def _character_selection_meta(self, action: NodeDocument | None) -> dict[str, object] | None:
        if action is None:
            return None
        selection = action.composition.get("character_selection")
        return selection if isinstance(selection, dict) else None
```

- [ ] **Step 3: 修改 `compose_nodes` 单角色拼接**

把：

```python
        character_positive_tags, included_sections, suppressed_sections = character_positive(
            character,
            scope,
        )
```

替换为：

```python
        selected_keys = self._character_selected_keys(action, 0)
        character_positive_tags, included_sections, suppressed_sections = (
            character_positive_with_selected_keys(
                character,
                scope,
                selected_keys,
            )
        )
```

并在 `PromptMeta.extra` 记录：

```python
                extra={
                    "character_selection": self._character_selection_meta(action),
                } if self._character_selection_meta(action) else {},
```

- [ ] **Step 4: 修改 `compose_resolved_nodes` 多角色拼接**

在循环内把：

```python
            character_positive_tags, included, suppressed = character_positive(
                item.node,
                scope,
            )
```

替换为：

```python
            selected_keys = self._character_selected_keys(primary_action, item.index)
            character_positive_tags, included, suppressed = character_positive_with_selected_keys(
                item.node,
                scope,
                selected_keys,
            )
```

`character_materials.append(...)` 不能再直接调用旧 `character_material(...)`，改为显式构造：

```python
            character_materials.append(
                {
                    "ref": item.ref,
                    "id": item.node.id,
                    "index": item.index,
                    "used_sections": included,
                    "suppressed_sections": suppressed,
                    "positive_tags": character_positive_tags,
                    "negative_tags": character_negative,
                    "selected_keys": selected_keys or [],
                }
            )
```

在 `PromptMeta.extra` 增加：

```python
                    "character_selection": self._character_selection_meta(primary_action),
```

如果 `_character_selection_meta(primary_action)` 返回 `None`，不要写入该 key。

- [ ] **Step 5: 运行 ScriptComposer selected_keys 测试**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_script_composer.py -q
```

Expected: 新增 selected_keys 测试 PASS；如果旧测试因历史字段如 `style_ref` 或 `meta.character_ref` 失败，先单独运行新增测试，记录旧测试债务，不在本任务扩散修复。

- [ ] **Step 6: 提交 Composer 接入**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add src/tags_machine_core/nodes/character_scope.py src/tags_machine_core/composers/script.py tests/test_script_composer.py
git commit -m "feat: let script composer use action selected keys"
```

---

### Task 5: 真实动作目录拼接预览

**Files:**
- No code changes.

- [ ] **Step 1: 用真实 action 生成 PromptBundle 预览**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run python - <<'PY'
from pathlib import Path
from tags_machine_core.composers.script import ScriptComposer
from tags_machine_core.nodes.reader import NodeReader
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet

reader = NodeReader()
base = Path(r"F:/my_project/new/tags_machine/design")
action = reader.read(base / "动作改2/new/20260506_3P后入趴卧")
homura = reader.read(base / "角色/akemi_homura")
madoka = reader.read(base / "角色/kaname_madoka")
ultimate_madoka = reader.read(base / "角色/ultimate_madoka")
nodes = ResolvedNodeSet(
    [
        ResolvedNode(role="character", ref="akemi_homura", index=0, node=homura),
        ResolvedNode(role="character", ref="kaname_madoka", index=1, node=madoka),
        ResolvedNode(role="character", ref="ultimate_madoka", index=2, node=ultimate_madoka),
        ResolvedNode(role="action", ref="20260506_3P后入趴卧", index=0, node=action),
    ]
)
bundle = ScriptComposer().compose_resolved_nodes(nodes)
print(bundle.prompt.positive)
print(bundle.meta.extra.get("character_selection"))
print(bundle.meta.extra.get("character_materials"))
PY
```

Expected:

- prompt 中有 3 个角色身份相关 tags。
- 每个角色只包含 `run-prompt-prompt.md` front matter 选择的 sections。
- `character_materials[*].used_sections` 与 `selected_keys` 对齐。
- action tags 正常追加。

- [ ] **Step 2: 记录预览结果**

把输出摘要写入 `F:/my_project/new/tags_machine/refactor/docs/action_selected_keys_preview_20260626.md`：

```markdown
# Action Selected Keys Preview 2026-06-26

## Case

- action: `设计/动作改2/new/20260506_3P后入趴卧`
- characters: `akemi_homura`, `kaname_madoka`, `ultimate_madoka`
- composer: `script`

## Result

- character_selection source: `run-prompt-prompt.md`
- character 0 used_sections: `character`, `copyright`, `hair`
- character 1 used_sections: `character`, `copyright`, `hair`
- character 2 used_sections: `character`, `copyright`, `hair`

## Manual Check

- selected character sections pass: yes
- action tags appended pass: yes
- unrelated character sections removed pass: yes
```

记录 Step 1 命令打印出的真实 sections；不要手写推测结果。

- [ ] **Step 3: 提交预览记录**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add docs/action_selected_keys_preview_20260626.md
git commit -m "docs: record selected keys prompt preview"
```

---

### Task 6: 业务真实出图验收

**Files:**
- No required code changes.
- Create: `F:/my_project/new/tags_machine/refactor/docs/action_selected_keys_business_test_20260626.md`

- [ ] **Step 1: 跑一个真实 NovelAI 出图 case**

选择一个当前可用 artist，例如常用列表中的 `20260412`。用 batch 或 CLI 走 ScriptComposer 节点链路，不使用 AgentComposer。

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run python -m tags_machine_core run-prompt `
  --composer script `
  --character akemi_homura `
  --character kaname_madoka `
  --character ultimate_madoka `
  --action 20260506_3P后入趴卧 `
  --artist 20260412 `
  --nt 1 `
  --seed -1
```

如果当前 CLI 参数名与示例不同，先运行 `uv run python -m tags_machine_core run-prompt --help` 确认参数名，再执行等价命令；验收必须满足：

- composer 是 `script`
- 输入是 character/action/artist 节点
- action 是带 `run-prompt-prompt.md` front matter 的真实动作目录
- 真实调用 NovelAI，不使用 dry-run

- [ ] **Step 2: 检查生成图片 PNG 参数**

Run:

```powershell
cd F:/my_project/new/tags_machine/refactor
$image = "Step 1 生成命令打印出的图片绝对路径"
uv run python -m tags_machine_core inspect-image-params $image --normalized
```

Expected:

- 能读出 PNG 参数。
- prompt 中角色相关字段不包含被 selected_keys 排除的 section。
- action prompt 和 artist 参数正常存在。

- [ ] **Step 3: 写业务验收记录**

创建 `docs/action_selected_keys_business_test_20260626.md`：

```markdown
# Action Selected Keys Business Test 2026-06-26

## Case

- composer: `script`
- backend: `novelai`
- artist: `20260412`
- action: `20260506_3P后入趴卧`
- characters: `akemi_homura`, `kaname_madoka`, `ultimate_madoka`

## Outputs

- image: `Step 1 生成命令打印出的图片绝对路径`
- generation_result: `Step 1 生成命令打印出的结果 JSON 绝对路径`

## PNG Parameter Check

- PNG params readable: yes
- selected_keys applied: yes
- action tags present: yes
- artist params present: yes

## Visual Check

- subject/cast pass:
- action pass:
- style pass:
- obvious character section pollution:
```

- [ ] **Step 4: 提交业务验收记录**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add docs/action_selected_keys_business_test_20260626.md
git commit -m "docs: record selected keys business generation test"
```

---

### Task 7: 文档正式化

**Files:**
- Modify: `F:/my_project/new/tags_machine/refactor/docs/action_yaml_spec_v1.md`
- Modify: `F:/my_project/new/tags_machine/refactor/docs/refactor_architecture_v2.md`

- [ ] **Step 1: 更新 action spec**

在 `docs/action_yaml_spec_v1.md` 增加章节：

```markdown
## action_profile.yaml

`action_profile.yaml` 是 action 的拼接辅助元数据，不是最终 prompt，也不是后端参数。

当前正式字段：

```yaml
schema: tags-machine.action-profile/v1

character_selection:
  source: action_profile.yaml
  default_selected_keys:
    - character
    - copyright
  characters:
    - selected_keys:
        - character
        - copyright
        - hair
    - selected_keys:
        - character
        - copyright
        - feet
```

字段含义：

- `character_selection.default_selected_keys`：未给某个角色单独声明时使用的 character tags section。
- `character_selection.characters[].selected_keys`：按角色 index 指定要取的 character tags section。
- `source`：由读取器写入或显式声明，用于调试和验收。

ScriptComposer 的优先级：

```text
characters[index].selected_keys
> default_selected_keys
> character_scope policy
> default all character tags
```

`character_scope` 是兼容字段。新动作优先使用 `action_profile.yaml` 表达精确 section 选择。
```

- [ ] **Step 2: 更新架构文档**

在 `docs/refactor_architecture_v2.md` 的 ScriptComposer 数据流里补充：

```markdown
ScriptComposer 读取 action NodeDocument 上的 `composition.character_selection`。
如果存在 `selected_keys`，Composer 按角色 index 从 character `tags` 中选择 section；
如果不存在，则回退到 `character_scope` 兼容 policy。
AgentComposer 不经过该规则，避免影响当前稳定 agent cache 链路。
```

- [ ] **Step 3: 提交文档**

```powershell
cd F:/my_project/new/tags_machine/refactor
git add docs/action_yaml_spec_v1.md docs/refactor_architecture_v2.md
git commit -m "docs: specify action selected keys composition"
```

---

## 验收标准

### 功能验收

- `NodeReader` 可以从 `action_profile.yaml` 读取 selected keys。
- `NodeReader` 可以从 `run-prompt-prompt.md` YAML front matter 兼容读取 selected keys。
- `ScriptComposer.compose_nodes` 单角色路径使用 selected keys。
- `ScriptComposer.compose_resolved_nodes` 多角色路径按 character index 使用 selected keys。
- 没有 selected keys 时，旧 `character_scope` 规则保持不变。
- `AgentComposer` 不被调用、不改 cache key、不改 task payload。

### 业务验收

- 用真实 action `F:/my_project/new/tags_machine/design/动作改2/new/20260506_3P后入趴卧` 能拼出符合 front matter 的角色字段。
- 至少跑一次 NovelAI 真实出图。
- PNG 参数可读。
- 生成 prompt 中不包含被 selected_keys 排除的 character section。
- action prompt 和 artist 参数正常存在。

### 最小命令集

```powershell
cd F:/my_project/new/tags_machine/refactor
uv run --with pytest --with-editable . pytest tests/test_action_profile.py -q
uv run --with pytest --with-editable . pytest tests/test_node_reader.py::test_reader_attaches_action_profile_from_run_prompt_prompt -q
uv run --with pytest --with-editable . pytest tests/test_script_composer.py -q
```

业务验收必须额外跑真实 NovelAI 出图，不用 dry-run 代替。

## 风险与处理

- 风险：旧 `tests/test_script_composer.py` 里有历史 API 债务，例如过期 `style_ref` 或旧 `meta.character_ref` 断言。
  - 处理：本任务只保证新增 selected_keys 测试和相关当前链路通过；旧债务单独清理，不混在本功能里。

- 风险：部分 action 的 `run-prompt-prompt.md` front matter 是 agent 生成，字段不稳定。
  - 处理：解析器只接受 `characters[].selected_keys`，其他字段保存在 `raw`，不参与拼接。

- 风险：角色数量多于 `characters[]` 配置。
  - 处理：复用最后一个 `characters[]` entry；如果不存在，则 fallback 到 `default_selected_keys` 或 `character_scope`。

- 风险：`selected_keys` 写了 character meta.yaml 中不存在的 key。
  - 处理：忽略不存在的 key，在 `suppressed_sections` 中仍只记录真实存在但未使用的 section。

## 执行顺序

1. Task 1 解析器。
2. Task 2 NodeReader 注入。
3. Task 3 selection 统一函数。
4. Task 4 ScriptComposer 接入。
5. Task 5 真实动作目录拼接预览。
6. Task 6 NovelAI 真实业务出图。
7. Task 7 文档正式化。

每个 task 独立提交，避免和当前 refactor 里已有脏文件混在一起。
