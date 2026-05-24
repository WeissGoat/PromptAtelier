from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.contracts import (
    CacheMeta,
    PromptBundle,
    PromptCompositionMeta,
    PromptMeta,
    PromptText,
)
from tags_machine_core.nodes.models import NodeDocument


AGENT_COMPOSER_VERSION = "v1"


class AgentCompositionRequired(RuntimeError):
    def __init__(self, task: "AgentCompositionTask"):
        self.task = task
        super().__init__(
            f"Agent composition result required for cache key: {task.cache_key}"
        )


class AgentNodeSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str
    ref: str
    kind: str
    id: str
    content_hash: str
    node: dict[str, Any]


class AgentCompositionTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.agent-composition-task/v1", alias="schema")
    composer_version: str = AGENT_COMPOSER_VERSION
    nodes: dict[str, AgentNodeSnapshot] = Field(default_factory=dict)
    extra_prompt: str = ""
    negative: str = ""
    style_ref: str | None = None
    character_scope: str | None = None
    instructions: list[str] = Field(default_factory=list)
    agent_model: str | None = None
    cache_key: str


class AgentCompositionResult(BaseModel):
    positive: str
    negative: str = ""
    character_scope: str | None = None
    included_character_sections: list[str] = Field(default_factory=list)
    suppressed_character_sections: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_prompt_bundle_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        prompt = value.get("prompt")
        meta = value.get("meta") if isinstance(value.get("meta"), dict) else {}
        composition = (
            meta.get("composition")
            if isinstance(meta.get("composition"), dict)
            else {}
        )
        if isinstance(prompt, dict):
            normalized = dict(value)
            normalized.setdefault("positive", prompt.get("positive", ""))
            normalized.setdefault("negative", prompt.get("negative", ""))
            normalized.setdefault("character_scope", composition.get("character_scope"))
            normalized.setdefault(
                "included_character_sections",
                composition.get("included_character_sections", []),
            )
            normalized.setdefault(
                "suppressed_character_sections",
                composition.get("suppressed_character_sections", []),
            )
            return normalized
        return value


class AgentComposer:
    """把外部 agent 结果落成 PromptBundle，并提供可复用缓存。"""

    composer_version = AGENT_COMPOSER_VERSION

    def build_task(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
    ) -> AgentCompositionTask:
        nodes = {
            role: snapshot
            for role, snapshot in {
                "character": self._snapshot_node("character", character),
                "action": self._snapshot_node("action", action),
                "background": self._snapshot_node("background", background),
            }.items()
            if snapshot is not None
        }
        payload = {
            "composer_version": self.composer_version,
            "nodes": {
                role: snapshot.model_dump(mode="json", by_alias=True)
                for role, snapshot in nodes.items()
            },
            "extra_prompt": extra_prompt.strip(),
            "negative": negative.strip(),
            "style_ref": style_ref,
            "character_scope": character_scope,
            "instructions": instructions or [],
            "agent_model": _optional_text(agent_model),
        }
        cache_key = self._cache_key(self._task_cache_payload(payload))
        return AgentCompositionTask(cache_key=cache_key, **payload)

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
        instructions: list[str] | None = None,
        agent_model: str | None = None,
        result: AgentCompositionResult | dict[str, Any] | None = None,
        cache: PromptCache | None = None,
    ) -> PromptBundle:
        task = self.build_task(
            character=character,
            action=action,
            background=background,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            instructions=instructions,
            agent_model=agent_model,
        )
        if cache:
            cached = cache.get(task.cache_key)
            if cached:
                return cached
        if result is None:
            raise AgentCompositionRequired(task)
        bundle = self.compose_from_result(task, result)
        if cache:
            cache.put(bundle)
        return bundle

    def compose_from_result(
        self,
        task: AgentCompositionTask,
        result: AgentCompositionResult | dict[str, Any],
    ) -> PromptBundle:
        agent_result = (
            result
            if isinstance(result, AgentCompositionResult)
            else AgentCompositionResult.model_validate(result)
        )
        character = task.nodes.get("character")
        action = task.nodes.get("action")
        background = task.nodes.get("background")
        source_nodes = [node.ref for node in task.nodes.values()]
        return PromptBundle(
            prompt=PromptText(
                positive=agent_result.positive.strip(),
                negative=(agent_result.negative or task.negative).strip(),
            ),
            meta=PromptMeta(
                character_ref=character.id if character else None,
                action_ref=action.id if action else None,
                background_ref=background.id if background else None,
                style_ref=task.style_ref,
                composer_type="agent",
                composer_version=self.composer_version,
                composition=PromptCompositionMeta(
                    character_scope=agent_result.character_scope or task.character_scope,
                    included_character_sections=agent_result.included_character_sections,
                    suppressed_character_sections=agent_result.suppressed_character_sections,
                ),
                source_nodes=source_nodes,
                extra={
                    "agent": {
                        "task_schema": task.schema_id,
                        "instructions": task.instructions,
                        "agent_model": task.agent_model,
                        "notes": agent_result.notes,
                        "extra": agent_result.extra,
                    }
                },
            ),
            cache=CacheMeta(cacheable=True, cache_key=task.cache_key),
        )

    def _snapshot_node(self, role: str, node: NodeDocument | None) -> AgentNodeSnapshot | None:
        if node is None:
            return None
        node_payload = node.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude={"path"},
        )
        return AgentNodeSnapshot(
            role=role,
            ref=node.source_ref(),
            kind=node.kind,
            id=node.id,
            content_hash=self._cache_key(node_payload),
            node=node_payload,
        )

    def _cache_key(self, payload: dict[str, Any]) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _task_cache_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        nodes = {}
        for role, snapshot in payload.get("nodes", {}).items():
            nodes[role] = {
                "id": snapshot.get("id"),
                "kind": snapshot.get("kind"),
                "content_hash": snapshot.get("content_hash"),
            }
        return {**payload, "nodes": nodes}


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_agent_result(path: str | Path) -> AgentCompositionResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AgentCompositionResult.model_validate(data)
