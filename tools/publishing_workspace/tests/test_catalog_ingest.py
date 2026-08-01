from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.catalog import (
    AssetChangedAfterPlanningError,
    CatalogRepository,
)
from publishing_workspace.metadata import default_image_node_reader_registry


def _png(path: Path, color: str = "white") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), color).save(path)
    return path


def _ingest(repository: CatalogRepository, path: Path, *, readers=None):
    stat = path.stat()
    with repository.connection() as connection:
        return repository.ingest_asset(
            connection,
            path,
            expected_size=stat.st_size,
            expected_modified_ns=stat.st_mtime_ns,
            readers=readers or default_image_node_reader_registry(),
            enrichers=[],
        )


class _FailIfCalledReaders:
    def read(self, path: Path, metadata: dict):
        raise AssertionError("路径复用不应调用 Reader")


def test_ingest_reports_parsed_new_then_reused_path(tmp_path: Path):
    path = _png(tmp_path / "a.png")
    repository = CatalogRepository(tmp_path / "catalog.sqlite")

    first = _ingest(repository, path)
    second = _ingest(repository, path, readers=_FailIfCalledReaders())

    assert first.outcome == "parsed_new"
    assert second.outcome == "reused_path"
    assert second.asset.asset_id == first.asset.asset_id


def test_ingest_reuses_content_at_new_path(tmp_path: Path):
    first_path = _png(tmp_path / "a.png")
    second_path = tmp_path / "b.png"
    second_path.write_bytes(first_path.read_bytes())
    repository = CatalogRepository(tmp_path / "catalog.sqlite")

    first = _ingest(repository, first_path)
    second = _ingest(repository, second_path)

    assert second.outcome == "reused_content"
    assert second.asset.asset_id == first.asset.asset_id


def test_ingest_rejects_file_changed_after_planning(tmp_path: Path):
    path = _png(tmp_path / "a.png")
    repository = CatalogRepository(tmp_path / "catalog.sqlite")
    stat = path.stat()
    path.write_bytes(path.read_bytes() + b"changed")

    with repository.connection() as connection:
        with pytest.raises(AssetChangedAfterPlanningError, match="规划后发生变化"):
            repository.ingest_asset(
                connection,
                path,
                expected_size=stat.st_size,
                expected_modified_ns=stat.st_mtime_ns,
                readers=default_image_node_reader_registry(),
                enrichers=[],
            )
