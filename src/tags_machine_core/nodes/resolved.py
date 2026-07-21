from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

from tags_machine_core.contracts import PromptNodeRef
from tags_machine_core.nodes.models import NodeDocument


NodeRole = Literal[
    "artist",
    "character",
    "action",
    "background",
    "vibe",
    "reference",
    "prop",
    "camera",
    "lighting",
]

NODE_ROLE_ORDER = {
    "character": 0,
    "action": 1,
    "background": 2,
    "artist": 3,
}


def node_role_order(role: str) -> int:
    return NODE_ROLE_ORDER.get(role, len(NODE_ROLE_ORDER))


@dataclass(frozen=True)
class NodeInput:
    role: str
    ref: str

    @classmethod
    def parse(cls, value: str) -> "NodeInput":
        role, separator, ref = str(value).partition(":")
        if not separator or not role.strip() or not ref.strip():
            raise ValueError("node input must use role:ref")
        return cls(role=role.strip(), ref=ref.strip())


@dataclass(frozen=True)
class ResolvedNode:
    role: str
    ref: str
    index: int
    node: NodeDocument

    def as_ref(self) -> dict[str, object]:
        return {
            "role": self.role,
            "ref": self.ref,
            "id": self.node.id,
            "index": self.index,
        }

    def as_prompt_ref(self, content_hash: str | None = None) -> PromptNodeRef:
        return PromptNodeRef(
            role=self.role,
            ref=self.ref,
            id=self.node.id,
            kind=self.node.kind,
            index=self.index,
            content_hash=content_hash,
        )


class ResolvedNodeSet:
    def __init__(self, nodes: list[ResolvedNode] | None = None):
        self.nodes = list(nodes or [])

    def __iter__(self) -> Iterator[ResolvedNode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __bool__(self) -> bool:
        return bool(self.nodes)

    def by_role(self, role: str) -> list[ResolvedNode]:
        return [item for item in self.nodes if item.role == role]

    def first(self, role: str) -> ResolvedNode | None:
        items = self.by_role(role)
        return items[0] if items else None

    def characters(self) -> list[ResolvedNode]:
        return self.by_role("character")

    def actions(self) -> list[ResolvedNode]:
        return self.by_role("action")

    def backgrounds(self) -> list[ResolvedNode]:
        return self.by_role("background")

    def artists(self) -> list[ResolvedNode]:
        return self.by_role("artist")

    def refs(self) -> list[dict[str, object]]:
        return [item.as_ref() for item in self.nodes]
