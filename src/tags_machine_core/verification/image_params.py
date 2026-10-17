from __future__ import annotations

import gzip
import json
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 藏在像素最低位里的元数据（NovelAI 官网出图、SD 的 stealth pnginfo 扩展）：
# 开头是 15 字节的标记，再是 32 位的数据位数，然后是数据；comp 的数据用 gzip 压过。
# alpha 版每个像素取 A 的最低位，rgb 版依次取 R、G、B 的最低位；像素按列读（先从上到下，再从左到右）。
_STEALTH_MAGICS = {
    b"stealth_pnginfo": ("alpha", False),
    b"stealth_pngcomp": ("alpha", True),
    b"stealth_rgbinfo": ("rgb", False),
    b"stealth_rgbcomp": ("rgb", True),
}
_STEALTH_HEADER_BITS = 15 * 8 + 32
_LSB_TABLE = bytes(ord("0") + (value & 1) for value in range(256))


def read_png_text_chunks(path: str | Path) -> dict[str, str]:
    """读取 PNG 文本块，不依赖旧项目运行时代码。"""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"Not a PNG file: {path}")

    chunks: dict[str, str] = {}
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length

        if chunk_type == b"tEXt":
            key, value = _split_keyword_text(chunk_data)
            chunks[key] = value
        elif chunk_type == b"zTXt":
            key, value = _decode_ztxt(chunk_data)
            chunks[key] = value
        elif chunk_type == b"iTXt":
            key, value = _decode_itxt(chunk_data)
            chunks[key] = value
        elif chunk_type == b"IEND":
            break

    return chunks


def is_png(path: str | Path) -> bool:
    """按文件头判断，不看扩展名（有的 PNG 存成了 .jpg）。"""
    with Path(path).open("rb") as handle:
        return handle.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE


def read_image_parameters(path: str | Path) -> dict[str, Any]:
    png = is_png(path)
    chunks = read_png_text_chunks(path) if png else {}
    decoded = {key: _maybe_json(value) for key, value in chunks.items()}
    parameters = _parameters_from(decoded)
    if not parameters:
        # 文本块被去掉了（转存、压缩过）的图，参数可能还藏在像素里。
        hidden = {key: _maybe_json(value) for key, value in read_stealth_text(path).items()}
        if hidden:
            decoded = {**hidden, **{key: value for key, value in decoded.items() if key not in hidden}}
            parameters = _parameters_from(decoded)
        elif not png:
            raise ValueError(f"Not a PNG file: {path}")
    return {
        "source_path": str(path),
        "png_text": decoded,
        "parameters": parameters,
    }


def _parameters_from(decoded: dict[str, Any]) -> dict[str, Any]:
    comment = decoded.get("Comment")
    if isinstance(comment, dict):
        return comment
    return _core_render_parameters(decoded.get("tags_machine_core"))


