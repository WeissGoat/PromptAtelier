from __future__ import annotations

import hashlib
import json
from typing import Any

from tags_machine_core.contracts import (
    CacheMeta,
    PromptBundle,
    PromptCompositionMeta,
    PromptMeta,
    PromptNodeRef,
    PromptText,
)
from tags_machine_core.nodes.character_scope import (
    character_positive_with_selected_keys,
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
    ) -> PromptBundle:
        prompt = prompt.strip()
        negative = negative.strip()
        cache_key = self._cache_key(
            prompt=prompt,
            negative=negative,
        )
        return PromptBundle(
            prompt=PromptText(positive=prompt, negative=negative),
            meta=PromptMeta(
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
        artist: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        character_scope: str | None = None,
        body_scope: str | None = None,
    ) -> PromptBundle:
        scope = resolve_character_scope(
            action=action,
            character=character,
            character_scope=character_scope or body_scope,
        )
        selected_keys = self._character_selected_keys(action, 0)
        character_positive_tags, included_sections, suppressed_sections = (
            character_positive_with_selected_keys(
                character,
                scope,
                selected_keys,
            )
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
        node_refs = self._prompt_refs_from_nodes(
            ("character", character, 0),
            ("action", action, 0),
            ("background", background, 0),
            ("artist", artist, 0),
        )
        cache_key = self._cache_key(
            prompt=positive,
            negative=negative_prompt,
            character_scope=scope,
            nodes=json.dumps([ref.model_dump(mode="json") for ref in node_refs], sort_keys=True),
        )
        extra = self._prompt_extra(action=action)
        return PromptBundle(
            prompt=PromptText(positive=positive, negative=negative_prompt),
            meta=PromptMeta(
                composer_type="script",
                composer_version=self.composer_version,
                composition=PromptCompositionMeta(
                    character_scope=scope,
                    included_character_sections=included_sections,
                    suppressed_character_sections=suppressed_sections,
                ),
                nodes=node_refs,
                extra=extra,
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def compose_resolved_nodes(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
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
            selected_keys = self._character_selected_keys(primary_action, item.index)
            character_positive_tags, included, suppressed = character_positive_with_selected_keys(
                item.node,
                scope,
                selected_keys,
            )
            character_negative = node_negative(item.node, scope)
            positive_parts.append(character_positive_tags)
            negative_parts.append(character_negative)
            included_sections.extend(included)
            suppressed_sections.extend(suppressed)
            character_materials.append(
                {
                    "ref": item.ref,
                    "id": item.node.id,
                    "index": item.index,
                    "used_sections": included,
                    "suppressed_sections": suppressed,
                    "positive_tags": character_positive_tags,
                    "negative_tags": character_negative,
                    "selected_keys": selected_keys or [],
                }
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
        prompt_nodes = list(resolved_nodes)
        node_refs = [
            item.as_prompt_ref(content_hash=self._node_content_hash(item.node))
            for item in prompt_nodes
        ]
        cache_key = self._cache_key(
            prompt=positive,
            negative=negative_prompt,
            character_scope=scope,
            nodes=json.dumps([ref.model_dump(mode="json") for ref in node_refs], sort_keys=True),
        )
        extra = {
            "character_materials": character_materials,
        }
        selection_meta = self._character_selection_meta(primary_action)
        if selection_meta:
            extra["character_selection"] = selection_meta
        return PromptBundle(
            prompt=PromptText(positive=positive, negative=negative_prompt),
            meta=PromptMeta(
                composer_type="script",
                composer_version=self.composer_version,
                composition=PromptCompositionMeta(
                    character_scope=scope,
                    included_character_sections=dedupe(included_sections),
                    suppressed_character_sections=dedupe(suppressed_sections),
                ),
                nodes=node_refs,
                extra=extra,
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def _cache_key(self, **parts: str | None) -> str:
        normalized = "\n".join(f"{key}={parts.get(key) or ''}" for key in sorted(parts))
        return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _prompt_refs_from_nodes(
        self,
        *items: tuple[str, NodeDocument | None, int],
    ) -> list[PromptNodeRef]:
        refs: list[PromptNodeRef] = []
        for role, node, index in items:
            if node is None:
                continue
            refs.append(
                PromptNodeRef(
                    role=role,
                    id=node.id,
                    kind=node.kind,
                    ref=node.source_ref(),
                    index=index,
                    content_hash=self._node_content_hash(node),
                )
            )
        return refs

    def _node_content_hash(self, node: NodeDocument) -> str:
        payload: dict[str, Any] = node.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude={"path"},
        )
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _character_selected_keys(
        self,
        action: NodeDocument | None,
        character_index: int,
    ) -> list[str] | None:
        selection = self._character_selection_meta(action)
        if not selection:
            return None
        characters = selection.get("characters") or []
        if isinstance(characters, list) and characters:
            entry = characters[character_index] if character_index < len(characters) else characters[-1]
            if isinstance(entry, dict):
                keys = entry.get("selected_keys") or []
                if isinstance(keys, list):
                    normalized = [str(key).strip() for key in keys if str(key).strip()]
                    if normalized:
                        return normalized
        default_keys = selection.get("default_selected_keys") or []
        if isinstance(default_keys, list) and default_keys:
            return [str(key).strip() for key in default_keys if str(key).strip()]
        return None

    def _character_selection_meta(self, action: NodeDocument | None) -> dict[str, Any] | None:
        if action is None:
            return None
        selection = action.composition.get("character_selection")
        return selection if isinstance(selection, dict) else None

    def _prompt_extra(self, *, action: NodeDocument | None) -> dict[str, Any]:
        selection_meta = self._character_selection_meta(action)
        if not selection_meta:
            return {}
        return {"character_selection": selection_meta}
