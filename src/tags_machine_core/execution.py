from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from tags_machine_core.clients import NovelAIClient
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
