from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from tags_machine_core.verification.image_params import read_image_parameters
from tags_machine_core.verification.render_params import compare_render_parameters


MATCH_SIMILARITY = 0.9
_SIMILARITY_SIZE = 256
_RESOLUTION_KEYS = {"width", "height"}


def image_similarity(left: Path, right: Path) -> dict[str, Any]:
    """两图缩放到同一尺寸后的灰度相似度（1 为完全相同）和 dHash 汉明距离（0–64，越小越像）。"""
    with Image.open(left) as a, Image.open(right) as b:
        a_gray = a.convert("L")
        b_gray = b.convert("L")
        a_small = a_gray.resize((_SIMILARITY_SIZE, _SIMILARITY_SIZE), Image.Resampling.BILINEAR)
        b_small = b_gray.resize((_SIMILARITY_SIZE, _SIMILARITY_SIZE), Image.Resampling.BILINEAR)
        mean_diff = ImageStat.Stat(ImageChops.difference(a_small, b_small)).mean[0]
        distance = _hamming(_dhash(a_gray), _dhash(b_gray))
    return {"similarity": round(1 - mean_diff / 255, 4), "dhash_distance": distance}


def _dhash(image: Image.Image) -> int:
    small = image.resize((9, 8), Image.Resampling.BILINEAR)
    pixels = small.tobytes()  # L 模式每像素一个字节
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _diff_key(path: str) -> str:
    """'$.parameters.seed' -> 'seed'，'$.model' -> 'model'，'$.parameters.v4_prompt.caption…' -> 'v4_prompt'。"""
    parts = path.removeprefix("$.").split(".")
    if parts and parts[0] == "parameters" and len(parts) > 1:
        return parts[1].split("[")[0]
    return parts[0].split("[")[0]


def compare_with_source(
    source: Path,
    generated: Path,
    *,
    expected_keys: Iterable[str] = (),
) -> dict[str, Any]:
    """对照源图和生成图。expected_keys 是本次设置主动改动的参数（如随机种子），不算作链路差异。"""
    expected = set(expected_keys)
    diffs = [
        item.as_dict()
        for item in compare_render_parameters(read_image_parameters(source), read_image_parameters(generated))
    ]
    for diff in diffs:
        key = _diff_key(diff["path"])
        diff["key"] = key
        diff["expected"] = key in expected
    unexpected = [diff for diff in diffs if not diff["expected"]]
    unexpected_no_resolution = [diff for diff in unexpected if diff["key"] not in _RESOLUTION_KEYS]
    try:
        similarity = image_similarity(source, generated)
    except OSError as exc:
        similarity = {"similarity": None, "dhash_distance": None, "error": str(exc)}

    if unexpected_no_resolution:
        verdict = "param_diff"
    elif similarity.get("similarity") is not None and similarity["similarity"] >= MATCH_SIMILARITY:
        verdict = "match"
    else:
        verdict = "drift"
    return {
        "verdict": verdict,
        **similarity,
        "param_diff_count": len(unexpected),
        "param_diff_no_resolution_count": len(unexpected_no_resolution),
        "diffs": diffs,
    }
