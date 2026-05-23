from __future__ import annotations

from pathlib import Path

from tags_machine_core.contracts import PromptBundle


class PromptCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> PromptBundle | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        bundle = PromptBundle.model_validate_json(path.read_text(encoding="utf-8"))
        bundle.cache.cache_hit = True
        return bundle

    def put(self, bundle: PromptBundle) -> Path | None:
        if not bundle.cache.cache_key:
            return None
        path = self._path_for(bundle.cache.cache_key)
        path.write_text(bundle.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        return path

    def _path_for(self, key: str) -> Path:
        safe_key = key.replace(":", "_").replace("/", "_")
        return self.root / f"{safe_key}.json"
