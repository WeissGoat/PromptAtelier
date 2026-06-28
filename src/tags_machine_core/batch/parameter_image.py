from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tags_machine_core.contracts import GenerationResult
from tags_machine_core.json_tools import to_jsonable

from .models import BatchTask


CANVAS_WIDTH = 1400
CANVAS_HEIGHT = 1500
MARGIN = 36
GAP = 20
BOX_RADIUS = 10


def write_parameter_details_image(
    path: str | Path,
    *,
    task: BatchTask,
    prompt_bundle: Any,
    render_request: Any,
    generation_result: GenerationResult,
) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    from PIL.PngImagePlugin import PngInfo

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fonts = {
        "title": _load_font(ImageFont, size=42),
        "section": _load_font(ImageFont, size=31),
        "body": _load_font(ImageFont, size=24),
        "small": _load_font(ImageFont, size=21),
    }
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), (248, 249, 251))
    draw = ImageDraw.Draw(image)

    bundle = _as_dict(prompt_bundle)
    request = _as_dict(render_request)
    result = _as_dict(generation_result)
    params = _display_parameters(request=request, result=result)

    _draw_header(draw, task=task, request=request, params=params, fonts=fonts)
    y = 162

    _draw_box(
        draw,
        x=MARGIN,
        y=y,
        width=CANVAS_WIDTH - MARGIN * 2,
        height=310,
        title="Render",
        lines=_render_lines(task=task, request=request, params=params),
        fonts=fonts,
    )

    y += 310 + GAP
    _draw_box(
        draw,
        x=MARGIN,
        y=y,
        width=CANVAS_WIDTH - MARGIN * 2,
        height=400,
        title="Prompt",
        lines=[_prompt_positive(bundle=bundle, request=request, params=params)],
        fonts=fonts,
        preserve_line_breaks=False,
    )

    y += 400 + GAP
    _draw_box(
        draw,
        x=MARGIN,
        y=y,
        width=CANVAS_WIDTH - MARGIN * 2,
        height=200,
        title="Negative Prompt",
        lines=[_prompt_negative(bundle=bundle, request=request, params=params)],
        fonts=fonts,
        preserve_line_breaks=False,
    )

    y += 200 + GAP
    _draw_box(
        draw,
        x=MARGIN,
        y=y,
        width=CANVAS_WIDTH - MARGIN * 2,
        height=270,
        title="NovelAI Parameters",
        lines=_parameter_lines(params=params, request=request),
        fonts=fonts,
    )

    footer = (
        "This image is a compact summary. Full data is in prompt_bundle.json, "
        "render_request.json, generation_result.json, and png_params.json."
    )
    draw.text((MARGIN, CANVAS_HEIGHT - 46), footer, fill=(96, 104, 116), font=fonts["small"])

    png_info = PngInfo()
    png_info.add_text("Software", "tags_machine_core batch parameter details")
    png_info.add_text("Task ID", task.id)
    png_info.add_itxt("Render Request", json.dumps(request, ensure_ascii=False))
    png_info.add_itxt("Generation Result", json.dumps(result, ensure_ascii=False))
    image.save(target, "PNG", pnginfo=png_info)
    return target


def _draw_header(draw: Any, *, task: BatchTask, request: dict[str, Any], params: dict[str, Any], fonts: dict[str, Any]) -> None:
    title = f"Batch Parameter Details"
    draw.text((MARGIN, 28), title, fill=(25, 29, 35), font=fonts["title"])
    subtitle = f"task_id={task.id}"
    draw.text((MARGIN, 88), subtitle, fill=(57, 65, 78), font=fonts["body"])
    badges = [
        f"artist={task.render.artist or '-'}",
        f"model={request.get('model') or params.get('model') or task.render.model or '-'}",
        f"seed={_short_value(params.get('seed') or task.render.seed or '-')}",
    ]
    x = MARGIN
    for badge in badges:
        x = _draw_badge(draw, x=x, y=124, text=badge, font=fonts["small"])


def _draw_badge(draw: Any, *, x: int, y: int, text: str, font: Any) -> int:
    padding_x = 12
    padding_y = 6
    width = int(draw.textlength(text, font=font)) + padding_x * 2
    height = 38
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=8,
        fill=(230, 237, 247),
        outline=(206, 217, 233),
    )
    draw.text((x + padding_x, y + padding_y), text, fill=(48, 72, 108), font=font)
    return x + width + 10


