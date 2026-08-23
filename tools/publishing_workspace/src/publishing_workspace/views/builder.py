from __future__ import annotations

from itertools import product
from typing import Protocol

from ..models import AssetRecord, ExportPlan, NodeValueProjection, ViewEntry, ViewItem


class NodeValueResolver(Protocol):
    @property
    def warnings(self) -> list[str]: ...

    def values_for(self, asset: AssetRecord, role: str) -> list[str]: ...


class DefaultNodeValueResolver:
    @property
    def warnings(self) -> list[str]:
        return []

    def values_for(self, asset: AssetRecord, role: str) -> list[str]:
        return asset.node_info.values_for(role)


class ClassificationViewBuilder:
    def build(
        self,
        assets: list[AssetRecord],
        *,
        hierarchy: list[str],
        import_id: str | None = None,
        missing_value: str = "unknown",
        skip_missing: bool = False,
        node_value_resolver: NodeValueResolver | None = None,
    ) -> ExportPlan:
        resolver = node_value_resolver or DefaultNodeValueResolver()
        views: dict[tuple[str, ...], list[ViewItem]] = {}
        for asset in assets:
            projection = _project_asset(
                asset,
                hierarchy,
                missing_value=missing_value,
                resolver=resolver,
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
        return ExportPlan(
            import_id=import_id,
            hierarchy=hierarchy,
            views=entries,
            warnings=resolver.warnings,
        )


def _project_asset(
    asset: AssetRecord,
    hierarchy: list[str],
    *,
    missing_value: str,
    resolver: NodeValueResolver,
) -> NodeValueProjection:
    normalized_hierarchy = [
        str(role).strip()
        for role in hierarchy
        if str(role).strip()
    ]
    normalized_missing = str(missing_value or "").strip()
    if not normalized_missing:
        raise ValueError("missing_value 不能为空")

    values: dict[str, list[str]] = {}
    missing_roles: list[str] = []
    for role in normalized_hierarchy:
        role_values = resolver.values_for(asset, role)
        if role_values:
            values[role] = role_values
        else:
            values[role] = [normalized_missing]
            missing_roles.append(role)

    return NodeValueProjection(
        hierarchy=normalized_hierarchy,
        missing_value=normalized_missing,
        values=values,
        missing_roles=missing_roles,
    )


def _natural_text_key(value: str) -> tuple[object, ...]:
    from ..inputs.directory import natural_key

    return natural_key(value)


def _natural_path_key(path: tuple[str, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(_natural_text_key(item) for item in path)
