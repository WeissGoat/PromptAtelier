from __future__ import annotations

import struct
import zlib
from pathlib import Path

from publishing_workspace.png_metadata import PNG_SIGNATURE, read_png_text_chunks


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def test_reads_text_chunks_after_image_data(tmp_path: Path):
    path = tmp_path / "metadata.png"
    png = bytearray(PNG_SIGNATURE)
    png.extend(_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)))
    png.extend(_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")))
    png.extend(_chunk(b"tEXt", "tags_machine_core".encode() + b"\x00" + "节点".encode()))
    png.extend(_chunk(b"zTXt", b"artist\x00\x00" + zlib.compress("画风".encode())))
    png.extend(
        _chunk(
            b"iTXt",
            b"action\x00\x00\x00\x00\x00" + "动作".encode(),
        )
    )
    png.extend(_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))

    chunks = read_png_text_chunks(path)

    assert chunks == {
        "tags_machine_core": "节点",
        "artist": "画风",
        "action": "动作",
    }
