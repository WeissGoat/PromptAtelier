from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    input_path: Path
    source_kind: str
    action: str = ""
    topic: str = ""
    ref: str | None = None
    source_detail: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_path", self.input_path.resolve())


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    evidence: ActionEvidence
    status: str
    relative_path: str = ""
    absolute_path: Path | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.absolute_path is not None:
            object.__setattr__(self, "absolute_path", self.absolute_path.resolve())

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "input": str(self.evidence.input_path),
            "source_kind": self.evidence.source_kind,
            "source_detail": self.evidence.source_detail,
            "action": self.evidence.action,
            "topic": self.evidence.topic,
            "ref": self.evidence.ref,
            "relative_path": self.relative_path,
            "absolute_path": str(self.absolute_path) if self.absolute_path else None,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ScanIssue:
    input_path: Path
    error: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_path", self.input_path.resolve())


@dataclass(frozen=True, slots=True)
class ScannedSource:
    kind: str
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path.resolve())


@dataclass(slots=True)
class ScanResult:
    task_dirs: list[Path] = field(default_factory=list)
    image_paths: list[Path] = field(default_factory=list)
    sources: list[ScannedSource] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
