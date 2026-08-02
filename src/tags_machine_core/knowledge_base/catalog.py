from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .config import KnowledgeBaseConfig
from .models import (
    ActionCatalogItem,
    CatalogManifest,
    CatalogPointer,
    CatalogWarning,
    LoadedCatalog,
)


class CatalogStore:
    def __init__(self, catalog_dir: str | Path) -> None:
        self.catalog_dir = Path(catalog_dir).expanduser().resolve()

    @classmethod
    def from_config(cls, config: KnowledgeBaseConfig) -> CatalogStore:
        return cls(config.catalog_dir)

    def publish(
        self,
        *,
        catalog_hash: str,
        manifest: CatalogManifest,
        items: list[ActionCatalogItem],
        warnings: list[CatalogWarning],
    ) -> tuple[Path, bool]:
        builds_dir = self.catalog_dir / "builds"
        builds_dir.mkdir(parents=True, exist_ok=True)
        build_name = catalog_hash.replace(":", "-")
        build_dir = builds_dir / build_name
        reused = build_dir.is_dir()
        if not reused:
            temp_dir = builds_dir / f".tmp-{uuid4().hex}"
            temp_dir.mkdir(parents=False)
            try:
                _write_json(temp_dir / "manifest.json", manifest.model_dump(by_alias=True, mode="json"))
                _write_jsonl(
                    temp_dir / "actions.jsonl",
                    [item.model_dump(by_alias=True, mode="json") for item in items],
                )
                _write_jsonl(
                    temp_dir / "warnings.jsonl",
                    [warning.model_dump(mode="json") for warning in warnings],
                )
                os.replace(temp_dir, build_dir)
            except Exception:
                _remove_tree(temp_dir)
                raise

        pointer = CatalogPointer(
            catalog_hash=catalog_hash,
            build=(Path("builds") / build_name).as_posix(),
        )
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        pointer_temp = self.catalog_dir / f".current-{uuid4().hex}.json"
        _write_json(pointer_temp, pointer.model_dump(by_alias=True, mode="json"))
        os.replace(pointer_temp, self.catalog_dir / "current.json")
        return build_dir, reused

    def load_current(self) -> LoadedCatalog:
        pointer_path = self.catalog_dir / "current.json"
        if not pointer_path.is_file():
            raise FileNotFoundError(f"knowledge base current catalog not found: {pointer_path}")
        pointer = CatalogPointer.model_validate(_read_json(pointer_path))
        build_dir = (self.catalog_dir / pointer.build).resolve()
        _ensure_within(build_dir, self.catalog_dir)
        manifest = CatalogManifest.model_validate(_read_json(build_dir / "manifest.json"))
        if manifest.catalog_hash != pointer.catalog_hash:
            raise ValueError("catalog pointer hash does not match manifest")
        items = [ActionCatalogItem.model_validate(value) for value in _read_jsonl(build_dir / "actions.jsonl")]
        warnings = [CatalogWarning.model_validate(value) for value in _read_jsonl(build_dir / "warnings.jsonl")]
        return LoadedCatalog(
            manifest=manifest,
            items=items,
            warnings=warnings,
            build_dir=build_dir,
        )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, values: list[object]) -> None:
    text = "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for value in values
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[object]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ensure_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"catalog build escapes catalog_dir: {path}") from exc


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
