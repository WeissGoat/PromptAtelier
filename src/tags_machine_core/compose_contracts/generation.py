"""契约帧到现有后台生图请求的适配；不拼写提示词，也不绑定 HTTP。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.sizes import size_presets

from .selection import select_frames


class ContractGenerationOptions(BaseModel):
    artist: str = Field(min_length=1)
    frames: str | None = None
    nt: int = Field(default=1, ge=1)
    seed: int | None = None
    size: Literal["contract", "random", "portrait", "landscape", "square", "custom"] = "contract"
    width: int = Field(default=832, ge=64, multiple_of=8)
    height: int = Field(default=1216, ge=64, multiple_of=8)
    negative: str = ""
    character_prompts: Literal["auto", "off"] = "auto"
    add_male_caption: bool = False
    comfyui_target: str | None = None
    skip_duplicates: bool = True
    dry_run: bool = False
    allow_over_limit: bool = False


def _join(parts: list[str]) -> str:
    return ", ".join(
        text.strip().strip(",").strip() for text in parts if text.strip().strip(",").strip()
    )


def build_generation_batch(
    detail: dict[str, Any],
    artist: NodeDocument,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """与 Web 的 buildFrameRequest 相同：保留画幅、多角色、负面词和结果回挂。"""
    if detail.get("parse_error"):
        raise ValueError(detail["parse_error"])
    frames = select_frames(detail.get("frames") or [], settings.get("frames"))
    if not frames:
        raise ValueError("没有可生成的帧；先在契约里写出示例帧")
    selected = {frame["id"] for frame in frames}
    errors = [
        issue["message"]
        for issue in detail.get("issues", [])
        if issue.get("severity") == "error"
        and (not issue.get("frame_id") or issue["frame_id"] in selected)
    ]
    if errors:
        raise ValueError("契约校验未通过：" + "；".join(errors))
    backend = (
        "comfyui"
        if "comfyui" in artist.renderers and "novelai" not in artist.renderers
        else "novelai"
    )
    presets = size_presets(artist.renderers.get(backend) or {})
    count = int(settings.get("nt", 1))
    width, height = int(settings.get("width", 832)), int(settings.get("height", 1216))
    if count < 1:
        raise ValueError("nt 必须至少为 1")
    if min(width, height) < 64 or width % 8 or height % 8:
        raise ValueError("宽高必须至少为 64，且是 8 的倍数")
    mode = settings.get("size", "contract")
    if mode not in {"contract", "random", "portrait", "landscape", "square", "custom"}:
        raise ValueError("无效的尺寸选项")
    seed = settings.get("seed")
    seed = int(seed) if seed is not None and str(seed).strip() else None
    if seed is not None and seed < 0:
        seed = None
    output = f"compares/contract_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    artist_ref = str(artist.path or settings["artist"])
    artist_name = artist.name or artist.id
    items = []
    for frame in frames:
        use_characters = backend == "novelai" and settings.get("character_prompts", "auto") != "off"
        captions = frame.get("character_prompts") or []
        merge = captions if not use_characters else []
        positive = _join([frame["submit"].get("positive", ""), *[c["positive"] for c in merge]])
        negative = _join(
            [
                frame["submit"].get("negative", ""),
                *[c["negative"] for c in merge],
                str(settings.get("negative") or ""),
            ]
        )
        if not positive:
            raise ValueError(f"{frame['id']} 没有正向提示词")
        ids = frame.get("characters") or list(detail["sources"]["characters"])
        nodes = [
            {"role": "character", "ref": detail["sources"]["characters"][cid]["path"]}
            for cid in ids
            if cid in detail["sources"]["characters"]
        ]
        if not nodes:
            members = (detail["sources"].get("action_group") or {}).get("members") or []
            nodes = [
                {"role": "action", "ref": m["path"]}
                for m in members
                if m["index"] == frame.get("member_index")
            ]
        if not nodes:
            raise ValueError(f"{frame['id']} 没有可读取的角色或来源动作")
        size = (frame.get("size") or "random") if mode == "contract" else mode
        if mode == "contract" and size not in {"random", *presets}:
            size = "random"
        params: dict[str, Any] = {"n_samples": count, "size": size}
        if use_characters:
            params["character_prompts"] = {
                "mode": "explicit" if captions else "auto",
                "add_male_caption": bool(settings.get("add_male_caption")),
            }
            if captions:
                params["character_prompts"].update(
                    captions=[
                        {"positive": c["positive"], "negative": c["negative"]} for c in captions
                    ],
                    unsupported="merge",
                )
        items.append(
            {
                "label": f"{frame['id']} {frame['title']}",
                "labels": {
                    "contract": detail["request"].get("title") or detail["id"],
                    "frame": frame["id"],
                    "artist": artist_name,
                },
                "compose_request": {
                    "compose": {
                        "composer": "agent",
                        "nodes": nodes,
                        "negative": "",
                        "agent_result": {"positive": positive, "negative": negative},
                        "contract": {
                            "id": detail["id"],
                            "frame_id": frame["id"],
                            "prompt_hash": frame["prompt_hash"],
                            "artist": artist_name,
                        },
                    },
                    "render": {
                        "backend": backend,
                        "artist": artist_ref,
                        "width": width,
                        "height": height,
                        "seed": seed,
                        "params": params,
                    },
                },
                "generate": {
                    "output_dir": f"{output}/{frame['id']}",
                    "skip_duplicates": settings.get("skip_duplicates", True),
                    **(
                        {"comfyui_target": settings["comfyui_target"]}
                        if backend == "comfyui" and settings.get("comfyui_target")
                        else {}
                    ),
                },
            }
        )
    return {
        "label": f"契约 · {detail['request'].get('title') or detail['id']} · {len(items)} 帧",
        "kind": "primary",
        "output_dir": output,
        "items": items,
    }
