from .base import PromptRule, RulePhase
from .character_extension import CharacterExtensionPolicyRule
from .character_count import CharacterCountRule
from .clothing import ClothingPolicyRule
from .dedupe import DedupeRule
from .tag_conflict import TagConflictRule
from .tag_normalize import TagNormalizeRule
from .visibility import VisibilityPolicyRule

DEFAULT_RULES: list[PromptRule] = [
    TagNormalizeRule(),
    DedupeRule(),
    CharacterExtensionPolicyRule(),
    TagConflictRule(),
    CharacterCountRule(),
    ClothingPolicyRule(),
    VisibilityPolicyRule(),
]

__all__ = [
    "CharacterCountRule",
    "CharacterExtensionPolicyRule",
    "ClothingPolicyRule",
    "DEFAULT_RULES",
    "DedupeRule",
    "PromptRule",
    "RulePhase",
    "TagConflictRule",
    "TagNormalizeRule",
    "VisibilityPolicyRule",
]
