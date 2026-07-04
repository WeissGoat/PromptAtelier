from .base import PromptRule, RulePhase
from .character_count import CharacterCountRule
from .clothing import ClothingPolicyRule
from .dedupe import DedupeRule
from .tag_conflict import TagConflictRule
from .tag_normalize import TagNormalizeRule
from .visibility import VisibilityPolicyRule

DEFAULT_RULES: list[PromptRule] = [
    TagNormalizeRule(),
    DedupeRule(),
    TagConflictRule(),
    CharacterCountRule(),
    ClothingPolicyRule(),
    VisibilityPolicyRule(),
]

__all__ = [
    "CharacterCountRule",
    "ClothingPolicyRule",
    "DEFAULT_RULES",
    "DedupeRule",
    "PromptRule",
    "RulePhase",
    "TagConflictRule",
    "TagNormalizeRule",
    "VisibilityPolicyRule",
]
