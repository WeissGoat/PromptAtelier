from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tags_machine_core.contracts import utc_now_iso
from tags_machine_core.json_tools import to_jsonable

from .models import ActionGroupStrategyName, ActionSelectionName, SelectorSpec
from .selectors import (
    SelectorContext,
    discover_nodes,
    expand_selector,
    matching_directories,
    resolve_ref,
)


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


class ActionGroupRoundState(BaseModel):
    group: str
    status: Literal["started", "completed", "failed"] = "started"
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None


class ActionGroupRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.action-group-record/v1", alias="schema")
    updated_at: str = Field(default_factory=utc_now_iso)
    groups: dict[str, ActionGroupRecordEntry] = Field(default_factory=dict)
    recorded_rounds: dict[str, ActionGroupRoundState] = Field(default_factory=dict)

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

    def planning_baseline(self) -> "ActionGroupRecord":
        baseline = self.model_copy(deep=True)
        for round_state in baseline.recorded_rounds.values():
            entry = baseline.groups.get(round_state.group)
            if entry is None:
                continue
            entry.selected_count = max(0, entry.selected_count - 1)
            if round_state.status == "completed":
                entry.completed_count = max(0, entry.completed_count - 1)
            elif round_state.status == "failed":
                entry.failed_count = max(0, entry.failed_count - 1)
        baseline.recorded_rounds = {}
        return baseline


def mark_round_started(
    record: ActionGroupRecord,
    *,
    round_id: str,
    group_name: str,
) -> bool:
    existing = record.recorded_rounds.get(round_id)
    if existing is not None:
        if existing.group != group_name:
            raise ValueError(
                f"Round {round_id} already belongs to action group {existing.group}, not {group_name}"
            )
        return False
    record.recorded_rounds[round_id] = ActionGroupRoundState(group=group_name)
    record.increment_selected(group_name)
    record.updated_at = utc_now_iso()
    return True


def mark_round_finished(
    record: ActionGroupRecord,
    *,
    round_id: str,
    status: Literal["completed", "failed"],
) -> bool:
    round_state = record.recorded_rounds.get(round_id)
    if round_state is None:
        raise ValueError(f"Cannot finish unknown action group round: {round_id}")
    if round_state.status == status:
        return False
    entry = record.groups.get(round_state.group) or ActionGroupRecordEntry()
    if round_state.status == "failed" and status == "completed":
        entry.failed_count = max(0, entry.failed_count - 1)
    elif round_state.status == "completed" and status == "failed":
        entry.completed_count = max(0, entry.completed_count - 1)
    round_state.status = status
    round_state.finished_at = utc_now_iso()
    if status == "completed":
        entry.completed_count += 1
    else:
        entry.failed_count += 1
    record.groups[round_state.group] = entry
    record.updated_at = utc_now_iso()
    return True


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
        resolved = (
            _resolve_collection_groups(name, context=context)
            if spec.selector.strip() == "collection"
            else [_resolve_single_group(name, spec=spec, context=context)]
        )
        for group in resolved:
            if group.name in seen_names:
                raise ValueError(f"Duplicate action group name: {group.name}")
            seen_names.add(group.name)
            groups.append(group)
    return groups


def _resolve_single_group(
    name: str,
    *,
    spec: SelectorSpec,
    context: SelectorContext,
) -> ResolvedActionGroup:
    actions = [str(item) for item in expand_selector(role="action", spec=spec, context=context)]
    actions = list(dict.fromkeys(actions))
    if not actions:
        source = spec.root or spec.pattern or ",".join(spec.refs) or spec.name or spec.selector
        raise ValueError(f"Action group has no actions: {name} ({source})")
    return ResolvedActionGroup(
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


def _resolve_collection_groups(
    collection_name: str,
    *,
    context: SelectorContext,
    stack: tuple[str, ...] = (),
) -> list[ResolvedActionGroup]:
    collection_key = f"actions.{collection_name}"
    if collection_key in stack:
        chain = " -> ".join([*stack, collection_key])
        raise ValueError(f"Circular collection reference detected: {chain}")
    items = context.collections.get("actions", {}).get(collection_name, [])
    if not items:
        raise ValueError(f"Unknown action collection: {collection_name}")

    groups: list[ResolvedActionGroup] = []
    fallback_actions: list[str] = []
    next_stack = (*stack, collection_key)
    for item in items:
        if isinstance(item, dict) and "collection" in item:
            groups.extend(
                _resolve_collection_groups(
                    str(item["collection"]),
                    context=context,
                    stack=next_stack,
                )
            )
            continue
        if isinstance(item, dict) and item.get("selector") == "folder":
            selector = SelectorSpec.model_validate(item)
            if selector.root and selector.include:
                root = resolve_ref(selector.root, context.base_dir)
                directories = matching_directories(root, selector)
                for directory in directories:
                    child_spec = selector.model_copy(
                        update={
                            "root": str(directory),
                            "include": {},
                            "exclude": {},
                            "limit": None,
                            "shuffle": False,
                        }
                    )
                    actions = discover_nodes(directory, child_spec)
                    if actions:
                        groups.append(
                            ResolvedActionGroup(
                                name=directory.name,
                                actions=actions,
                                source={
                                    "selector": "folder",
                                    "collection": collection_name,
                                    "root": str(directory),
                                    "recursive": selector.recursive,
                                },
                            )
                        )
                if directories:
                    continue
        if isinstance(item, dict):
            selector = SelectorSpec.model_validate(item)
            fallback_actions.extend(expand_selector(role="action", spec=selector, context=context))
        else:
            fallback_actions.extend(
                discover_nodes(
                    resolve_ref(str(item), context.base_dir),
                    SelectorSpec(selector="collection", name=collection_name),
                )
            )

    if fallback_actions:
        groups.append(
            ResolvedActionGroup(
                name=collection_name,
                actions=list(dict.fromkeys(str(item) for item in fallback_actions)),
                source={"selector": "collection", "collection": collection_name},
            )
        )
    if not groups:
        raise ValueError(f"Action group collection has no actions: {collection_name}")
    return _merge_collection_groups(groups)


def _merge_collection_groups(groups: list[ResolvedActionGroup]) -> list[ResolvedActionGroup]:
    merged: dict[str, ResolvedActionGroup] = {}
    for group in groups:
        current = merged.get(group.name)
        if current is None:
            merged[group.name] = group.model_copy(deep=True)
            continue
        current.actions = list(dict.fromkeys([*current.actions, *group.actions]))
    return list(merged.values())


def select_group_actions(
    group: ResolvedActionGroup,
    *,
    strategy: ActionSelectionName,
    limit: int | None,
    rng: random.Random,
) -> list[str]:
    actions = list(group.actions)
    if limit is None or limit >= len(actions):
        return actions
    if strategy == "all":
        return actions[:limit]
    if strategy == "random_preserve_order":
        indices = sorted(rng.sample(range(len(actions)), k=limit))
        return [actions[index] for index in indices]
    raise ValueError(f"Unsupported action selection strategy: {strategy}")


def resolve_record_path(value: str | None, *, base_dir: str | Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(base_dir) / path


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