def _draw_box(
    draw: Any,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    lines: list[str],
    fonts: dict[str, Any],
    preserve_line_breaks: bool = True,
) -> None:
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=BOX_RADIUS,
        fill=(255, 255, 255),
        outline=(218, 224, 232),
    )
    draw.text((x + 18, y + 14), title, fill=(42, 85, 135), font=fonts["section"])
    content_top = y + 56
    content_bottom = y + height - 18
    line_height = _line_height(draw, fonts["body"])
    rendered = _wrapped_lines(
        draw,
        lines,
        max_width=width - 36,
        font=fonts["body"],
        preserve_line_breaks=preserve_line_breaks,
    )
    max_lines = max(1, (content_bottom - content_top) // line_height)
    clipped = len(rendered) > max_lines
    if clipped:
        rendered = rendered[: max_lines - 1] + ["...truncated; see JSON artifacts for full data"]
    cursor = content_top
    for line in rendered:
        draw.text((x + 18, cursor), line, fill=(42, 45, 52), font=fonts["body"])
        cursor += line_height


def _render_lines(*, task: BatchTask, request: dict[str, Any], params: dict[str, Any]) -> list[str]:
    size = request.get("size") if isinstance(request.get("size"), dict) else {}
    width = params.get("width") or size.get("width") or task.render.width or "-"
    height = params.get("height") or size.get("height") or task.render.height or "-"
    sample_line = f"task_nt={task.render.nt}, png_n_samples={params.get('n_samples', '-')}"
    if params.get("_actual_image_count"):
        sample_line += f", actual_png_images={params['_actual_image_count']}"
    lines = [
        f"backend: {task.render.backend}",
        f"artist: {task.render.artist or '-'}",
        f"model: {request.get('model') or params.get('model') or task.render.model or '-'}",
        f"resolution: {task.render.resolution}",
        f"size: {width} x {height}",
        f"samples: {sample_line}",
    ]
    return lines


def _parameter_lines(*, params: dict[str, Any], request: dict[str, Any]) -> list[str]:
    keys = [
        "seed",
        "extra_noise_seed",
        "steps",
        "scale",
        "cfg_rescale",
        "sampler",
        "noise_schedule",
        "ucPreset",
        "qualityToggle",
        "sm",
        "sm_dyn",
        "dynamic_thresholding",
        "characterPrompts",
        "reference_image_multiple",
        "reference_strength_multiple",
        "director_reference_images",
    ]
    lines = []
    if request.get("action"):
        lines.append(f"action: {request.get('action')}")
    for key in keys:
        if key not in params:
            continue
        value = params[key]
        value = _display_value(value, limit=220)
        lines.append(f"{key}: {value}")
    return lines or ["-"]


def _prompt_positive(*, bundle: dict[str, Any], request: dict[str, Any], params: dict[str, Any]) -> str:
    if params.get("prompt"):
        return str(params.get("prompt"))
    prompt = bundle.get("prompt")
    if request.get("prompt"):
        return str(request.get("prompt"))
    if request.get("input"):
        return str(request.get("input"))
    if isinstance(prompt, dict) and prompt.get("positive"):
        return str(prompt.get("positive"))
    return "-"


def _prompt_negative(*, bundle: dict[str, Any], request: dict[str, Any], params: dict[str, Any]) -> str:
    if params.get("negative_prompt"):
        return str(params.get("negative_prompt"))
    if params.get("uc"):
        return str(params.get("uc"))
    prompt = bundle.get("prompt")
    if request.get("negative_prompt"):
        return str(request.get("negative_prompt"))
    if isinstance(prompt, dict) and prompt.get("negative"):
        return str(prompt.get("negative"))
    return "-"


def _display_parameters(*, request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    png_parameters = _png_parameter_sets(result)
    if png_parameters:
        merged = _merge_parameter_sets(png_parameters)
        merged["_actual_image_count"] = len(png_parameters)
        return merged

    request_body = result.get("request_body")
    if isinstance(request_body, dict):
        body_params = request_body.get("parameters")
        if isinstance(body_params, dict):
            return body_params
    request_params = request.get("params")
    if isinstance(request_params, dict):
        return request_params
    return {}


def _png_parameter_sets(result: dict[str, Any]) -> list[dict[str, Any]]:
    png_info = result.get("png_info")
    if not isinstance(png_info, dict):
        return []
    images = png_info.get("images")
    if not isinstance(images, list):
        return []
    parameter_sets: list[dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        parameters = image.get("parameters")
        if isinstance(parameters, dict) and parameters:
            parameter_sets.append(parameters)
    return parameter_sets


def _merge_parameter_sets(parameter_sets: list[dict[str, Any]]) -> dict[str, Any]:
    if not parameter_sets:
        return {}
    keys: list[str] = []
    for parameters in parameter_sets:
        for key in parameters:
            if key not in keys:
                keys.append(key)

    merged: dict[str, Any] = {}
    for key in keys:
        values = [parameters.get(key) for parameters in parameter_sets if key in parameters]
        unique = _unique_values(values)
        merged[key] = unique[0] if len(unique) == 1 else unique
    return merged


def _unique_values(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    data = to_jsonable(value)
    return data if isinstance(data, dict) else {}


def _compact_json(value: Any, *, limit: int) -> str:
    text = json.dumps(to_jsonable(value), ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(chars={len(text)})"


def _display_value(value: Any, *, limit: int) -> str:
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        text = ", ".join(str(item) for item in value)
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...(items={len(value)})"
    if isinstance(value, (list, dict)):
        return _compact_json(value, limit=limit)
    return str(value)


def _short_value(value: Any, *, limit: int = 48) -> str:
    text = _display_value(value, limit=limit)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _wrapped_lines(
    draw: Any,
    lines: list[str],
    *,
    max_width: int,
    font: Any,
    preserve_line_breaks: bool,
) -> list[str]:
    result: list[str] = []
    source_lines = lines if preserve_line_breaks else [" ".join(line.strip() for line in lines)]
    for source in source_lines:
        text = str(source)
        if not text:
            result.append("")
            continue
        result.extend(_wrap_line(draw, text, max_width=max_width, font=font))
    return result


def _wrap_line(draw: Any, text: str, *, max_width: int, font: Any) -> list[str]:
    chunks = _split_wrap_chunks(text)
    lines: list[str] = []
    current = ""
    for chunk in chunks:
        candidate = current + chunk
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current.rstrip())
            current = chunk.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def _split_wrap_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in {",", " ", "/", "\\", ":", ";"}:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def _line_height(draw: Any, font: Any) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return max(24, bbox[3] - bbox[1] + 8)


def _load_font(image_font: Any, *, size: int) -> Any:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return image_font.truetype(candidate, size=size)
        except OSError:
            continue
    return image_font.load_default()
