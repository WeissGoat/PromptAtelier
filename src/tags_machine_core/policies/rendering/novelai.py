from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tags_machine_core.contracts import PromptBundle, RenderRequest
from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.policies.config import PolicyTarget, PromptPolicyConfig
from tags_machine_core.policies.registry import PromptPolicyRegistry

from .base import RenderPolicyContext
from .sources import ResolvedVibeSource, resolve_policy_path


logger = get_logger(__name__)

VIBE_PARAMETER_KEYS = (
    "reference_image_multiple",
    "reference_strength_multiple",
    "reference_information_extracted_multiple",
)


class NovelAIVibeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["artist", "image"]
    ref: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "NovelAIVibeSource":
        if self.type == "artist":
            if not self.ref or self.path:
                raise ValueError("novelai_vibe artist source requires ref and forbids path")
        elif self.type == "image":
            if not self.path or self.ref:
                raise ValueError("novelai_vibe image source requires path and forbids ref")
        return self


class NovelAIVibeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: NovelAIVibeSource
    strength: list[float] | float | None = None
    information_extracted: list[float] | float | None = None


def _number_list(value: Any, *, field_name: str) -> list[float]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[float] = []
    for item in values:
        try:
            parsed = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must contain numbers") from exc
        if not math.isfinite(parsed) or not 0 <= parsed <= 1:
            raise ValueError(f"{field_name} values must be between 0 and 1")
        result.append(parsed)
    return result


def _broadcast(values: list[float], *, count: int, field_name: str) -> list[float]:
    if not values:
        return []
    if len(values) == count:
        return list(values)
    if len(values) == 1:
        return values * count
    raise ValueError(
        f"{field_name} length must be 1 or match reference image count {count}; "
        f"got {len(values)}"
    )


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_summary(
    *,
    source_type: Literal["artist", "image"],
    source_ref: str,
    images: list[str],
    strengths: list[float],
    information_extracted: list[float],
    sizes: list[int],
) -> ResolvedVibeSource:
    hashes = [_hash_text(image) for image in images]
    return ResolvedVibeSource(
        source_type=source_type,
        source_ref=source_ref,
        images=images,
        strengths=strengths,
        information_extracted=information_extracted,
        source_sha256=hashes,
        source_sizes=sizes,
    )


def _resolve_artist_source(
    source: NovelAIVibeSource,
    options: NovelAIVibeOptions,
    *,
    design_root: Path | None,
) -> ResolvedVibeSource:
    assert source.ref is not None
    ref_path = Path(source.ref)
    if design_root is None and not ref_path.is_absolute():
        raise ValueError(
            "novelai_vibe artist source requires design_root for relative ref: "
            f"{source.ref}"
        )
    repository = NovelAIArtistRepository(design_root or Path("."))
    node = repository.load_node(source.ref)
    payload = node.renderers.get("novelai", {})
    params = payload.get("params", {}) if isinstance(payload, dict) else {}
    if not isinstance(params, dict):
        params = {}
    images = [str(item) for item in params.get("reference_image_multiple", []) or []]
    if not images:
        raise ValueError(
            f"novelai_vibe artist source has no reference_image_multiple: {source.ref}"
        )

    source_strengths = _number_list(
        params.get("reference_strength_multiple"),
        field_name="reference_strength_multiple",
    )
    source_information = _number_list(
        params.get("reference_information_extracted_multiple"),
        field_name="reference_information_extracted_multiple",
    )
    strengths = _broadcast(
        _number_list(options.strength, field_name="strength")
        or source_strengths,
        count=len(images),
        field_name="reference_strength_multiple",
    )
    if not strengths:
        raise ValueError(
            f"novelai_vibe artist source has no reference strengths: {source.ref}"
        )
    information = _broadcast(
        _number_list(options.information_extracted, field_name="information_extracted")
        or source_information,
        count=len(images),
        field_name="reference_information_extracted_multiple",
    )
    sizes = [len(image.encode("utf-8")) for image in images]
    return _source_summary(
        source_type="artist",
        source_ref=source.ref,
        images=images,
        strengths=strengths,
        information_extracted=information,
        sizes=sizes,
    )


