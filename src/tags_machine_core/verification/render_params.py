from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tags_machine_core.verification.image_params import read_image_parameters


IMAGE_LIKE_KEYS = {
    "image",
    "mask",
    "reference_image",
    "reference_image_multiple",
    "director_reference_images",
}

IGNORED_PARAMETER_KEYS = {
    "Generation_time",
    "signed_hash",
    "request_type",
    "stream",
}


@dataclass(frozen=True)
class RenderParamDiff:
    path: str
    left: Any
    right: Any
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "left": self.left,
            "right": self.right,
        }


def load_render_parameter_source(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".png":
        return read_image_parameters(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def normalize_render_parameters(source: dict[str, Any]) -> dict[str, Any]:
    payload = _as_novelai_payload(source)
    parameters = {
        key: value
        for key, value in payload.get("parameters", {}).items()
        if key not in IGNORED_PARAMETER_KEYS
    }
    normalized = {
        "input": payload.get("input") or parameters.get("prompt"),
        "model": payload.get("model") or parameters.get("model"),
        "action": payload.get("action") or "generate",
        "parameters": parameters,
    }
    return _summarize_image_values(normalized)


def compare_render_parameters(
    left: dict[str, Any],
    right: dict[str, Any],
) -> list[RenderParamDiff]:
    return _diff_values(
        normalize_render_parameters(left),
        normalize_render_parameters(right),
        "$",
    )


def _as_novelai_payload(source: dict[str, Any]) -> dict[str, Any]:
    if "png_text" in source:
        return _as_novelai_payload(source.get("png_text") or {})

    if "Comment" in source:
        comment = source.get("Comment")
        if isinstance(comment, str):
            try:
                comment = json.loads(comment)
            except json.JSONDecodeError:
                comment = {}
        if isinstance(comment, dict):
            return _payload_from_parameters(
                comment,
                model=_model_from_source(source),
            )

    if "parameters" in source and isinstance(source.get("parameters"), dict):
        parameters = dict(source["parameters"])
        if "input" in source or "model" in source or "action" in source:
            return {
                "input": source.get("input") or parameters.get("prompt"),
                "model": source.get("model") or parameters.get("model"),
                "action": source.get("action"),
                "parameters": parameters,
            }
        return _payload_from_parameters(parameters, model=source.get("model"))

    if "params" in source and isinstance(source.get("params"), dict):
        parameters = dict(source["params"])
        return {
            "input": source.get("prompt") or parameters.get("prompt"),
            "model": source.get("model") or parameters.get("model"),
            "action": (source.get("meta") or {}).get("action") if isinstance(source.get("meta"), dict) else None,
            "parameters": parameters,
        }

    return _payload_from_parameters(source)


def _payload_from_parameters(parameters: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    return {
        "input": parameters.get("prompt"),
        "model": model or parameters.get("model"),
        "action": parameters.get("action"),
        "parameters": parameters,
    }


def _model_from_source(source: dict[str, Any]) -> str | None:
    source_text = source.get("Source")
    if not isinstance(source_text, str):
        return None
    if "V4.5" in source_text:
        return "nai-diffusion-4-5-full"
    if "V4" in source_text:
        return "nai-diffusion-4-full"
    return None


def _summarize_image_values(value: Any, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: _summarize_image_values(item, str(key))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_summarize_image_values(item, parent_key) for item in value]
    if isinstance(value, bytes):
        return _hash_summary(value, value_type="bytes")
    if isinstance(value, str) and parent_key in IMAGE_LIKE_KEYS:
        return _hash_summary(value.encode("utf-8"), value_type="string", chars=len(value))
    return value


def _hash_summary(data: bytes, *, value_type: str, chars: int | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": value_type,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    if chars is not None:
        summary["chars"] = chars
    return summary


def _diff_values(left: Any, right: Any, path: str) -> list[RenderParamDiff]:
    if type(left) is not type(right):
        return [RenderParamDiff(path=path, left=left, right=right, kind="type")]
    if isinstance(left, dict):
        diffs: list[RenderParamDiff] = []
        for key in sorted(set(left) | set(right), key=str):
            child_path = f"{path}.{key}"
            if key not in left or key not in right:
                diffs.append(
                    RenderParamDiff(
                        path=child_path,
                        left=left.get(key, "<missing>"),
                        right=right.get(key, "<missing>"),
                        kind="key",
                    )
                )
            else:
                diffs.extend(_diff_values(left[key], right[key], child_path))
        return diffs
    if isinstance(left, list):
        if len(left) != len(right):
            return [RenderParamDiff(path=path, left=len(left), right=len(right), kind="length")]
        diffs = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            diffs.extend(_diff_values(left_item, right_item, f"{path}[{index}]"))
        return diffs
    if left != right:
        return [RenderParamDiff(path=path, left=left, right=right, kind="value")]
    return []
