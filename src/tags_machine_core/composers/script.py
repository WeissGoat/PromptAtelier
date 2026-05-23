from __future__ import annotations

import hashlib

from tags_machine_core.contracts import (
    CacheMeta,
    PromptBundle,
    PromptConstraints,
    PromptMeta,
    PromptText,
    ShotMeta,
)
from tags_machine_core.nodes.models import NodeDocument


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
        body_scope: str | None = None,
    ) -> PromptBundle:
        shot = self._resolve_shot(action=action, character=character, body_scope=body_scope)
        scope = shot.body_scope
        positive = _join_prompt_parts(
            self._node_positive(character, scope),
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
        constraints = self._merge_constraints(character, action, background)
        cache_key = self._cache_key(
            prompt=positive,
            negative=negative_prompt,
            character_ref=character.id if character else None,
            action_ref=action.id if action else None,
            background_ref=background.id if background else None,
            style_ref=style_ref,
            body_scope=scope,
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
                shot=shot,
                constraints=constraints,
                source_nodes=source_nodes,
            ),
            cache=CacheMeta(cacheable=True, cache_key=cache_key),
        )

    def _node_positive(self, node: NodeDocument | None, body_scope: str | None) -> list[str]:
        if node is None:
            return []
        if node.prompt.positive:
            return node.positive_texts(body_scope)
        return node.all_tags()

    def _node_negative(self, node: NodeDocument | None, body_scope: str | None) -> list[str]:
        if node is None:
            return []
        return node.negative_texts(body_scope)

    def _resolve_shot(
        self,
        *,
        action: NodeDocument | None,
        character: NodeDocument | None,
        body_scope: str | None,
    ) -> ShotMeta:
        action_shot = action.shot if action else None
        character_shot = character.shot if character else None
        return ShotMeta(
            framing=(action_shot.framing if action_shot else None)
            or (character_shot.framing if character_shot else None),
            body_scope=body_scope
            or (action_shot.body_scope if action_shot else None)
            or (character_shot.body_scope if character_shot else None),
            camera=(action_shot.camera if action_shot else None)
            or (character_shot.camera if character_shot else None),
        )

    def _merge_constraints(self, *nodes: NodeDocument | None) -> PromptConstraints:
        required_parts: list[str] = []
        forbidden_parts: list[str] = []
        notes: list[str] = []
        for node in nodes:
            if node is None:
                continue
            required_parts.extend(node.constraints.required_parts)
            forbidden_parts.extend(node.constraints.forbidden_parts)
            notes.extend(node.constraints.notes)
        return PromptConstraints(
            required_parts=self._dedupe(required_parts),
            forbidden_parts=self._dedupe(forbidden_parts),
            notes=self._dedupe(notes),
        )

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
