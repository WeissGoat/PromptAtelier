from __future__ import annotations

from pathlib import Path
from typing import Any

from tags_machine_core.policies.config import PromptPolicyConfig
from tags_machine_core.policies.registry import PromptPolicyRegistry
from tags_machine_core.policies.source import PromptPolicySource
from tags_machine_core.policies.template_resolver import (
    PromptPolicyTemplateResolver,
    deep_merge,
)


class PromptPolicyProvider:
    def __init__(
        self,
        *,
        template_resolver: PromptPolicyTemplateResolver | None = None,
        registry: PromptPolicyRegistry | None = None,
        project_default_source: PromptPolicySource | dict[str, Any] | None = None,
        relative_to: str | Path | None = None,
    ):
        self.template_resolver = template_resolver or PromptPolicyTemplateResolver()
        self.registry = registry or PromptPolicyRegistry()
        resolved = self.template_resolver.resolve(
            project_default_source,
            implicit_template="default",
            relative_to=relative_to,
        )
        self._default_mapping = resolved.mapping
        self._default_config = self._validate(
            resolved.mapping,
            template=resolved.template,
            template_hash=resolved.template_hash,
        )

    @classmethod
    def with_builtin_defaults(cls) -> "PromptPolicyProvider":
        return cls()

    @property
    def default_config(self) -> PromptPolicyConfig:
        return self._default_config.model_copy(deep=True)

    def resolve(
        self,
        override: PromptPolicySource | PromptPolicyConfig | dict[str, Any] | None,
        *,
        relative_to: str | Path | None = None,
    ) -> PromptPolicyConfig:
        if override is None:
            return self.default_config
        if isinstance(override, PromptPolicyConfig):
            return self.registry.validate_config(override.model_copy(deep=True))

        source = override if isinstance(override, PromptPolicySource) else PromptPolicySource.model_validate(override)
        raw = source.as_mapping()
        if raw.get("require"):
            resolved = self.template_resolver.resolve(
                source,
                implicit_template=None,
                relative_to=relative_to,
            )
            mapping = resolved.mapping
            template = resolved.template
            template_hash = resolved.template_hash
        else:
            mapping = deep_merge(self._default_mapping, raw)
            template = self._default_config.template
            template_hash = self._default_config.template_hash
        return self._validate(mapping, template=template, template_hash=template_hash)

    def _validate(
        self,
        mapping: dict[str, Any],
        *,
        template: str | None,
        template_hash: str | None,
    ) -> PromptPolicyConfig:
        payload = dict(mapping)
        payload["template"] = template
        payload["template_hash"] = template_hash
        config = PromptPolicyConfig.model_validate(payload)
        return self.registry.validate_config(config)
