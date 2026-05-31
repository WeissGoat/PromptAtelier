from __future__ import annotations

import hashlib

from tags_machine_core.contracts import (
    CacheMeta,
    PromptBundle,
    PromptCompositionMeta,
    PromptMeta,
    PromptText,
)
from tags_machine_core.nodes.character_scope import (
    character_material,
    character_positive,
    dedupe,
    node_negative,
    node_positive,
    resolve_character_scope,
)
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNodeSet


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
        scope = resolve_character_scope(
            action=action,
            character=character,
            character_scope=character_scope or body_scope,
        )
        character_positive_tags, included_sections, suppressed_sections = character_positive(
            character,
            scope,
        )
        positive = _join_prompt_parts(
            character_positive_tags,
            node_positive(action, scope),
            node_positive(background, scope),
            extra_prompt,
        )
        negative_prompt = _join_prompt_parts(
            negative,
            node_negative(character, scope),
            node_negative(action, scope),
            node_negative(background, scope),
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

    def compose_resolved_nodes(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        body_scope: str | None = None,
    ) -> PromptBundle:
        characters = resolved_nodes.characters()
        actions = resolved_nodes.actions()
        backgrounds = resolved_nodes.backgrounds()
        primary_character = characters[0].node if characters else None
        primary_action = actions[0].node if actions else None
        scope = resolve_character_scope(
            action=primary_action,
            character=primary_character,
            character_scope=character_scope or body_scope,
        )

        positive_parts: list[str | list[str] | None] = []
        negative_parts: list[str | list[str] | None] = [negative]
        character_materials: list[dict[str, object]] = []
        included_sections: list[str] = []
        suppressed_sections: list[str] = []

        for item in characters:
            character_positive_tags, included, suppressed = character_positive(
                item.node,
                scope,
            )
            character_negative = node_negative(item.node, scope)
            positive_parts.append(character_positive_tags)
            negative_parts.append(character_negative)
            included_sections.extend(included)
            suppressed_sections.extend(suppressed)
            character_materials.append(
                character_material(
                    node=item.node,
                    ref=item.ref,
                    index=item.index,
                    character_scope=scope,
                )
            )

        for item in actions:
            positive_parts.append(node_positive(item.node, scope))
            negative_parts.append(node_negative(item.node, scope))
        for item in backgrounds:
            positive_parts.append(node_positive(item.node, scope))
            negative_parts.append(node_negative(item.node, scope))
        positive_parts.append(extra_prompt)

        positive = _join_prompt_parts(*positive_parts)
        negative_prompt = _join_prompt_parts(*negative_parts)
        prompt_nodes = [
            item
            for item in resolved_nodes
            if item.role not in {"artist", "style"}
        ]
        cache_key = self._cache_key(
            prompt=positive,
            negative=negative_prompt,
            style_ref=style_ref,
            character_scope=scope,
        )
        return PromptBundle(
            prompt=PromptText(positive=positive, negative=negative_prompt),
            meta=PromptMeta(
                character_ref=primary_character.id if len(characters) == 1 else None,
                action_ref=primary_action.id if primary_action else None,
                background_ref=backgrounds[0].node.id if len(backgrounds) == 1 else None,
                style_ref=style_ref,
                composer_type="script",
                composer_version=self.composer_version,
                composition=PromptCompositionMeta(
                    character_scope=scope,
                    included_character_sections=dedupe(included_sections),
                    suppressed_character_sections=dedupe(suppressed_sections),
                ),
                source_nodes=[item.node.source_ref() for item in prompt_nodes],
                extra={
                    "node_refs": [item.as_ref() for item in prompt_nodes],
                    "character_materials": character_materials,
                },
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def _cache_key(self, **parts: str | None) -> str:
        normalized = "\n".join(f"{key}={parts.get(key) or ''}" for key in sorted(parts))
        return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
