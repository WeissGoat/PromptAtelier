from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from tags_machine_core.nodes.models import NodeDocument

from .models import FileMutation, NodeEditorDocument


class NodeSourceAdapter(Protocol):
    adapter_id: str

    def matches(self, node_dir: Path, role: str) -> bool: ...

    def read_editor(self, node_dir: Path) -> NodeEditorDocument: ...

    def build_runtime_node(
        self,
        node_dir: Path,
        values: dict[str, Any],
    ) -> NodeDocument: ...

    def preview_mutations(
        self,
        node_dir: Path,
        values: dict[str, Any],
    ) -> list[FileMutation]: ...
