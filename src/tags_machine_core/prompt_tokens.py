"""按 NovelAI 官网的方式数提示词 token。

官网图片页（novelai.net/image）的前端代码里：
- 模型 → 分词器：V5 用 Qwen 3.5，V4 / V4.5 用 T5，V3 及更早用 CLIP。
- 模型 → 上限：V5 Full（含 Medium）1471，V5 Curated 703，V4 / V4.5 512，其他 225。
- 支持分角色提示词的模型（V4+），主提示词和各角色提示词加起来共用一个上限。
- 计数前的预处理：
  - CLIP：``[]{}`` 换成空格，HTML 实体解码两次，合并空白，转小写；不计开始 / 结束符。
  - T5：删掉 ``[]{}`` 和 ``1.2::`` / ``::`` 这类权重记号；不做 Precompiled 归一化；末尾加 1 个结束符。
  - Qwen：NFC 归一化，字节级 BPE；不删权重记号，不加特殊符。

官网用的词表和下面公开的同款词表逐项比对过（CLIP、T5 完全一致；Qwen 3.5 只差 26 个
对提示词无影响的特殊符），所以这里从 Hugging Face 下载公开词表，缓存到本地，仓库里不放
NovelAI 的文件。下载失败或没装 ``tokenizers`` 时退回估算，结果里 ``exact`` 为 False。

缓存目录默认是 ``<项目>/cache/tokenizers``（``TM_TOKENIZER_DIR`` 可改）；
``TM_TOKENIZER_DOWNLOAD=0`` 禁止下载；``HF_ENDPOINT`` 可指定镜像。也可以手动把
``tokenizer.json`` 放进缓存目录，文件名见 ``_cache_path``。
"""

from __future__ import annotations

import html
import math
import os
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tags_machine_core.logging_config import get_logger

logger = get_logger(__name__)

TokenizerKind = Literal["clip", "t5", "qwen", "approx"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 公开词表：仓库 / 固定版本 / 文件。改版本时同时改缓存文件名里的短 sha，旧缓存自然失效。
TOKENIZER_SOURCES: dict[str, tuple[str, str]] = {
    "clip": ("openai/clip-vit-large-patch14", "32bd64288804d66eefd0ccbe215aa642df71cc41"),
    "t5": ("google-t5/t5-base", "a9723ea7f1b39c1eae772870f3b547bf6ef7e6c1"),
    "qwen": ("Qwen/Qwen3.5-0.8B", "2fc06364715b967f1860aea9cf38778875588b17"),
}
DOWNLOAD_TIMEOUT = 30
RETRY_AFTER_SECONDS = 600

_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_T5_STRIP_RE = re.compile(r"-?\d*\.?\d*::")
_BRACKETS_RE = re.compile(r"[\[\]{}]")


@dataclass(frozen=True)
class TokenCount:
    count: int
    exact: bool
    tokenizer: str


def tokenizer_cache_dir() -> Path:
    override = os.environ.get("TM_TOKENIZER_DIR")
    return Path(override) if override else PROJECT_ROOT / "cache" / "tokenizers"


_lock = threading.Lock()
_loaded: dict[str, Any] = {}
_failed_at: dict[str, float] = {}


def _cache_path(kind: str) -> Path:
    _, sha = TOKENIZER_SOURCES[kind]
    return tokenizer_cache_dir() / f"{kind}-{sha[:10]}.json"


def _download(kind: str, target: Path) -> None:
    import requests

    repo, sha = TOKENIZER_SOURCES[kind]
    # HF_ENDPOINT 和 huggingface_hub 的约定一致，连不上 huggingface.co 时可设为镜像（如 https://hf-mirror.com）。
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    url = f"{endpoint}/{repo}/resolve/{sha}/tokenizer.json"
    logger.info("下载分词器 %s ← %s", kind, url)
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".part")
    temp.write_bytes(response.content)
    temp.replace(target)


def _load(kind: str, *, allow_download: bool) -> Any | None:
    if kind not in TOKENIZER_SOURCES:
        return None
    if kind in _loaded:
        return _loaded[kind]
    with _lock:
        if kind in _loaded:
            return _loaded[kind]
        failed = _failed_at.get(kind)
        if failed is not None and time.monotonic() - failed < RETRY_AFTER_SECONDS:
            return None
        try:
            from tokenizers import Tokenizer, normalizers
        except ImportError:
            _failed_at[kind] = time.monotonic()
            logger.warning("没有安装 tokenizers，token 数改为估算")
            return None
        path = _cache_path(kind)
        try:
            if not path.is_file():
                if not allow_download or os.environ.get("TM_TOKENIZER_DOWNLOAD", "1") == "0":
                    return None
                _download(kind, path)
            tokenizer = Tokenizer.from_file(str(path))
            if kind == "t5":
                # 官网的 T5 不做 Precompiled 归一化（normalize 直接返回原文）。
                tokenizer.normalizer = normalizers.Sequence([])
        except Exception as exc:  # noqa: BLE001 网络、文件损坏等：退回估算，过一段时间再试
            _failed_at[kind] = time.monotonic()
            logger.warning("分词器 %s 不可用，token 数改为估算：%s", kind, exc)
            return None
        _loaded[kind] = tokenizer
        return tokenizer


