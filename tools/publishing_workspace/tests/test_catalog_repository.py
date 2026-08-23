from __future__ import annotations

from pathlib import Path

from PIL import Image

from publishing_workspace.catalog.repository import CatalogRepository
from publishing_workspace.metadata import default_image_node_reader_registry
from publishing_workspace.models import ImportedItem, SelectionSet


def _png(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), color).save(path)
    return path


def test_assets_by_ids_preserves_requested_order_and_import_scope(tmp_path: Path):
    first = _png(tmp_path / "images" / "first.png", "red")
    second = _png(tmp_path / "images" / "second.png", "blue")
    selection = SelectionSet(
        id="import-a",
        source_type="directory",
        source_ref=str(tmp_path / "images"),
        items=[
            ImportedItem(
                source_path=str(first),
                resolved_path=str(first),
                source_type="directory",
                source_ref=str(tmp_path / "images"),
                source_order=0,
                display_name=first.name,
            ),
            ImportedItem(
                source_path=str(second),
                resolved_path=str(second),
                source_type="directory",
                source_ref=str(tmp_path / "images"),
                source_order=1,
                display_name=second.name,
            ),
        ],
    )
    repository = CatalogRepository(tmp_path / "catalog.sqlite")
    repository.import_selection(
        selection,
        readers=default_image_node_reader_registry(),
        enrichers=[],
    )
    imported = repository.assets_for_import("import-a")

    result = repository.assets_by_ids(
        [imported[1].asset_id, "sha256:missing", imported[0].asset_id, imported[1].asset_id],
        import_id="import-a",
    )

    assert list(result) == [imported[1].asset_id, imported[0].asset_id]
    assert result[imported[1].asset_id].display_name == "second.png"
    assert result[imported[0].asset_id].source_order == 0
    assert repository.assets_by_ids(
        [imported[0].asset_id],
        import_id="missing-import",
    ) == {}
