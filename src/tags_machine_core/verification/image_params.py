from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


def read_image_parameters(path: str | Path) -> dict[str, Any]:
    chunks = read_png_text_chunks(path)
    decoded = {key: _maybe_json(value) for key, value in chunks.items()}
    comment = decoded.get("Comment")
    return {
        "source_path": str(path),
        "png_text": decoded,
        "parameters": comment if isinstance(comment, dict) else {},
    }


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
