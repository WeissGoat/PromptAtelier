from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tags_machine_core.clients.novelai import model_from_source_label, normalize_novelai_model, source_label_hash
from tags_machine_core.verification.image_params import read_image_parameters, read_png_dimensions


IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
# 解析规则变了就加一：旧记录即使文件没变也会重新读取。2：按 Source 的模型哈希认 Curated / Full。
RECORD_VERSION = 2
_POST_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)_?(.*)$")


class PostInfo(BaseModel):
    dir_name: str
    date: str | None = None
    post_id: str | None = None
    title: str | None = None


class CharCaption(BaseModel):
    positive: str = ""
    negative: str = ""
    centers: list[dict[str, float]] = Field(default_factory=list)


class VibeInfo(BaseModel):
    count: int = 0
    hashes: list[str] = Field(default_factory=list)
    strengths: list[float] = Field(default_factory=list)
    information_extracted: list[float] = Field(default_factory=list)


class ImageRecord(BaseModel):
    """一张源图的元数据摘要；完整原始参数按需另读。"""

    id: str
    path: str
    rel_path: str
    size_bytes: int
    mtime_ns: int
    post: PostInfo | None = None
    width: int | None = None
    height: int | None = None
    has_metadata: bool = False
    source_label: str | None = None
    model: str | None = None
    request_type: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    char_captions: list[CharCaption] = Field(default_factory=list)
    seed: int | None = None
    steps: int | None = None
    scale: float | None = None
    cfg_rescale: float | None = None
    sampler: str | None = None
    noise_schedule: str | None = None
    vibe: VibeInfo = Field(default_factory=VibeInfo)
    flags: list[str] = Field(default_factory=list)
    record_version: int = 0


def image_id_for(rel_path: str) -> str:
    return hashlib.sha1(rel_path.replace("\\", "/").encode("utf-8")).hexdigest()[:12]


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def parse_post_dir(name: str) -> PostInfo:
    match = _POST_DIR_RE.match(name)
    if not match:
        return PostInfo(dir_name=name)
    return PostInfo(
        dir_name=name,
        date=match.group(1),
        post_id=match.group(2),
        title=match.group(3) or None,
    )


def read_source_parameters(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (NovelAI 参数, PNG 文本块)；读不到时返回两个空字典。"""
    if path.suffix.lower() != ".png":
        return {}, {}
    try:
        meta = read_image_parameters(path)
    except (OSError, ValueError):
        return {}, {}
    params = meta.get("parameters")
    png_text = meta.get("png_text")
    return (params if isinstance(params, dict) else {}), (png_text if isinstance(png_text, dict) else {})


def build_image_record(path: Path, *, base: Path) -> ImageRecord:
    stat = path.stat()
    rel_path = _relative(path, base)
    params, png_text = read_source_parameters(path)
    record = ImageRecord(
        id=image_id_for(rel_path),
        path=str(path),
        rel_path=rel_path,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        post=parse_post_dir(path.parent.name) if path.parent != base else None,
        record_version=RECORD_VERSION,
    )
    _fill_dimensions(record, path, params)
    if not params:
        record.flags.append("no_metadata")
        return record

    record.has_metadata = True
    source_label = png_text.get("Source")
    record.source_label = str(source_label) if source_label else None
    # Source 是 NovelAI 自己写的；Comment 里的 model 可能是第三方客户端另记的，排在后面。
    hashed_model = model_from_source_label(record.source_label)
    raw_model = params.get("model") or source_label
    record.model = hashed_model or (normalize_novelai_model(str(raw_model)) if raw_model else None)
    record.request_type = _optional_str(params.get("request_type"))
    record.prompt, record.char_captions = _captions(params, "v4_prompt", params.get("prompt"))
    record.negative_prompt, negative_chars = _captions(
        params, "v4_negative_prompt", params.get("uc") or params.get("negative_prompt")
    )
    for index, caption in enumerate(negative_chars):
        if index < len(record.char_captions):
            record.char_captions[index].negative = caption.positive
        else:
            record.char_captions.append(CharCaption(negative=caption.positive))
    record.seed = _optional_int(params.get("seed"))
    record.steps = _optional_int(params.get("steps"))
    record.scale = _optional_float(params.get("scale"))
    record.cfg_rescale = _optional_float(params.get("cfg_rescale"))
    record.sampler = _optional_str(params.get("sampler"))
    record.noise_schedule = _optional_str(params.get("noise_schedule"))
    record.vibe = _vibe(params)
    record.flags.extend(_flags(params, record))
    if not hashed_model and not params.get("model") and source_label_hash(record.source_label):
        record.flags.append("model_unverified")
    return record


def _relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _fill_dimensions(record: ImageRecord, path: Path, params: dict[str, Any]) -> None:
    if path.suffix.lower() == ".png":
        try:
            dims = read_png_dimensions(path)
            record.width, record.height = dims["width"], dims["height"]
            return
        except (OSError, ValueError, KeyError):
            pass
    record.width = _optional_int(params.get("width"))
    record.height = _optional_int(params.get("height"))


def _captions(params: dict[str, Any], key: str, fallback: Any) -> tuple[str, list[CharCaption]]:
    block = params.get(key)
    caption = block.get("caption") if isinstance(block, dict) else None
    if isinstance(caption, dict):
        base = str(caption.get("base_caption") or "")
        chars: list[CharCaption] = []
        for item in caption.get("char_captions") or []:
            if not isinstance(item, dict):
                continue
            centers = [c for c in item.get("centers") or [] if isinstance(c, dict)]
            chars.append(CharCaption(positive=str(item.get("char_caption") or ""), centers=centers))
        return base or str(fallback or ""), chars
    return str(fallback or ""), []


def _vibe(params: dict[str, Any]) -> VibeInfo:
    images = [str(item) for item in params.get("reference_image_multiple") or [] if item]
    strengths = _float_list(params.get("reference_strength_multiple"))
    extracted = _float_list(params.get("reference_information_extracted_multiple"))
    return VibeInfo(
        count=len(images),
        hashes=[short_hash(image) for image in images],
        strengths=strengths,
        information_extracted=extracted,
    )


def _flags(params: dict[str, Any], record: ImageRecord) -> list[str]:
    flags: list[str] = []
    request_type = (record.request_type or "").lower()
    if "infill" in request_type or params.get("mask"):
        flags.append("inpaint")
    elif "img2img" in request_type or params.get("image"):
        flags.append("img2img")
    if params.get("add_original_image") and "inpaint" in flags:
        flags.append("add_original")
    if record.vibe.count == 0 and record.vibe.strengths:
        flags.append("vibe_missing")
    if params.get("director_reference_images") or params.get("director_reference_strengths"):
        flags.append("director_ref")
    return flags


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        number = _optional_float(item)
        if number is not None:
            result.append(number)
    return result


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
