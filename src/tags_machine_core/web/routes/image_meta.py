from __future__ import annotations

import base64
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.clients.novelai import normalize_novelai_model
from tags_machine_core.verification.image_params import (
    read_image_parameters,
    read_png_dimensions,
)
from tags_machine_core.web.errors import ApiError

router = APIRouter()


def _parse_meta_dict(
    params_dict: dict[str, Any],
    png_text: dict[str, Any],
    dimensions: dict[str, int],
    filename: str,
    target_path: Path | None = None,
) -> dict[str, Any]:
    notice: str | None = None
    is_infilling = params_dict.get("request_type") == "NativeInfillingRequest"
    inferred_original_seed: int | None = None
    origin_found = False

    if is_infilling:
        # Check if an origin counterpart exists on disk
        if target_path and target_path.exists():
            candidates = [
                target_path.parent.parent / "origin" / target_path.name,
                target_path.parent / "origin" / target_path.name,
            ]
            for candidate in candidates:
                if candidate.is_file():
                    try:
                        origin_meta = read_image_parameters(candidate)
                        origin_params = origin_meta.get("parameters", {})
                        if isinstance(origin_params, dict) and origin_params:
                            merged = dict(origin_params)
                            if params_dict.get("prompt"):
                                merged["prompt"] = params_dict["prompt"]
                            if params_dict.get("negative_prompt"):
                                merged["negative_prompt"] = params_dict["negative_prompt"]
                            params_dict = merged
                            notice = (
                                f"检测到局部重绘图 (Infilling)，已自动关联母图 (origin/{candidate.name}) "
                                f"并恢复原始种子 (Seed={origin_params.get('seed')}) 与风格参考 (Vibe Transfer)。"
                            )
                            origin_found = True
                            break
                    except Exception:
                        pass

        if not origin_found:
            seed_m = re.search(r"comm_seed_\d+_(\d+)_\d+", filename)
            if seed_m:
                inferred_original_seed = int(seed_m.group(1))
                notice = (
                    f"检测到局部重绘图 (Infilling)，已从文件名自动识别原始母图种子 (Seed={inferred_original_seed})。"
                )
            else:
                notice = "检测到局部重绘图 (Infilling)，若出图与原图有差异，可能是因为母图底图与局部蒙版未包含在元数据中。"

    prompt = params_dict.get("prompt") or ""
    if not prompt and isinstance(params_dict.get("v4_prompt"), dict):
        caption = params_dict["v4_prompt"].get("caption")
        if isinstance(caption, dict):
            prompt = caption.get("base_caption") or ""

    negative_prompt = params_dict.get("negative_prompt") or ""
    if not negative_prompt and isinstance(params_dict.get("v4_negative_prompt"), dict):
        caption = params_dict["v4_negative_prompt"].get("caption")
        if isinstance(caption, dict):
            negative_prompt = caption.get("base_caption") or ""

    seed = params_dict.get("seed")
    if is_infilling and inferred_original_seed is not None and not origin_found:
        seed = inferred_original_seed
        params_dict["seed"] = inferred_original_seed

    steps = params_dict.get("steps")
    scale = params_dict.get("scale")
    sampler = params_dict.get("sampler")
    raw_model = params_dict.get("model") or png_text.get("Source")
    model = normalize_novelai_model(raw_model) if raw_model else None

    if not prompt and "parameters" in png_text and isinstance(png_text["parameters"], str):
        sd_text = png_text["parameters"]
        parts = sd_text.split("Negative prompt:")
        prompt = parts[0].strip()
        if len(parts) > 1:
            rest = parts[1]
            param_match = re.search(r"Steps:\s*(\d+)", rest)
            if param_match:
                negative_prompt = rest[:param_match.start()].strip()
                steps = int(param_match.group(1))
            else:
                negative_prompt = rest.strip()
            seed_m = re.search(r"Seed:\s*(\d+)", rest)
            if seed_m:
                seed = int(seed_m.group(1))
            scale_m = re.search(r"CFG scale:\s*([\d\.]+)", rest)
            if scale_m:
                scale = float(scale_m.group(1))
            sampler_m = re.search(r"Sampler:\s*([^,\n]+)", rest)
            if sampler_m:
                sampler = sampler_m.group(1).strip()

    return {
        "filename": filename,
        "source_path": str(target_path.resolve()) if target_path and target_path.exists() else None,
        "dimensions": dimensions,
        "prompt": str(prompt or ""),
        "negative_prompt": str(negative_prompt or ""),
        "seed": int(seed) if seed is not None else None,
        "steps": int(steps) if steps is not None else 28,
        "scale": float(scale) if scale is not None else 5.0,
        "sampler": str(sampler) if sampler is not None else None,
        "model": str(model) if model is not None else None,
        "is_infilling": is_infilling,
        "notice": notice,
        "raw_parameters": params_dict or {},
    }


