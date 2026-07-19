from .base import PromptRule, RulePhase
from .character_extension import CharacterExtensionPolicyRule
from .character_section_filter import (
    CharacterSectionFilterOptions,
    CharacterSectionFilterPolicyRule,
)
from .character_count import CharacterCountRule
from .clothing import ClothingPolicyRule
from .character_weight import CharacterWeightOptions, CharacterWeightPolicyRule
from .dedupe import DedupeRule
from .tag_conflict import TagConflictRule
from .tag_normalize import TagNormalizeRule
from .visibility import VisibilityPolicyRule

DEFAULT_RULES: list[PromptRule] = [
    TagNormalizeRule(),
    DedupeRule(),
    CharacterExtensionPolicyRule(),
    CharacterSectionFilterPolicyRule(),
    TagConflictRule(),
    CharacterCountRule(),
    ClothingPolicyRule(),
    VisibilityPolicyRule(),
    CharacterWeightPolicyRule(),
]

__all__ = [
    "CharacterCountRule",
    "CharacterExtensionPolicyRule",
    "CharacterSectionFilterOptions",
    "CharacterSectionFilterPolicyRule",
    "CharacterWeightOptions",
    "CharacterWeightPolicyRule",
    "ClothingPolicyRule",
    "DEFAULT_RULES",
    "DedupeRule",
    "PromptRule",
    "RulePhase",
    "TagConflictRule",
    "TagNormalizeRule",
    "VisibilityPolicyRule",
]
