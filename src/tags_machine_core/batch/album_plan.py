"""读取 final AlbumPlan，并保持它与动作知识库工具的依赖边界。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import AlbumPlanInput


ALBUM_PLAN_SCHEMA = "tags-machine.album-plan/v1"


@dataclass(frozen=True)
class AlbumPlanFrame:
    phase_id: str
    scene_id: str
    frame_id: str
    character_refs: tuple[str, ...]
    character_node_paths: tuple[Path, ...]
    prompt: str
    negative_prompt: str
    action_source: dict[str, Any]
    notes: str | None


@dataclass(frozen=True)
class LoadedAlbumPlan:
    path: Path
    action_root: Path
    content_hash: str
    album_id: str
    title: str
    source: dict[str, Any]
    frames: tuple[AlbumPlanFrame, ...]


def load_album_plan(value: AlbumPlanInput) -> LoadedAlbumPlan:
    """读取 final Plan，只做执行所需的结构和角色节点校验。"""

    action_root = Path(value.action_root).resolve()
    if not action_root.is_dir():
        raise FileNotFoundError(f"album_plan.action_root not found: {action_root}")
    raw_path = Path(value.path)
    path = raw_path.resolve() if raw_path.is_absolute() else (action_root / raw_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"AlbumPlan not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"AlbumPlan must be a mapping: {path}")
    _validate_root(raw)

    pool = _character_pool(raw["characters"], action_root=action_root)
    frames = tuple(_read_frames(raw["phases"], pool=pool))
    if not frames:
        raise ValueError("AlbumPlan must contain at least one frame")
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return LoadedAlbumPlan(
        path=path,
        action_root=action_root,
        content_hash="sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        album_id=_require_text(raw, "id", "AlbumPlan"),
        title=_require_text(raw, "title", "AlbumPlan"),
        source=dict(_require_mapping(raw.get("source"), "AlbumPlan source")),
        frames=frames,
    )


def _validate_root(raw: Mapping[str, Any]) -> None:
    if raw.get("schema") != ALBUM_PLAN_SCHEMA:
        raise ValueError(f"AlbumPlan schema must be {ALBUM_PLAN_SCHEMA}")
    for field in ("id", "title", "source", "characters", "phases"):
        if field not in raw:
            raise ValueError(f"AlbumPlan missing required field: {field}")
    if "customization" in raw:
        raise ValueError("AlbumPlan does not support customization; use root characters instead")
    source = _require_mapping(raw["source"], "AlbumPlan source")
    if source.get("type") != "story_set" or not _is_text(source.get("ref")):
        raise ValueError("AlbumPlan source requires type: story_set and ref")
    if not isinstance(raw["phases"], list):
        raise ValueError("AlbumPlan phases must be a list")


def _character_pool(value: object, *, action_root: Path) -> dict[str, Path]:
    if not isinstance(value, list):
        raise ValueError("AlbumPlan characters must be a list")
    character_root = (action_root.parent / "角色").resolve()
    if not character_root.is_dir():
        raise FileNotFoundError(f"character root not found beside action_root: {character_root}")
    result: dict[str, Path] = {}
    for item in value:
        data = _require_mapping(item, "AlbumPlan character")
        ref = _require_text(data, "ref", "AlbumPlan character")
        if ref in result:
            raise ValueError(f"duplicate AlbumPlan character ref: {ref}")
        relative = Path(ref)
        if relative.is_absolute():
            raise ValueError("AlbumPlan character ref must be relative to design/角色")
        node_path = (character_root / relative).resolve()
        try:
            node_path.relative_to(character_root)
        except ValueError as exc:
            raise ValueError("AlbumPlan character ref must stay within design/角色") from exc
        if not (node_path / "meta.yaml").is_file():
            raise FileNotFoundError(f"AlbumPlan character meta.yaml not found: {node_path / 'meta.yaml'}")
        result[ref] = node_path
    return result


def _read_frames(phases: object, *, pool: Mapping[str, Path]) -> list[AlbumPlanFrame]:
    if not isinstance(phases, list):
        raise ValueError("AlbumPlan phases must be a list")
    phase_ids: set[str] = set()
    scene_ids: set[str] = set()
    frame_ids: set[str] = set()
    frames: list[AlbumPlanFrame] = []
    for phase in phases:
        phase_data = _require_mapping(phase, "AlbumPlan phase")
        phase_id = _require_text(phase_data, "id", "AlbumPlan phase")
        if phase_id in phase_ids:
            raise ValueError(f"duplicate AlbumPlan phase id: {phase_id}")
        phase_ids.add(phase_id)
        scenes = phase_data.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError(f"AlbumPlan phase {phase_id} requires scenes")
        for scene in scenes:
            scene_data = _require_mapping(scene, "AlbumPlan scene")
            scene_id = _require_text(scene_data, "id", "AlbumPlan scene")
            if scene_id in scene_ids:
                raise ValueError(f"duplicate AlbumPlan scene id: {scene_id}")
            scene_ids.add(scene_id)
            raw_frames = scene_data.get("frames")
            if not isinstance(raw_frames, list) or not raw_frames:
                raise ValueError(f"AlbumPlan scene {scene_id} requires frames")
            for frame in raw_frames:
                frame_data = _require_mapping(frame, "AlbumPlan frame")
                frame_id = _require_text(frame_data, "id", "AlbumPlan frame")
                if frame_id in frame_ids:
                    raise ValueError(f"duplicate AlbumPlan frame id: {frame_id}")
                frame_ids.add(frame_id)
                refs = _frame_character_refs(frame_data, pool=pool, frame_id=frame_id)
                action_source = _require_mapping(frame_data.get("action_source"), f"frame {frame_id}.action_source")
                if not _is_text(action_source.get("type")) or not isinstance(action_source.get("refs"), list):
                    raise ValueError(f"frame {frame_id} requires action_source type and refs")
                frames.append(
                    AlbumPlanFrame(
                        phase_id=phase_id,
                        scene_id=scene_id,
                        frame_id=frame_id,
                        character_refs=tuple(refs),
                        character_node_paths=tuple(pool[ref] for ref in refs),
                        prompt=_require_text(frame_data, "prompt", f"frame {frame_id}"),
                        negative_prompt=_require_string(frame_data, "negative_prompt", f"frame {frame_id}"),
                        action_source=dict(action_source),
                        notes=frame_data.get("notes") if isinstance(frame_data.get("notes"), str) else None,
                    )
                )
    return frames


def _frame_character_refs(frame: Mapping[str, Any], *, pool: Mapping[str, Path], frame_id: str) -> list[str]:
    value = frame.get("character_refs")
    if len(pool) > 1 and value is None:
        raise ValueError(f"frame {frame_id} must declare character_refs for a multi-character AlbumPlan")
    if value is None:
        return list(pool)
    if not isinstance(value, list) or not value:
        raise ValueError(f"frame {frame_id}.character_refs must be a non-empty list")
    refs = [_require_text({"ref": ref}, "ref", f"frame {frame_id}.character_refs") for ref in value]
    unknown = [ref for ref in refs if ref not in pool]
    if unknown:
        raise ValueError(f"frame {frame_id} references characters outside AlbumPlan pool: {unknown}")
    return refs


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_text(value: Mapping[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not _is_text(item):
        raise ValueError(f"{label} requires non-empty {field}")
    return str(item).strip()


def _require_string(value: Mapping[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError(f"{label} requires string {field}")
    return item


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
