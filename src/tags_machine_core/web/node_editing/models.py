from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class NodeEditorSource(BaseModel):
    path: str
    format: str
    sha256: str | None = None
    writable: bool = True


class NodeEditorDocument(BaseModel):
    adapter: str
    role: str
    values: dict[str, Any] = Field(default_factory=dict)
    sources: list[NodeEditorSource] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)


class FileMutation(BaseModel):
    path: Path
    format: str
    before_text: str = ""
    after_text: str
    before_sha256: str | None = None
    # 写回时的换行处理，同 open(newline=...)：None 按系统换行写；"" 原样写（直接编辑源文件时保留原换行）。
    newline: str | None = None

    @property
    def changed(self) -> bool:
        return self.before_text != self.after_text
