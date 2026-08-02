from __future__ import annotations

from pathlib import Path

import yaml


def write_config(tmp_path: Path, action_root: Path) -> Path:
    config = tmp_path / "knowledge_base.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema": "tags-machine-core.knowledge-base/v1",
                "action_root": str(action_root),
                "catalog_dir": str(tmp_path / "catalog"),
                "sources": [
                    {"id": "new", "path": "new", "enabled": True},
                    {"id": "legacy", "pattern": "st_*", "enabled": True},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config


def write_action(
    root: Path,
    ref: str,
    *,
    action_id: str | None = None,
    domain: str = "foot",
    cast: str = "solo",
    prompt: list[str] | None = None,
    negative: list[str] | None = None,
    scope: str = "foot_detail",
    include_meta: bool = True,
) -> Path:
    node = root / Path(ref)
    node.mkdir(parents=True)
    prompt = prompt or ["foot focus", "barefoot"]
    negative = negative or ["bad anatomy"]
    (node / "tags.txt").write_text(", ".join(prompt), encoding="utf-8")
    (node / "classify.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "node_id": ref,
                "phase": "core",
                "species": "human",
                "cast": cast,
                "domain": [domain],
                "subtype": {domain: ["detail"]},
                "pose": ["standing"],
                "environment": [],
                "tone": "normal",
                "flags": [],
                "clothing": "clothed",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    if include_meta:
        (node / "meta.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema": "tags-machine.action/v1",
                    "kind": "action",
                    "id": action_id or node.name,
                    "name": action_id or node.name,
                    "description": "fixture action",
                    "tags": {"action": prompt},
                    "negative_prompt": negative,
                    "character_scope": scope,
                    "clothing": {"state": "clothed"},
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return node
