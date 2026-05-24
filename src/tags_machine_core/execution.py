from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from tags_machine_core.backends import ensure_backend_can_execute
from tags_machine_core.clients import ComfyUIClient, NovelAIClient, SDClient
from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult, RenderRequest
from tags_machine_core.verification import read_image_parameters


def save_generated_images(
    images,
    *,
    output_dir: Path,
    request: RenderRequest,
    default_format: str,
) -> list[GeneratedImage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid4().hex[:8]
    generated_images: list[GeneratedImage] = []
    for index, image in enumerate(images, start=1):
        suffix = Path(image.filename).suffix or f".{default_format}"
        filename = f"{batch_id}_{request.seed or 0}_{index:02d}{suffix}"
        path = output_dir / filename
        path.write_bytes(image.content)
        meta = {"source_filename": image.filename, "index": index}
        for attr in ("subfolder", "image_type", "node_id"):
            value = getattr(image, attr, None)
            if value:
                meta[attr] = value
        generated_images.append(
            GeneratedImage(
                path=path,
                filename=filename,
                meta=meta,
            )
        )
    return generated_images


def collect_png_info(images: list[GeneratedImage]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for image in images:
        record: dict[str, Any] = {
            "filename": image.filename,
            "path": str(image.path),
        }
        try:
            record.update(read_image_parameters(image.path))
        except Exception as exc:
            # 图片可能不是 PNG，或者后端没有写入文本参数；记录错误便于验收回放。
            record["error"] = str(exc)
        records.append(record)
    return {"images": records}


def execute_novelai_generation(
    config: AppConfig,
    request: RenderRequest,
    *,
    output_dir: str | Path | None,
    image_format: str,
) -> GenerationResult:
    access_token = os.environ.get(config.novelai.access_token_env)
    if not access_token:
        raise RuntimeError(
            f"Missing NovelAI token environment variable: {config.novelai.access_token_env}"
        )
    client = NovelAIClient(
        access_token=access_token,
        base_url=config.novelai.base_url,
        timeout=config.novelai.timeout,
        retry=config.novelai.retry,
    )
    images = save_generated_images(
        client.generate_images(request),
        output_dir=Path(output_dir or config.runtime.output_dir),
        request=request,
        default_format=image_format,
    )
    return GenerationResult(
        backend="novelai",
        images=images,
        request_body=client.build_payload(request),
        png_info=collect_png_info(images),
        cache_hit=False,
    )


def execute_render_request(
    config: AppConfig,
    request: RenderRequest,
    *,
    output_dir: str | Path | None,
    image_format: str,
    allow_experimental_backend: bool = False,
    client_id: str | None = None,
    comfyui_no_wait: bool = False,
    comfyui_poll_interval: float = 1.0,
    comfyui_max_wait_seconds: float | None = None,
) -> GenerationResult:
    ensure_backend_can_execute(
        request.backend,
        allow_experimental_backend=allow_experimental_backend,
        entrypoint="execute-render-request",
        experimental_flag="--allow-experimental-backend",
    )

    if request.backend == "novelai":
        return execute_novelai_generation(
            config,
            request,
            output_dir=output_dir,
            image_format=image_format,
        )
    if request.backend == "comfyui":
        return execute_comfyui_generation(
            config,
            request,
            output_dir=output_dir,
            image_format=image_format,
            client_id=client_id,
            no_wait=comfyui_no_wait,
            poll_interval=comfyui_poll_interval,
            max_wait_seconds=comfyui_max_wait_seconds,
        )
    if request.backend == "sd":
        return execute_sd_generation(
            config,
            request,
            output_dir=output_dir,
            image_format=image_format,
        )
    raise ValueError(f"Unsupported backend: {request.backend}")


def execute_comfyui_generation(
    config: AppConfig,
    request: RenderRequest,
    *,
    output_dir: str | Path | None,
    image_format: str,
    client_id: str | None = None,
    no_wait: bool = False,
    poll_interval: float = 1.0,
    max_wait_seconds: float | None = None,
) -> GenerationResult:
    client = ComfyUIClient(
        base_url=config.comfyui.base_url,
        timeout=config.comfyui.timeout,
    )
    if no_wait:
        queued = client.queue_prompt(request, client_id=client_id)
        images: list[GeneratedImage] = []
        comfyui_meta = {"prompt_id": queued.prompt_id, "queue_raw": queued.raw}
    else:
        generated = client.generate_images(
            request,
            client_id=client_id,
            poll_interval=poll_interval,
            max_wait_seconds=max_wait_seconds,
        )
        images = save_generated_images(
            generated.images,
            output_dir=Path(output_dir or config.runtime.output_dir),
            request=request,
            default_format=image_format,
        )
        comfyui_meta = {
            "prompt_id": generated.prompt_id,
            "queue_raw": generated.queue_raw,
            "history": generated.history,
        }
    png_info = collect_png_info(images)
    png_info["comfyui"] = comfyui_meta
    return GenerationResult(
        backend="comfyui",
        images=images,
        request_body=client.build_payload(request, client_id=client_id),
        png_info=png_info,
        cache_hit=False,
    )


def execute_sd_generation(
    config: AppConfig,
    request: RenderRequest,
    *,
    output_dir: str | Path | None,
    image_format: str,
) -> GenerationResult:
    client = SDClient(
        base_url=config.sd.base_url,
        timeout=config.sd.timeout,
    )
    images = save_generated_images(
        client.generate_images(request),
        output_dir=Path(output_dir or config.runtime.output_dir),
        request=request,
        default_format=image_format,
    )
    return GenerationResult(
        backend="sd",
        images=images,
        request_body=client.build_payload(request),
        png_info=collect_png_info(images),
        cache_hit=False,
    )
