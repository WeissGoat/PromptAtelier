"""跨后台任务的成功结果复用。缓存持久化，按参数加锁，复用图另存契约关联。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

REUSE_MANIFEST = "generation.reuse.json"


class GenerationReuse:
    def __init__(self, output_root: str | Path):
        self.root = Path(output_root).resolve()
        self.directory = self.root / ".web" / "generation_cache"
        # 固定数量的锁避免每个历史请求永久占用一个锁；同一键总是串行。
        self.locks = [threading.Lock() for _ in range(64)]

    def signature(self, api: Any, compose: dict, plan: dict, options: dict) -> str:
        render = compose.get("render") or {}
        params = render.get("params") or {}
        payload = plan.get("artist_payload") or {}
        seed = render.get("seed")
        if seed is None:
            seed = params.get("seed", (payload.get("params") or {}).get("seed"))
        random_seed = seed is None or int(seed) < 0
        size = params.get("size") or payload.get("default_size") or "custom"
        # 对随机设置作确定性的计划预览，不花额度；真实 miss 仍执行原来随机出的计划。
        if random_seed or size == "random":
            stable = copy.deepcopy(compose)
            stable_render = stable.setdefault("render", {})
            if random_seed:
                stable_render["seed"] = 0
            if size == "random":
                stable_render.setdefault("params", {})["size"] = "custom"
            plan = api.resolve_compose_render_plan(stable)["render_request"]
        effective = {key: value for key, value in plan.items() if key not in {"meta", "schema"}}
        effective["action"] = (plan.get("meta") or {}).get("action")
        identity = {
            "version": 1,
            "request": effective,
            "random_seed": random_seed,
            "random_size": size == "random",
            "comfyui_target": options.get("comfyui_target"),
        }
        text = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def run(
        self, api: Any, compose: dict, prepared: dict, generate, *, force: bool = False
    ) -> dict:
        key = self.signature(api, compose, prepared["render_request"], prepared)
        path = self.directory / f"{key}.json"
        with self.locks[int(key[:4], 16) % len(self.locks)]:
            cached = self._read(path) if not force else None
            if cached and self._valid(cached.get("images")):
                images = cached["images"]
                self._associate(compose, prepared, images, key)
                return {"images": images, "cache_hit": True}
            result = generate()
            images = result.get("images") or []
            # 部分返回或文件已丢失时不可把不完整的一批当作成功缓存。
            count = int(((compose.get("render") or {}).get("params") or {}).get("n_samples", 1))
            if len(images) >= count and self._valid(images):
                self._write(path, {"images": images})
            return result

    @staticmethod
    def _valid(images: Any) -> bool:
        try:
            return (
                isinstance(images, list)
                and bool(images)
                and all(
                    isinstance(image, dict)
                    and image.get("path")
                    and Path(image["path"]).is_file()
                    and Path(image["path"]).stat().st_size > 0
                    for image in images
                )
            )
        except (OSError, TypeError):
            return False

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _associate(self, compose: dict, prepared: dict, images: list, key: str) -> None:
        trace = (compose.get("compose") or {}).get("contract")
        if not trace or not prepared.get("output_dir"):
            return
        directory = Path(prepared["output_dir"])
        self._write(
            directory / REUSE_MANIFEST,
            {
                "contract": trace,
                "images": images,
                "key": key,
                "created_at": time.time(),
            },
        )
