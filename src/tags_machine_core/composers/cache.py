from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tags_machine_core.contracts import PromptBundle


_SHA256_CACHE_KEY = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_CACHE_STEM_LENGTH = 120


class PromptCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> PromptBundle | None:
        key = str(key).strip()
        path = self._path_for(key)
        if not path.exists():
            return None
        bundle = PromptBundle.model_validate_json(path.read_text(encoding="utf-8"))
        if bundle.cache.cache_key != key:
            return None
        bundle.cache.cache_hit = True
        return bundle

    def put(self, bundle: PromptBundle) -> Path | None:
        if not bundle.cache.cache_key:
            return None
        path = self._path_for(bundle.cache.cache_key)
        path.write_text(bundle.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        return path

    def _path_for(self, key: str) -> Path:
        return self.root / f"{self._filename_stem_for(key)}.json"

    def _filename_stem_for(self, key: str) -> str:
        key = str(key).strip()
        if not key:
            raise ValueError("cache key must not be empty")
        if _SHA256_CACHE_KEY.fullmatch(key):
            return key.replace(":", "_")

        # 非标准 key 可能来自外部 agent 或调试脚本，必须压成单个文件名，避免穿透缓存目录。
        safe_key = _UNSAFE_FILENAME_CHARS.sub("_", key).strip("._-") or "cache"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        max_prefix_length = _MAX_CACHE_STEM_LENGTH - len(digest) - 1
        safe_key = safe_key[:max_prefix_length].rstrip("._-") or "cache"
        return f"{safe_key}_{digest}"
