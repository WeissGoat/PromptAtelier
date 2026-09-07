from __future__ import annotations

import base64
import os
import re
import tempfile
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
) -> dict[str, Any]:
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
        "dimensions": dimensions,
        "prompt": str(prompt or ""),
        "negative_prompt": str(negative_prompt or ""),
        "seed": int(seed) if seed is not None else None,
        "steps": int(steps) if steps is not None else 28,
        "scale": float(scale) if scale is not None else 5.0,
        "sampler": str(sampler) if sampler is not None else None,
        "model": str(model) if model is not None else None,
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

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(data)
                temp_file_path = Path(tmp.name)
            target_path = temp_file_path
        elif "image/" in content_type or "application/octet-stream" in content_type:
            data = await request.body()
            if not data:
                raise ApiError(
                    code="empty_file",
                    message="Uploaded raw image body is empty",
                    status_code=400,
                )
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(data)
                temp_file_path = Path(tmp.name)
            target_path = temp_file_path
            filename = "uploaded_image.png"
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
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(data)
                    temp_file_path = Path(tmp.name)
                target_path = temp_file_path
                filename = body.get("filename") or "uploaded_image.png"
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
        )

    finally:
        if temp_file_path and temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
