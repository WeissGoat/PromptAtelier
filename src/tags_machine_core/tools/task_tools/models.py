from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RelatedResource:
    role: str
    id: str | None = None
    ref: str | None = None
    path: Path | None = None
    index: int = 0
    exists: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if self.path is not None:
            object.__setattr__(self, "path", self.path.resolve())
            object.__setattr__(self, "exists", self.path.is_dir())


@dataclass(slots=True)
class TaskContext:
    input_path: Path
    task_dir: Path
    archive_files: dict[str, Path] = field(default_factory=dict)
    resources: list[RelatedResource] = field(default_factory=list)
    render_request: dict[str, Any] | None = None
    prompt_bundle: dict[str, Any] | None = None
    generation_result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def resources_for(self, role: str) -> list[RelatedResource]:
        return [resource for resource in self.resources if resource.role == role]


@dataclass(slots=True)
class TaskContextSet:
    tasks: list[TaskContext]

    def resources_for(self, role: str) -> list[RelatedResource]:
        return [
            resource
            for task in self.tasks
            for resource in task.resources_for(role)
        ]

    def existing_paths(self, role: str) -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for resource in self.resources_for(role):
            if resource.path is None or not resource.exists:
                continue
            key = str(resource.path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(resource.path.resolve())
        return result