@router.post("/image-meta/inspect")
async def inspect_image_meta(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    temp_file_path: Path | None = None

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            file = form.get("file")
            if not file or not hasattr(file, "read"):
                raise ApiError(
                    code="missing_image_source",
                    message="Missing 'file' field in multipart form upload",
                    status_code=400,
                )
            filename = getattr(file, "filename", "uploaded_image.png") or "uploaded_image.png"
            data = await file.read()
            if not data:
                raise ApiError(
                    code="empty_file",
                    message="Uploaded file is empty",
                    status_code=400,
                )

            cache_dir = Path("output") / ".template_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            clean_name = re.sub(r'[\\/*?:"<>|]', "_", filename)
            target_path = cache_dir / f"{int(time.time() * 1000)}_{clean_name}"
            target_path.write_bytes(data)
        elif "image/" in content_type or "application/octet-stream" in content_type:
            data = await request.body()
            if not data:
                raise ApiError(
                    code="empty_file",
                    message="Uploaded raw image body is empty",
                    status_code=400,
                )
            filename = "uploaded_image.png"
            cache_dir = Path("output") / ".template_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            target_path = cache_dir / f"{int(time.time() * 1000)}_{filename}"
            target_path.write_bytes(data)
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}

            raw_path = body.get("path")
            base64_str = body.get("image_base64") or body.get("base64")

            if base64_str and isinstance(base64_str, str):
                if "," in base64_str:
                    base64_str = base64_str.split(",", 1)[1]
                data = base64.b64decode(base64_str)
                filename = body.get("filename") or "uploaded_image.png"
                cache_dir = Path("output") / ".template_cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                clean_name = re.sub(r'[\\/*?:"<>|]', "_", filename)
                target_path = cache_dir / f"{int(time.time() * 1000)}_{clean_name}"
                target_path.write_bytes(data)
            elif raw_path and isinstance(raw_path, str):
                target_path = Path(raw_path)
                if not target_path.is_absolute():
                    target_path = (Path.cwd() / target_path).resolve()
                if not target_path.exists():
                    raise ApiError(
                        code="file_not_found",
                        message=f"Image file not found: {raw_path}",
                        status_code=404,
                    )
                filename = target_path.name
            else:
                raise ApiError(
                    code="missing_image_source",
                    message="Must provide multipart 'file', JSON 'path', or JSON 'image_base64'",
                    status_code=400,
                )

        try:
            dimensions = read_png_dimensions(target_path)
        except Exception:
            dimensions = {"width": 1024, "height": 1024}

        try:
            meta = read_image_parameters(target_path)
            png_text = meta.get("png_text", {})
            params = meta.get("parameters", {})
            if not isinstance(params, dict):
                params = {}
        except Exception:
            png_text = {}
            params = {}

        return _parse_meta_dict(
            params_dict=params,
            png_text=png_text,
            dimensions=dimensions,
            filename=filename,
            target_path=target_path,
        )

    finally:
        if temp_file_path and temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
