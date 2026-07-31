from __future__ import annotations

from itertools import product

from ..models import AssetRecord, ExportPlan, ViewEntry, ViewItem


class ClassificationViewBuilder:
    def build(
        self,
        assets: list[AssetRecord],
        *,
        hierarchy: list[str],
        import_id: str | None = None,
        missing_value: str = "unknown",
        skip_missing: bool = False,
    ) -> ExportPlan:
        views: dict[tuple[str, ...], list[ViewItem]] = {}
        for asset in assets:
            projection = asset.node_projection(
                hierarchy,
                missing_value=missing_value,
            )
            if skip_missing and projection.has_missing:
                continue
            dimensions = [projection.values_for(role) for role in projection.hierarchy]
            for path in product(*dimensions):
                views.setdefault(tuple(path), []).append(
                    ViewItem(
                        asset_id=asset.asset_id,
                        source_path=asset.path,
                        display_name=asset.display_name or asset.path.rsplit("/", 1)[-1],
                        order=asset.source_order,
                    )
                )

        entries = []
        for path, items in sorted(views.items(), key=lambda pair: _natural_path_key(pair[0])):
            sorted_items = sorted(
                items,
                key=lambda item: (item.order, _natural_text_key(item.display_name)),
            )
            entries.append(ViewEntry(path=list(path), items=sorted_items))
        return ExportPlan(import_id=import_id, hierarchy=hierarchy, views=entries)


def _natural_text_key(value: str) -> tuple[object, ...]:
    from ..inputs.directory import natural_key

    return natural_key(value)


def _natural_path_key(path: tuple[str, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(_natural_text_key(item) for item in path)
