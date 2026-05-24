from __future__ import annotations

import hashlib

from tags_machine_core.contracts import (
    CacheMeta,
    PromptBundle,
    PromptCompositionMeta,
    PromptMeta,
    PromptText,
)
from tags_machine_core.nodes.models import NodeDocument


CHARACTER_SCOPE_POLICY: dict[str, dict[str, list[str] | None]] = {
    "default": {"include": None},
    "full_body": {"include": None},
    "upper_body": {
        "include": [
            "character",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "upper_clothes",
            "full_body_clothes",
            "handwear",
            "body",
            "hands",
            "accessories",
            "weapons",
            "props",
            "wings",
            "tail",
            "extra",
        ],
    },
    "lower_body": {
        "include": [
            "character",
            "copyright",
            "role",
            "body",
            "lower_clothes",
            "full_body_clothes",
            "legwear",
            "footwear",
            "feet",
            "tail",
            "extra",
        ],
    },
    "portrait": {
        "include": [
            "character",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "upper_clothes",
            "accessories",
            "extra",
        ],
    },
    "face_detail": {
        "include": [
            "character",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "extra",
        ],
    },
    "hand_detail": {
        "include": [
            "character",
            "copyright",
            "role",
            "body",
            "hands",
            "handwear",
            "accessories",
            "props",
            "weapons",
            "extra",
        ],
    },
    "foot_detail": {
        "include": [
            "character",
            "copyright",
            "role",
            "body",
            "feet",
            "legwear",
            "footwear",
            "extra",
        ],
    },
    "object_focus": {
        "include": [
            "character",
            "copyright",
            "role",
            "accessories",
            "weapons",
            "props",
            "extra",
        ],
    },
}


def _join_prompt_parts(*parts: str | list[str] | None) -> str:
    items: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, list):
            items.extend(str(item).strip(" ,") for item in part if str(item).strip(" ,"))
        else:
            text = str(part).strip(" ,")
            if text:
                items.append(text)
    return ", ".join(items)


class ScriptComposer:
    """Minimal deterministic composer for an already complete subject prompt."""

    composer_version = "v1"

    def compose_full_prompt(
        self,
        prompt: str,
        negative: str = "",
        character_ref: str | None = None,
        action_ref: str | None = None,
        style_ref: str | None = None,
    ) -> PromptBundle:
        prompt = prompt.strip()
        negative = negative.strip()
        cache_key = self._cache_key(
            prompt=prompt,
            negative=negative,
            character_ref=character_ref,
            action_ref=action_ref,
            style_ref=style_ref,
        )
        return PromptBundle(
            prompt=PromptText(positive=prompt, negative=negative),
            meta=PromptMeta(
                character_ref=character_ref,
                action_ref=action_ref,
                style_ref=style_ref,
                composer_type="script",
                composer_version=self.composer_version,
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def compose_nodes(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        body_scope: str | None = None,
    ) -> PromptBundle:
        scope = self._resolve_character_scope(
            action=action,
            character=character,
            character_scope=character_scope or body_scope,
        )
        character_positive, included_sections, suppressed_sections = self._character_positive(
            character,
            scope,
        )
        positive = _join_prompt_parts(
            character_positive,
            self._node_positive(action, scope),
            self._node_positive(background, scope),
            extra_prompt,
        )
        negative_prompt = _join_prompt_parts(
            negative,
            self._node_negative(character, scope),
            self._node_negative(action, scope),
            self._node_negative(background, scope),
        )
        source_nodes = [
            node.source_ref()
            for node in [character, action, background]
            if node is not None
        ]
        cache_key = self._cache_key(
            prompt=positive,
            negative=negative_prompt,
            character_ref=character.id if character else None,
            action_ref=action.id if action else None,
            background_ref=background.id if background else None,
            style_ref=style_ref,
            character_scope=scope,
        )
        return PromptBundle(
            prompt=PromptText(positive=positive, negative=negative_prompt),
            meta=PromptMeta(
                character_ref=character.id if character else None,
                action_ref=action.id if action else None,
                background_ref=background.id if background else None,
                style_ref=style_ref,
                composer_type="script",
                composer_version=self.composer_version,
                composition=PromptCompositionMeta(
                    character_scope=scope,
                    included_character_sections=included_sections,
                    suppressed_character_sections=suppressed_sections,
                ),
                source_nodes=source_nodes,
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def _character_positive(
        self,
        node: NodeDocument | None,
        character_scope: str | None,
    ) -> tuple[list[str], list[str], list[str]]:
        if node is None:
            return [], [], []
        if node.prompt.positive:
            included_roles: list[str] = []
            suppressed_roles: list[str] = []
            texts: list[str] = []
            for fragment in node.prompt.positive:
                role = fragment.role or "prompt"
                if fragment.applies_to(character_scope):
                    texts.append(fragment.text)
                    included_roles.append(role)
                else:
                    suppressed_roles.append(role)
            return texts, self._dedupe(included_roles), self._dedupe(suppressed_roles)

        sections = list(node.tags.keys())
        include_sections = self._included_character_sections(sections, character_scope)
        include_set = set(include_sections)
        suppressed_sections = [section for section in sections if section not in include_set]
        texts: list[str] = []
        for section in include_sections:
            texts.extend(node.tags.get(section, []))
        return texts, include_sections, suppressed_sections

    def _node_positive(self, node: NodeDocument | None, character_scope: str | None) -> list[str]:
        if node is None:
            return []
        if node.kind == "character":
            return self._character_positive(node, character_scope)[0]
        if node.prompt.positive:
            return node.positive_texts(character_scope)
        return node.all_tags()

    def _node_negative(self, node: NodeDocument | None, character_scope: str | None) -> list[str]:
        if node is None:
            return []
        items: list[str] = []
        items.extend(node.negative_prompt)
        items.extend(node.negative_texts(character_scope))
        return items

    def _resolve_character_scope(
        self,
        *,
        action: NodeDocument | None,
        character: NodeDocument | None,
        character_scope: str | None,
    ) -> str:
        return (
            character_scope
            or (action.character_scope if action else None)
            or (character.character_scope if character else None)
            or "default"
        )

    def _included_character_sections(
        self,
        sections: list[str],
        character_scope: str | None,
    ) -> list[str]:
        policy = CHARACTER_SCOPE_POLICY.get(
            character_scope or "default",
            CHARACTER_SCOPE_POLICY["default"],
        )
        include = policy.get("include")
        if include is None:
            return sections
        include_set = set(include)
        return [section for section in sections if section in include_set]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _cache_key(self, **parts: str | None) -> str:
        normalized = "\n".join(f"{key}={parts.get(key) or ''}" for key in sorted(parts))
        return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
