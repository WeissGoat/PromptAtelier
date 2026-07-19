from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from tags_machine_core.json_tools import to_jsonable

from .action_groups import (
    ActionGroupRecord,
    mark_round_finished,
    mark_round_started,
)
from .models import BatchTask


class ActionGroupStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def for_run_dir(cls, run_dir: str | Path) -> "ActionGroupStateStore":
        return cls(Path(run_dir) / "state" / "action_groups.json")

    def load(self) -> ActionGroupRecord:
        if not self.path.exists():
            return ActionGroupRecord()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid action group state JSON: {self.path}: {exc}") from exc
        return ActionGroupRecord.model_validate(data)

    def save(self, record: ActionGroupRecord) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(to_jsonable(record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path

    def summary(self, record: ActionGroupRecord | None = None) -> dict[str, Any]:
        value = record or self.load()
        return {
            "rounds": len(value.recorded_rounds),
            "groups": {
                name: {
                    "selected": entry.selected_count,
                    "completed": entry.completed_count,
                    "failed": entry.failed_count,
                }
                for name, entry in sorted(value.groups.items())
            },
        }


class ActionGroupRunTracker:
    def __init__(self, run_dir: str | Path):
        self.store = ActionGroupStateStore.for_run_dir(run_dir)
        self.record = self.store.load()

    def start_task(self, task: BatchTask) -> None:
        round_id = str(task.source.get("round_id") or "")
        group = str(task.source.get("action_group") or "")
        if not round_id or not group:
            return
        if mark_round_started(self.record, round_id=round_id, group_name=group):
            self.store.save(self.record)

    def reconcile(
        self,
        tasks: list[BatchTask],
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        entries_by_task = {str(entry.get("task_id")): entry for entry in entries}
        rounds: dict[str, list[BatchTask]] = {}
        for task in tasks:
            round_id = str(task.source.get("round_id") or "")
            if round_id and round_id in self.record.recorded_rounds:
                rounds.setdefault(round_id, []).append(task)

        changed = False
        character_rounds: Counter[str] = Counter()
        for round_id, round_tasks in rounds.items():
            character = str(round_tasks[0].source.get("character") or "")
            if character:
                character_rounds[Path(character).name] += 1
            statuses = [
                str(entries_by_task[task.id].get("status") or "")
                for task in round_tasks
                if task.id in entries_by_task
            ]
            if not statuses:
                continue
            if "failed" in statuses:
                changed = mark_round_finished(
                    self.record,
                    round_id=round_id,
                    status="failed",
                ) or changed
            elif len(statuses) == len(round_tasks) and all(
                status in {"succeeded", "skipped"} for status in statuses
            ):
                changed = mark_round_finished(
                    self.record,
                    round_id=round_id,
                    status="completed",
                ) or changed
        if changed:
            self.store.save(self.record)
        return {
            **self.store.summary(self.record),
            "characters": dict(sorted(character_rounds.items())),
        }
