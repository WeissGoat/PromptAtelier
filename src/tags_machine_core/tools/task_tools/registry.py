from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from .config import OperationPlacement
from .models import TaskContextSet
from .operations.open_directory import (
    DirectoryOpener,
    open_directory_with_explorer,
    open_related_directories,
)

OperationResult = Any


class OperationHandler(Protocol):
    def __call__(self, contexts: TaskContextSet) -> "OperationResult":
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class OperationSpec:
    id: str
    default_label: str
    target_role: str
    default_placement: OperationPlacement
    default_order: int
    supports_multiple_tasks: bool = True
    supports_multiple_resources: bool = True
    handler: OperationHandler | None = None


class OperationRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> None:
        if spec.id in self._specs:
            raise ValueError(f"\u91cd\u590d\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1a{spec.id}")
        self._specs[spec.id] = spec

    def get(self, operation_id: str) -> OperationSpec:
        try:
            return self._specs[operation_id]
        except KeyError as exc:
            raise KeyError(f"\u672a\u77e5\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1a{operation_id}") from exc

    def all(self) -> list[OperationSpec]:
        return list(self._specs.values())

    def ids(self) -> list[str]:
        return list(self._specs)


def build_default_registry(
    *,
    directory_opener: DirectoryOpener = open_directory_with_explorer,
) -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(
        OperationSpec(
            id="open_action_directory",
            default_label="\u6253\u5f00 Action \u76ee\u5f55",
            target_role="action",
            default_placement=OperationPlacement.BOTH,
            default_order=10,
            handler=partial(
                open_related_directories,
                role="action",
                opener=directory_opener,
            ),
        )
    )
    registry.register(
        OperationSpec(
            id="open_artist_directory",
            default_label="\u6253\u5f00 Artist \u76ee\u5f55",
            target_role="artist",
            default_placement=OperationPlacement.BOTH,
            default_order=20,
            handler=partial(
                open_related_directories,
                role="artist",
                opener=directory_opener,
            ),
        )
    )
    return registry
