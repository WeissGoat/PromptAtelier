from __future__ import annotations

import hashlib

from tags_machine_core.contracts import CacheMeta, PromptBundle, PromptMeta, PromptText


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

    def _cache_key(self, **parts: str | None) -> str:
        normalized = "\n".join(f"{key}={parts.get(key) or ''}" for key in sorted(parts))
        return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