def read_stealth_text(path: str | Path) -> dict[str, str]:
    """读藏在像素最低位里的元数据，读成和 PNG 文本块一样的 {键: 文字}；没有时返回空字典。

    NovelAI 写的是一段 JSON（Comment、Description、Source 等键），SD 扩展写的是 parameters 文字。
    只认无损格式（PNG、WebP）；JPEG 有损压缩，最低位留不住。
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow 是依赖，缺了就当没有
        return {}
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "WEBP"}:
                return {}
            text = _read_stealth(image)
    except (OSError, ValueError, EOFError, zlib.error, UnicodeDecodeError):
        return {}
    if text is None:
        return {}
    value = _maybe_json(text)
    if isinstance(value, dict):
        return {str(key): item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for key, item in value.items()}
    return {"parameters": text}


def _read_stealth(image: Any) -> str | None:
    from PIL import Image

    has_alpha = "A" in image.getbands() or "transparency" in image.info
    rgba = image.convert("RGBA")
    width, height = rgba.size
    for kind in ("alpha", "rgb") if has_alpha else ("rgb",):
        per_pixel = 1 if kind == "alpha" else 3

        def bits(count: int) -> str:
            # 只取需要的那几列，转置后按行取字节就是按列的顺序。
            columns = min(width, -(-count // (height * per_pixel)))
            part = rgba.crop((0, 0, columns, height)).transpose(Image.Transpose.TRANSPOSE)
            raw = part.getchannel("A").tobytes() if kind == "alpha" else part.convert("RGB").tobytes()
            return raw[:count].translate(_LSB_TABLE).decode("ascii")

        if width * height * per_pixel < _STEALTH_HEADER_BITS:
            continue
        header = bits(_STEALTH_HEADER_BITS)
        magic = _bits_to_bytes(header[:120])
        found = _STEALTH_MAGICS.get(magic)
        if not found or found[0] != kind:
            continue
        length = int(header[120:], 2)
        if length <= 0 or _STEALTH_HEADER_BITS + length > width * height * per_pixel:
            return None
        data = _bits_to_bytes(bits(_STEALTH_HEADER_BITS + length)[_STEALTH_HEADER_BITS:])
        if found[1]:
            data = gzip.decompress(data)
        return data.decode("utf-8")
    return None


def _bits_to_bytes(bits: str) -> bytes:
    count = len(bits) // 8
    return int(bits[: count * 8], 2).to_bytes(count, "big") if count else b""


def _core_render_parameters(core_info: Any) -> dict[str, Any]:
    """ComfyUI 出的图没有 NovelAI 的 Comment 参数块，从 core 写入的 render 段还原参数。"""
    if not isinstance(core_info, dict) or core_info.get("backend") != "comfyui":
        return {}
    render = core_info.get("render")
    if not isinstance(render, dict):
        return {}
    parameters: dict[str, Any] = {"backend": "comfyui", **render}
    if "cfg" in render:
        parameters.setdefault("scale", render["cfg"])
    return parameters


def read_png_dimensions(path: str | Path) -> dict[str, int]:
    """读取 PNG 画布尺寸，只解析 IHDR，不引入图像库依赖。"""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"Not a PNG file: {path}")

    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            if length < 8:
                raise ValueError(f"Invalid PNG IHDR chunk: {path}")
            width, height = struct.unpack(">II", chunk_data[:8])
            return {"width": width, "height": height}
        if chunk_type == b"IEND":
            break

    raise ValueError(f"PNG IHDR chunk not found: {path}")


def _split_keyword_text(chunk_data: bytes) -> tuple[str, str]:
    if b"\x00" not in chunk_data:
        raise ValueError("Invalid PNG tEXt chunk without keyword separator")
    raw_key, raw_value = chunk_data.split(b"\x00", 1)
    return _decode_text(raw_key), _decode_text(raw_value)


def _decode_ztxt(chunk_data: bytes) -> tuple[str, str]:
    if b"\x00" not in chunk_data:
        raise ValueError("Invalid PNG zTXt chunk without keyword separator")
    raw_key, rest = chunk_data.split(b"\x00", 1)
    if not rest:
        raise ValueError("Invalid PNG zTXt chunk without compression method")
    compression_method = rest[0]
    if compression_method != 0:
        raise ValueError(f"Unsupported PNG zTXt compression method: {compression_method}")
    return _decode_text(raw_key), _decode_text(zlib.decompress(rest[1:]))


def _decode_itxt(chunk_data: bytes) -> tuple[str, str]:
    parts = chunk_data.split(b"\x00", 4)
    if len(parts) < 5:
        raise ValueError("Invalid PNG iTXt chunk")
    raw_key, compression_flag, compression_method, _language_tag, rest = parts
    translated_keyword, raw_text = rest.split(b"\x00", 1) if b"\x00" in rest else (b"", rest)
    del translated_keyword
    if compression_flag == b"\x01":
        if compression_method != b"\x00":
            raise ValueError(f"Unsupported PNG iTXt compression method: {compression_method!r}")
        raw_text = zlib.decompress(raw_text)
    return _decode_text(raw_key), _decode_text(raw_text)


def _decode_text(value: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _maybe_json(value: str) -> Any:
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value
