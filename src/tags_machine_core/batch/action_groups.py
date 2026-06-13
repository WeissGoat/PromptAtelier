from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tags_machine_core.contracts import utc_now_iso
from tags_machine_core.json_tools import to_jsonable

from .models import ActionGroupStrategyName, SelectorSpec
from .selectors import SelectorContext, expand_selector


class ResolvedActionGroup(BaseModel):
    name: str
    actions: list[str]
    source: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("action group name must not be empty")
        return text


class ActionGroupRecordEntry(BaseModel):
    selected_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    last_selected_at: str | None = None


class ActionGroupRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.action-group-record/v1", alias="schema")
    updated_at: str = Field(default_factory=utc_now_iso)
    groups: dict[str, ActionGroupRecordEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> "ActionGroupRecord":
        if path is None:
            return cls()
        record_path = Path(path)
        if not record_path.exists():
            return cls()
        try:
            data = json.loads(record_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid action_group_record JSON: {record_path}: {exc}") from exc
        return cls.model_validate(data)

    def save(self, path: str | Path | None) -> None:
        if path is None:
            return
        record_path = Path(path)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = utc_now_iso()
        record_path.write_text(
            json.dumps(to_jsonable(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def selected_count(self, group_name: str) -> int:
        return self.groups.get(group_name, ActionGroupRecordEntry()).selected_count

    def increment_selected(self, group_name: str) -> int:
        entry = self.groups.get(group_name) or ActionGroupRecordEntry()
        entry.selected_count += 1
        entry.last_selected_at = utc_now_iso()
        self.groups[group_name] = entry
        return entry.selected_count


def resolve_action_groups(
    specs: list[SelectorSpec],
    *,
    context: SelectorContext,
) -> list[ResolvedActionGroup]:
    groups: list[ResolvedActionGroup] = []
    seen_names: set[str] = set()
    for spec in specs:
        name = (spec.name or "").strip()
        if not name:
            raise ValueError("select.action_groups item requires name")
        if name in seen_names:
            raise ValueError(f"Duplicate action group name: {name}")
        seen_names.add(name)

        actions = [str(item) for item in expand_selector(role="action", spec=spec, context=context)]
        actions = list(dict.fromkeys(actions))
        if not actions:
            source = spec.root or spec.pattern or ",".join(spec.refs) or spec.name or spec.selector
            raise ValueError(f"Action group has no actions: {name} ({source})")
        groups.append(
            ResolvedActionGroup(
                name=name,
                actions=actions,
                source={
                    "selector": spec.selector,
                    "root": spec.root,
                    "pattern": spec.pattern,
                    "recursive": spec.recursive,
                    "limit": spec.limit,
                },
            )
        )
    return groups


def resolve_record_path(value: str | None, *, base_dir: str | Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else path


def choose_action_group(
    groups: list[ResolvedActionGroup],
    *,
    strategy: ActionGroupStrategyName,
    character_index: int,
    rng: random.Random,
    record: ActionGroupRecord | None = None,
) -> tuple[ResolvedActionGroup, int | None]:
    if not groups:
        raise ValueError("character_action_group requires at least one action group")
    if strategy == "ordered":
        return groups[character_index % len(groups)], None
    if strategy == "random":
        return rng.choice(groups), None
    if strategy == "balanced_random":
        record = record or ActionGroupRecord()
        min_count = min(record.selected_count(group.name) for group in groups)
        candidates = [group for group in groups if record.selected_count(group.name) == min_count]
        chosen = rng.choice(candidates)
        return chosen, record.increment_selected(chosen.name)
    raise ValueError(f"Unsupported action_group_strategy: {strategy}")
