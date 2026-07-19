from __future__ import annotations

from pathlib import Path

from tags_machine_core.nodes.reader import NodeReader

from .action_sources import ActionSourcesAdapter
from .artist_tags import LegacyArtistTagsAdapter
from .base import NodeSourceAdapter
from .character_yaml import CharacterMetaYamlAdapter


class NodeSourceAdapterRegistry:
    def __init__(self, adapters: list[NodeSourceAdapter]):
        self.adapters = adapters

    def resolve(self, node_dir: str | Path, role: str) -> NodeSourceAdapter:
        path = Path(node_dir).resolve()
        for adapter in self.adapters:
            if adapter.matches(path, role):
                return adapter
        raise ValueError(f"Unsupported node source for role={role}: {path}")


def create_default_registry(design_root: str | Path, reader: NodeReader | None = None) -> NodeSourceAdapterRegistry:
    node_reader = reader or NodeReader()
    return NodeSourceAdapterRegistry(
        [
            LegacyArtistTagsAdapter(Path(design_root)),
            ActionSourcesAdapter(node_reader),
            CharacterMetaYamlAdapter(node_reader),
        ]
    )
