from __future__ import annotations

import io
import json
import os
from pathlib import Path
import struct
import time
from typing import Any
from uuid import uuid4
import zlib

from PIL import Image

from tags_machine_core.backends import ensure_backend_can_execute
from tags_machine_core.clients import (
    ComfyUIClient,
    GatewayNovelAIRawClient,
    NovelAIClient,
    NovelAIImage,
    SDClient,
)
from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult, RenderRequest
from tags_machine_core.logging_config import get_logger
from tags_machine_core.renderers.comfyui_workflow import normalize_binding_paths
from tags_machine_core.verification import read_image_parameters


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CORE_PNG_INFO_KEY = "tags_machine_core"
logger = get_logger(__name__)
_last_novelai_request_at = 0.0


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
        logger.info("saved generated image path=%s", path)
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
    access_token = config.novelai.access_token or os.environ.get(config.novelai.access_token_env)
    if not access_token:
        raise RuntimeError(
            "Missing NovelAI token: set novelai.access_token in config or "
            f"environment variable {config.novelai.access_token_env}"
        )
    client = _novelai_executor_client(config, access_token)
    output_path = Path(output_dir or config.runtime.output_dir)
    requests = split_novelai_samples(request)
    logger.info(
        "execute_novelai_generation start model=%s split_requests=%s output_dir=%s",
        request.model,
        len(requests),
        output_path,
    )
    if len(requests) == 1:
        effective_request = requests[0]
        images = save_generated_images(
            _generate_novelai_images(
                client,
                effective_request,
                request_interval=config.novelai.request_interval,
            ),
            output_dir=output_path,
            request=effective_request,
            default_format=image_format,
        )
        png_info = collect_png_info(images)
        _attach_gateway_retry_records(png_info, client)
        return GenerationResult(
            backend="novelai",
            images=images,
            request_body=client.build_payload(effective_request),
            png_info=png_info,
            cache_hit=False,
        )

    images: list[GeneratedImage] = []
    png_records: list[dict[str, Any]] = []
    request_bodies: list[dict[str, Any]] = []
    gateway_records: list[dict[str, Any]] = []
    for index, split_request in enumerate(requests):
        generated = save_generated_images(
            _generate_novelai_images(
                client,
                split_request,
                request_interval=config.novelai.request_interval,
            ),
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
        _attach_gateway_retry_records(png_info, client, split_request_index=index)
        for record in png_info.get("images", []):
            if isinstance(record, dict):
                record["split_request_index"] = index
                png_records.append(record)
        gateway_records.extend(png_info.get("ai_image_gateway", []))

    return GenerationResult(
        backend="novelai",
        images=images,
        request_body={
            "split_batch": True,
            "reason": "force_n_samples_1",
            "requests": request_bodies,
        },
        png_info={
            key: value
            for key, value in {
                "images": png_records,
                "ai_image_gateway": gateway_records,
            }.items()
            if value
        },
        cache_hit=False,
    )


def _novelai_executor_client(config: AppConfig, access_token: str):
    executor = str(config.generation.executor or "core_novelai_client")
    kwargs = {
        "access_token": access_token,
        "base_url": config.novelai.base_url,
        "timeout": config.novelai.timeout,
        "retry": config.novelai.retry,
        "retry_interval": config.novelai.retry_interval,
    }
    if executor == "core_novelai_client":
        return NovelAIClient(**kwargs)
    if executor == "ai_image_gateway_raw":
        return GatewayNovelAIRawClient(**kwargs)
    raise ValueError(
        "Unsupported generation.executor for NovelAI: "
        f"{executor!r}. Expected 'core_novelai_client' or 'ai_image_gateway_raw'."
    )


def _attach_gateway_retry_records(
    png_info: dict[str, Any],
    client: Any,
    *,
    split_request_index: int | None = None,
) -> None:
    retry_records = getattr(client, "last_retry_records", None)
    if not retry_records:
        return
    record: dict[str, Any] = {"retry_records": retry_records}
    if split_request_index is not None:
        record["split_request_index"] = split_request_index
    png_info.setdefault("ai_image_gateway", []).append(record)


def execute_mock_generation(
    request: RenderRequest,
    *,
    output_dir: str | Path | None,
    image_format: str,
) -> GenerationResult:
    output_path = Path(output_dir or ".")
    default_format = image_format or "png"
    requests = split_novelai_samples(request) if request.backend == "novelai" else [request]
    if len(requests) == 1:
        effective_request = requests[0]
        request_body = _mock_request_body(effective_request)
        images = save_generated_images(
            [
                NovelAIImage(
                    filename=f"mock.{default_format}",
                    content=_mock_png_bytes(effective_request),
                )
            ],
            output_dir=output_path,
            request=effective_request,
            default_format=default_format,
        )
        _write_mock_png_parameters(images, request_body)
        png_info = collect_png_info(images)
        png_info["mock"] = {
            "enabled": True,
            "reason": "batch execution_mode=mock",
        }
        return GenerationResult(
            backend=request.backend,
            images=images,
            request_body=request_body,
            png_info=png_info,
            cache_hit=False,
        )

    images: list[GeneratedImage] = []
    png_records: list[dict[str, Any]] = []
    request_bodies: list[dict[str, Any]] = []
    gateway_records: list[dict[str, Any]] = []
    for index, split_request in enumerate(requests):
        request_body = _mock_request_body(split_request)
        generated = save_generated_images(
            [
                NovelAIImage(
                    filename=f"mock.{default_format}",
                    content=_mock_png_bytes(split_request),
                )
            ],
            output_dir=output_path,
            request=split_request,
            default_format=default_format,
        )
        _write_mock_png_parameters(generated, request_body)
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
        request_bodies.append(request_body)
        png_info = collect_png_info(generated)
        for record in png_info.get("images", []):
            if isinstance(record, dict):
                record["split_request_index"] = index
                png_records.append(record)

    return GenerationResult(
        backend=request.backend,
        images=images,
        request_body={
            "split_batch": True,
            "reason": "force_n_samples_1",
            "requests": request_bodies,
        },
        png_info={
            "images": png_records,
            "mock": {
                "enabled": True,
                "reason": "batch execution_mode=mock",
                "split_batch": True,
            },
        },
        cache_hit=False,
    )


def _mock_request_body(request: RenderRequest) -> dict[str, Any]:
    if request.backend == "novelai":
        return NovelAIClient(access_token="mock").build_payload(request)
    return {
        "backend": request.backend,
        "model": request.model,
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "seed": request.seed,
        "size": request.size.model_dump(mode="json"),
        "params": request.params,
    }


def _write_mock_png_parameters(images: list[GeneratedImage], request_body: dict[str, Any]) -> None:
    parameters = _mock_png_parameters(request_body)
    text = json.dumps(parameters, ensure_ascii=False)
    for image in images:
        write_png_text_chunks(Path(image.path), {"Comment": text})


def _mock_png_parameters(request_body: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(request_body.get("parameters") or {})
    if request_body.get("input"):
        parameters.setdefault("prompt", request_body["input"])
    if request_body.get("model"):
        parameters.setdefault("model", request_body["model"])
    if request_body.get("action"):
        parameters.setdefault("action", request_body["action"])
    negative = parameters.get("negative_prompt")
    if negative is not None:
        parameters.setdefault("uc", negative)
    return parameters


def _mock_png_bytes(request: RenderRequest) -> bytes:
    width = max(32, min(256, int(request.size.width or 1024) // 8))
    height = max(32, min(256, int(request.size.height or 1024) // 8))
    image = Image.new("RGB", (width, height), color=(36, 40, 48))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _generate_novelai_images(
    client: NovelAIClient,
    request: RenderRequest,
    *,
    request_interval: float,
):
    _wait_for_novelai_request_slot(request_interval)
    return client.generate_images(request)


def _wait_for_novelai_request_slot(request_interval: float) -> None:
    global _last_novelai_request_at
    interval = max(0.0, float(request_interval or 0.0))
    if interval <= 0:
        _last_novelai_request_at = time.monotonic()
        return

    now = time.monotonic()
    wait_seconds = interval - (now - _last_novelai_request_at)
    if wait_seconds > 0:
        logger.info("NovelAI request throttle sleep seconds=%.2f", wait_seconds)
        time.sleep(wait_seconds)
    _last_novelai_request_at = time.monotonic()


def split_novelai_samples(request: RenderRequest) -> list[RenderRequest]:
    """把 NovelAI 批量请求拆成多次单图请求，避免向 API 发送 n_samples > 1。"""
    count = _request_n_samples(request)
    if count <= 1:
        return [request]

    logger.info("split NovelAI n_samples into single requests count=%s", count)
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
    comfyui_poll_interval: float | None = None,
    comfyui_max_wait_seconds: float | None = None,
) -> GenerationResult:
    ensure_backend_can_execute(
        request.backend,
        allow_experimental_backend=allow_experimental_backend,
        entrypoint="execute-render-request",
        experimental_flag="--allow-experimental-backend",
    )
    logger.info("execute_render_request backend=%s model=%s", request.backend, request.model)

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
    poll_interval: float | None = None,
    max_wait_seconds: float | None = None,
) -> GenerationResult:
    client = ComfyUIClient(
        base_url=config.comfyui.base_url,
        timeout=config.comfyui.timeout,
        retry=config.comfyui.retry,
        retry_interval=config.comfyui.retry_interval,
    )
    output_path = Path(output_dir or config.runtime.output_dir)
    requests = split_comfyui_samples(request)
    effective_poll_interval = (
        config.comfyui.poll_interval if poll_interval is None else poll_interval
    )
    effective_max_wait = (
        config.comfyui.max_wait_seconds if max_wait_seconds is None else max_wait_seconds
    )
    logger.info(
        "execute_comfyui_generation start workflow=%s split_requests=%s output_dir=%s",
        request.params.get("workflow"),
        len(requests),
        output_path,
    )
    if len(requests) > 1:
        return _execute_split_comfyui_generation(
            client=client,
            requests=requests,
            output_dir=output_path,
            image_format=image_format,
            client_id=client_id,
            no_wait=no_wait,
            poll_interval=effective_poll_interval,
            max_wait_seconds=effective_max_wait,
        )

    effective_request = requests[0]
    if no_wait:
        queued = client.queue_prompt(effective_request, client_id=client_id)
        images: list[GeneratedImage] = []
        comfyui_meta = {"prompt_id": queued.prompt_id, "queue_raw": queued.raw}
    else:
        generated = client.generate_images(
            effective_request,
            client_id=client_id,
            poll_interval=effective_poll_interval,
            max_wait_seconds=effective_max_wait,
        )
        images = save_generated_images(
            generated.images,
            output_dir=output_path,
            request=effective_request,
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
        request_body=client.build_payload(effective_request, client_id=client_id),
        png_info=png_info,
        cache_hit=False,
    )


def _execute_split_comfyui_generation(
    *,
    client: ComfyUIClient,
    requests: list[RenderRequest],
    output_dir: Path,
    image_format: str,
    client_id: str | None,
    no_wait: bool,
    poll_interval: float,
    max_wait_seconds: float | None,
) -> GenerationResult:
    images: list[GeneratedImage] = []
    png_records: list[dict[str, Any]] = []
    request_bodies: list[dict[str, Any]] = []
    prompt_records: list[dict[str, Any]] = []

    for index, split_request in enumerate(requests):
        if no_wait:
            queued = client.queue_prompt(split_request, client_id=client_id)
            request_bodies.append(client.build_payload(split_request, client_id=client_id))
            prompt_records.append({"split_request_index": index, "prompt_id": queued.prompt_id})
            continue

        generated = client.generate_images(
            split_request,
            client_id=client_id,
            poll_interval=poll_interval,
            max_wait_seconds=max_wait_seconds,
        )
        generated_images = save_generated_images(
            generated.images,
            output_dir=output_dir,
            request=split_request,
            default_format=image_format,
        )
        images.extend(
            image.model_copy(
                update={
                    "meta": {
                        **image.meta,
                        "split_request_index": index,
                        "prompt_id": generated.prompt_id,
                    }
                }
            )
            for image in generated_images
        )
        request_bodies.append(client.build_payload(split_request, client_id=client_id))
        prompt_records.append(
            {
                "split_request_index": index,
                "prompt_id": generated.prompt_id,
                "queue_raw": generated.queue_raw,
                "history": generated.history,
            }
        )
        png_info = collect_png_info(generated_images)
        for record in png_info.get("images", []):
            if isinstance(record, dict):
                record["split_request_index"] = index
                record["prompt_id"] = generated.prompt_id
                png_records.append(record)

    return GenerationResult(
        backend="comfyui",
        images=images,
        request_body={
            "split_batch": True,
            "reason": "force_n_samples_1",
            "requests": request_bodies,
        },
        png_info={
            "images": png_records,
            "comfyui": {
                "split_batch": True,
                "requests": prompt_records,
            },
        },
        cache_hit=False,
    )


def split_comfyui_samples(request: RenderRequest) -> list[RenderRequest]:
    count = _request_n_samples_for_backend(request, backend="ComfyUI")
    if count <= 1:
        return [request]

    logger.info("split ComfyUI n_samples into single requests count=%s", count)
    return [_single_comfyui_sample_request(request, index, count) for index in range(count)]


def _single_comfyui_sample_request(
    request: RenderRequest,
    index: int,
    count: int,
) -> RenderRequest:
    params = dict(request.params)
    seed = _offset_comfyui_seed(params.get("seed", request.seed), index)
    params["n_samples"] = 1
    if seed is not None:
        params["seed"] = seed
        params["node_overrides"] = _comfyui_seed_overrides(params, seed)

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


def _request_n_samples_for_backend(request: RenderRequest, *, backend: str) -> int:
    value = request.params.get("n_samples", 1)
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{backend} parameter n_samples must be an integer, got {value!r}") from None
    if count < 1:
        raise ValueError(f"{backend} parameter n_samples must be at least 1, got {value!r}")
    return count


def _offset_comfyui_seed(seed: Any, index: int) -> int | None:
    if seed is None:
        return None
    try:
        value = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"ComfyUI parameter seed must be an integer, got {seed!r}") from None
    if value < 0:
        return value
    return value + index


def _comfyui_seed_overrides(params: dict[str, Any], seed: int) -> dict[str, Any]:
    overrides = dict(params.get("node_overrides") or {})
    comfyui_inputs = params.get("comfyui_inputs")
    if not isinstance(comfyui_inputs, dict):
        return overrides
    inputs = comfyui_inputs.get("inputs")
    if not isinstance(inputs, dict) or "seed" not in inputs:
        return overrides
    for path in normalize_binding_paths(inputs["seed"], source="comfyui_inputs.inputs.seed"):
        overrides[path] = seed
    return overrides


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
