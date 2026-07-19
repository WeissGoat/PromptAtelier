from .migration import (
    apply_legacy_tags_migration,
    audit_legacy_tags,
    migrate_legacy_action_tags,
    migrate_legacy_artist_tags,
    migrate_legacy_background_tags,
    migrate_legacy_character_tags,
    plan_legacy_tags_migration,
)
from .character_scope import (
    CHARACTER_SCOPE_POLICY,
    IDENTITY_MINIMAL_SECTIONS,
    character_material,
    character_positive,
    dedupe,
    node_negative,
    node_positive,
    resolve_character_scope,
)
from .artist_input_filter import (
    ArtistInputFilter,
    ArtistInputFilterConfig,
    ArtistNegativePromptFilterConfig,
)
from .models import NodeDocument
from .novelai_artist import NovelAIArtist, NovelAIArtistRepository
from .reader import NodeReader
from .resolved import NodeInput, ResolvedNode, ResolvedNodeSet
from .validation import validate_node_tree

# 兼容旧接口命名：style 节点在新实现里统一落到 artist 迁移函数。
migrate_legacy_style_tags = migrate_legacy_artist_tags

__all__ = [
    "ArtistInputFilter",
    "ArtistInputFilterConfig",
    "ArtistNegativePromptFilterConfig",
    "NodeDocument",
    "NodeInput",
    "NodeReader",
    "NovelAIArtist",
    "NovelAIArtistRepository",
    "ResolvedNode",
    "ResolvedNodeSet",
    "CHARACTER_SCOPE_POLICY",
    "IDENTITY_MINIMAL_SECTIONS",
    "apply_legacy_tags_migration",
    "audit_legacy_tags",
    "character_material",
    "character_positive",
    "dedupe",
    "migrate_legacy_action_tags",
    "migrate_legacy_artist_tags",
    "migrate_legacy_background_tags",
    "migrate_legacy_character_tags",
    "migrate_legacy_style_tags",
    "node_negative",
    "node_positive",
    "plan_legacy_tags_migration",
    "resolve_character_scope",
    "validate_node_tree",
]
