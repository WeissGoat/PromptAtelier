from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class ResolvedVibeSource:
    source_type: Literal["artist", "image"]
    source_ref: str
    images: list[str]
    strengths: list[float]
    information_extracted: list[float]
    source_sha256: list[str]
    source_sizes: list[int]


def resolve_policy_path(value: str | Path, *, relative_to: Path | None = None) -> Path:
    """按 Policy 配置文件目录解析路径，避免依赖当前工作目录。"""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        if relative_to is None:
            raise ValueError(
                f"Relative Policy path requires policy_relative_to: {value}"
            )
        candidate = relative_to / candidate
    return candidate.resolve()