def preprocess(text: str, kind: str) -> str:
    """官网送进分词器之前对文本做的处理。"""
    if kind == "clip":
        value = _BRACKETS_RE.sub(" ", text).strip()
        value = html.unescape(html.unescape(value)).strip()
        return re.sub(r"\s+", " ", value).strip().lower()
    if kind == "t5":
        return _T5_STRIP_RE.sub("", _BRACKETS_RE.sub("", text))
    return text


def estimate_tokens(text: str, kind: str) -> int:
    """没有真实分词器时的估算：英文词按 ~4 字符一个 token，标点各 1 个；CJK 每字 2 个。"""
    value = preprocess(text, kind)
    count = 0
    for word in re.findall(r"[A-Za-z0-9']+|[^\sA-Za-z0-9']", value):
        if word[0].isalnum() or word[0] == "'":
            count += max(1, math.ceil(len(word) / (5 if kind == "clip" else 4)))
        elif _CJK_RE.match(word):
            count += 2
        else:
            count += 1
    return count + (1 if kind == "t5" else 0)


def count_tokens(text: str, kind: str, *, allow_download: bool = True) -> TokenCount:
    """按官网的方式数一段提示词；T5 的结果含末尾的结束符（和官网显示一致）。"""
    tokenizer = _load(kind, allow_download=allow_download)
    if tokenizer is None:
        return TokenCount(estimate_tokens(text, kind), False, kind)
    value = preprocess(text, kind)
    if kind == "t5":
        if not value:
            return TokenCount(1, True, kind)
        return TokenCount(len(tokenizer.encode(value, add_special_tokens=True).ids), True, kind)
    if not value:
        return TokenCount(0, True, kind)
    return TokenCount(len(tokenizer.encode(value, add_special_tokens=False).ids), True, kind)


def novelai_token_spec(model: str | None) -> tuple[str, int, bool]:
    """NovelAI 模型 → (分词器, 上限, 主提示词和角色提示词是否共用上限)。和官网前端的对照表一致。"""
    name = (model or "").strip().lower()
    if name.startswith("nai-diffusion-5"):
        if "curated" in name:
            return "qwen", 703, True
        return "qwen", 1471, True
    if name.startswith("nai-diffusion-4"):
        return "t5", 512, True
    return "clip", 225, False


def prompt_token_usage(
    base: str,
    characters: Iterable[str] = (),
    *,
    tokenizer: str,
    limit: int | None,
    shared: bool = True,
    allow_download: bool = True,
) -> dict[str, Any]:
    """主提示词和各角色提示词的 token 数；shared 时按官网规则加总后和上限比较。"""
    base_count = count_tokens(base, tokenizer, allow_download=allow_download)
    char_counts = [count_tokens(text, tokenizer, allow_download=allow_download) for text in characters]
    total = base_count.count + (sum(item.count for item in char_counts) if shared else 0)
    exact = base_count.exact and all(item.exact for item in char_counts)
    over = False
    if limit:
        over = total > limit if shared else max([base_count.count, *[item.count for item in char_counts]]) > limit
    return {
        "tokenizer": tokenizer,
        "limit": limit,
        "exact": exact,
        "shared": shared,
        "base": base_count.count,
        "characters": [item.count for item in char_counts],
        "total": total,
        "over": over,
    }


def render_request_token_usage(render_request: dict[str, Any]) -> dict[str, Any] | None:
    """从 NovelAI 的 RenderRequest 里取最终提示词（含画风前后缀、分角色提示词）算 token。"""
    if render_request.get("backend") != "novelai":
        return None
    params = render_request.get("params") or {}
    positive = render_request.get("prompt")
    if not isinstance(positive, str):
        positive = params.get("prompt") if isinstance(params.get("prompt"), str) else ""
    captions = (((params.get("v4_prompt") or {}).get("caption") or {}).get("char_captions")) or []
    characters = [item.get("char_caption", "") for item in captions if isinstance(item, dict)]
    tokenizer, limit, shared = novelai_token_spec(render_request.get("model"))
    usage = prompt_token_usage(positive, characters if shared else [], tokenizer=tokenizer, limit=limit, shared=shared)
    usage["model"] = render_request.get("model")
    return usage
