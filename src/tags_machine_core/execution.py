from __future__ import annotations

import json
import os
from pathlib import Path
import struct
from typing import Any
from uuid import uuid4
import zlib

from tags_machine_core.backends import ensure_backend_can_execute
from tags_machine_core.clients import ComfyUIClient, NovelAIClient, SDClient
from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult, RenderRequest
from tags_machine_core.verification import read_image_parameters


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CORE_PNG_INFO_KEY = "tags_machine_core"


def save_generated_images(
    images,
    *,
    output_dir: Path,
    request: RenderRequest,
    default_format: str,
) -> list[GeneratedImage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid4().hex[:8]
    png_text = build_core_png_text(request)
    generated_images: list[GeneratedImage] = []
    for index, image in enumerate(images, start=1):
        suffix = Path(image.filename).suffix or f".{default_format}"
        filename = f"{batch_id}_{request.seed or 0}_{index:02d}{suffix}"
        path = output_dir / filename
        path.write_bytes(image.content)
        if path.suffix.lower() == ".png":
            write_png_text_chunks(path, png_text)
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


def build_core_png_text(request: RenderRequest) -> dict[str, str]:
    core_info = {
        "schema": "tags-machine-core.png-info/v1",
        "mode": request.meta.get("mode"),
        "backend": request.backend,
        "model": request.model,
        "composer_type": request.meta.get("composer_type"),
        "composer_version": request.meta.get("composer_version"),
        "prompt_cache_key": request.meta.get("prompt_cache_key"),
        "resolution": request.meta.get("resolution"),
        "split_batch": request.meta.get("split_batch"),
        "nodes": request.meta.get("node_refs") or [],
        "source_nodes": request.meta.get("source_nodes") or [],
        "character_prompts": request.meta.get("character_prompts"),
    }
    result = {
        CORE_PNG_INFO_KEY: json.dumps(_drop_none(core_info), ensure_ascii=False),
    }
    result.update(_legacy_png_text(request))
    return result


def write_png_text_chunks(path: Path, text_chunks: dict[str, str]) -> None:
    if not text_chunks:
        return
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return
    insert_at = _png_iend_offset(data)
    if insert_at is None:
        return
    encoded = b"".join(
        _png_text_chunk(key, value)
        for key, value in text_chunks.items()
        if key and value is not None
    )
    if not encoded:
        return
    path.write_bytes(data[:insert_at] + encoded + data[insert_at:])


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


def _legacy_png_text(request: RenderRequest) -> dict[str, str]:
    result: dict[str, str] = {}
    mode = request.meta.get("mode")
    if isinstance(mode, str) and mode:
        result["mode"] = mode

    artist_ref = _first_node_ref(request, "artist")
    if artist_ref:
        result["artist"] = artist_ref

    artist_path = request.artist_payload.get("path")
    if isinstance(artist_path, str) and artist_path:
        result["artist_path"] = artist_path

    for role in ("character", "action", "background"):
        refs = _node_refs(request, role)
        if refs:
            result[role] = json.dumps(refs, ensure_ascii=False) if len(refs) > 1 else refs[0]
    return result


def _node_refs(request: RenderRequest, role: str) -> list[str]:
    refs = request.meta.get("node_refs")
    if not isinstance(refs, list):
        return []
    result: list[str] = []
    for item in refs:
        if not isinstance(item, dict) or item.get("role") != role:
            continue
        value = item.get("ref") or item.get("id")
        if value:
            result.append(str(value))
    return result


def _first_node_ref(request: RenderRequest, role: str) -> str | None:
    refs = _node_refs(request, role)
    return refs[0] if refs else None


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(item)
            for key, item in value.items()
            if item is not None and item != [] and item != {}
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _png_iend_offset(data: bytes) -> int | None:
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        next_offset = offset + 12 + length
        if chunk_type == b"IEND":
            return offset
        offset = next_offset
    return None


def _png_text_chunk(key: str, value: str) -> bytes:
    raw = key.encode("latin-1") + b"\x00" + str(value).encode("utf-8")
    return _png_chunk(b"tEXt", raw)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


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
        retry_interval=config.novelai.retry_interval,
    )
    output_path = Path(output_dir or config.runtime.output_dir)
    requests = split_novelai_samples(request)
    if len(requests) == 1:
        effective_request = requests[0]
        images = save_generated_images(
            client.generate_images(effective_request),
            output_dir=output_path,
            request=effective_request,
            default_format=image_format,
        )
        return GenerationResult(
            backend="novelai",
            images=images,
            request_body=client.build_payload(effective_request),
            png_info=collect_png_info(images),
            cache_hit=False,
        )

    images: list[GeneratedImage] = []
    png_records: list[dict[str, Any]] = []
    request_bodies: list[dict[str, Any]] = []
    for index, split_request in enumerate(requests):
        generated = save_generated_images(
            client.generate_images(split_request),
            output_dir=output_path,
            request=split_request,
            default_format=image_format,
        )
        images.extend(
            image.model_copy(
                update={
                    "meta": {
                        **image.meta,
                        "split_request_index": index,
                    }
                }
            )
            for image in generated
        )
        request_bodies.append(client.build_payload(split_request))
        png_info = collect_png_info(generated)
        for record in png_info.get("images", []):
            if isinstance(record, dict):
                record["split_request_index"] = index
                png_records.append(record)

    return GenerationResult(
        backend="novelai",
        images=images,
        request_body={
            "split_batch": True,
            "reason": "force_n_samples_1",
            "requests": request_bodies,
        },
        png_info={"images": png_records},
        cache_hit=False,
    )


def split_novelai_samples(request: RenderRequest) -> list[RenderRequest]:
    """把 NovelAI 批量请求拆成多次单图请求，避免向 API 发送 n_samples > 1。"""
    count = _request_n_samples(request)
    if count <= 1:
        return [request]

    return [_single_novelai_sample_request(request, index, count) for index in range(count)]


def _request_n_samples(request: RenderRequest) -> int:
    value = request.params.get("n_samples", 1)
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"NovelAI parameter n_samples must be an integer, got {value!r}") from None
    if count < 1:
        raise ValueError(f"NovelAI parameter n_samples must be at least 1, got {value!r}")
    return count


def _single_novelai_sample_request(
    request: RenderRequest,
    index: int,
    count: int,
) -> RenderRequest:
    params = dict(request.params)
    seed = _offset_novelai_seed(params.get("seed", request.seed), index)
    params["n_samples"] = 1
    if seed is not None:
        params["seed"] = seed

    meta = dict(request.meta)
    meta["split_batch"] = {
        "index": index,
        "count": count,
        "reason": "force_n_samples_1",
    }
    return request.model_copy(
        deep=True,
        update={
            "seed": seed if seed is not None else request.seed,
            "params": params,
            "meta": meta,
        },
    )


def _offset_novelai_seed(seed: Any, index: int) -> int | None:
    if seed is None:
        return None
    try:
        value = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"NovelAI parameter seed must be an integer, got {seed!r}") from None
    value += index
    if value > 4294967295:
        raise ValueError(f"NovelAI parameter seed must be between 0 and 4294967295, got {value!r}")
    return value


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
