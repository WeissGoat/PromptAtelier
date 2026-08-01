from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from ..tasks.models import OperationConfig


class ProcessingCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def key(
        self,
        input_sha256: str,
        profile: str,
        operations: list[tuple[str, OperationConfig]],
    ) -> str:
        payload = {
            "input_sha256": input_sha256,
            "profile": profile,
            "operations": [
                {
                    "type": operation_type,
                    "enabled": config.enabled,
                    "version": config.version,
                    "adapter": config.adapter,
                    "options": config.options,
                }
                for operation_type, config in operations
                if config.enabled
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}"

    def copy_to(self, cached: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, target)