def _resolve_image_source(
    source: NovelAIVibeSource,
    options: NovelAIVibeOptions,
    *,
    policy_relative_to: Path | None,
) -> ResolvedVibeSource:
    assert source.path is not None
    path = resolve_policy_path(source.path, relative_to=policy_relative_to)
    if not path.is_file():
        raise FileNotFoundError(f"NovelAI vibe image not found: {path}")
    content = path.read_bytes()
    if not content:
        raise ValueError(f"NovelAI vibe image is empty: {path}")
    strengths = _number_list(options.strength, field_name="strength")
    information = _number_list(
        options.information_extracted,
        field_name="information_extracted",
    )
    if not strengths or not information:
        raise ValueError(
            "novelai_vibe image source requires strength and information_extracted"
        )
    encoded = base64.b64encode(content).decode("ascii")
    return _source_summary(
        source_type="image",
        source_ref=str(path),
        images=[encoded],
        strengths=_broadcast(strengths, count=1, field_name="strength"),
        information_extracted=_broadcast(
            information,
            count=1,
            field_name="information_extracted",
        ),
        sizes=[len(content)],
    )


def resolve_vibe_source(
    options: NovelAIVibeOptions,
    *,
    design_root: Path | None = None,
    policy_relative_to: Path | None = None,
) -> ResolvedVibeSource:
    source = options.source
    if source.type == "artist":
        return _resolve_artist_source(source, options, design_root=design_root)
    return _resolve_image_source(source, options, policy_relative_to=policy_relative_to)


def _policy_metadata(source: ResolvedVibeSource) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "enabled": True,
        "rules": ["novelai_vibe@v1"],
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "image_count": len(source.images),
        "source_sha256": source.source_sha256,
        "source_sizes": source.source_sizes,
        "strength": source.strengths,
        "information_extracted": source.information_extracted,
        "replaced_fields": list(VIBE_PARAMETER_KEYS),
    }
    signature_payload = {
        key: value
        for key, value in metadata.items()
        if key not in {"enabled", "rules"}
    }
    signature = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
    metadata["signature"] = "sha256:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return metadata


class NovelAIVibePolicyRule:
    id = "novelai_vibe"
    version = "v1"
    scope = "renderer"
    backend = "novelai"
    phase = "bundle_finalize"
    default_enabled = False
    options_model = NovelAIVibeOptions

    def apply(self, context: RenderPolicyContext) -> RenderPolicyContext:
        options = NovelAIVibeOptions.model_validate(context.policy.options_for(self.id))
        source = resolve_vibe_source(
            options,
            design_root=context.design_root,
            policy_relative_to=context.policy_relative_to,
        )
        params = copy.deepcopy(context.request.params)
        params["reference_image_multiple"] = list(source.images)
        params["reference_strength_multiple"] = list(source.strengths)
        params["reference_information_extracted_multiple"] = list(
            source.information_extracted
        )
        meta = copy.deepcopy(context.request.meta)
        meta["novelai_render_policy"] = _policy_metadata(source)
        context.request = context.request.model_copy(update={"params": params, "meta": meta})
        context.add_trace(
            rule=f"{self.id}@{self.version}",
            action="replace_vibe",
            source_type=source.source_type,
            source_ref=source.source_ref,
            image_count=len(source.images),
        )
        logger.info(
            "NovelAI vibe policy applied source_type=%s source_ref=%s image_count=%s",
            source.source_type,
            source.source_ref,
            len(source.images),
        )
        return context


DEFAULT_RENDER_RULES = [NovelAIVibePolicyRule()]


class NovelAIRenderPolicyPipeline:
    """在基础 NovelAI RenderRequest 生成后执行后端专用规则。"""

    def __init__(self, registry: PromptPolicyRegistry | None = None):
        self.registry = registry or PromptPolicyRegistry(renderer_rules=DEFAULT_RENDER_RULES)

    def apply(
        self,
        request: RenderRequest,
        *,
        bundle: PromptBundle,
        resolved_nodes: ResolvedNodeSet | None,
        policy: PromptPolicyConfig,
        target: PolicyTarget,
        design_root: Path | None = None,
        policy_relative_to: Path | None = None,
    ) -> RenderRequest:
        if not policy.target_enabled(target):
            logger.trace(
                "NovelAIRenderPolicyPipeline skipped target=%s enabled=%s",
                target,
                policy.enabled,
            )
            return request
        context = RenderPolicyContext(
            request=request,
            bundle=bundle,
            resolved_nodes=resolved_nodes,
            policy=policy,
            target=target,
            design_root=design_root,
            policy_relative_to=policy_relative_to,
        )
        plan = self.registry.build_plan(policy, scope="renderer", backend="novelai")
        for rule in plan.effective_rules:
            context = rule.apply(context)
        if context.trace:
            meta = copy.deepcopy(context.request.meta)
            meta["novelai_render_policy_trace"] = context.trace
            context.request = context.request.model_copy(update={"meta": meta})
        return context.request
