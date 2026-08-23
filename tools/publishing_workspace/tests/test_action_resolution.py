import json
from pathlib import Path

from publishing_workspace.action_resolution import ActionNodeValueResolver
from publishing_workspace.models import (
    AssetFingerprint,
    AssetImageInfo,
    AssetRecord,
    ImageNodeInfo,
    ImageNodeRef,
)
from publishing_workspace.views import ClassificationViewBuilder


def _asset(asset_id: str, nodes: list[ImageNodeRef]) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        path=f"F:/{asset_id}.png",
        fingerprint=AssetFingerprint(size=1, modified_ns=1, sha256=asset_id),
        image=AssetImageInfo(width=2, height=2, format="PNG"),
        node_info=ImageNodeInfo(nodes=nodes),
    )


def _design(tmp_path: Path) -> tuple[Path, Path, Path]:
    design = tmp_path / "design"
    action_root = design / "动作改2"
    original = action_root / "new" / "standing"
    category = action_root / "st_sfw" / "01_standing"
    original.mkdir(parents=True)
    category.mkdir(parents=True)
    (action_root / "category_view_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "name": "standing",
                        "view_name": "01_standing",
                        "root": "st_sfw",
                        "source": "new/standing",
                        "dest": "st_sfw/01_standing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return design, original, category


def test_dynamic_category_action_uses_original_node_and_latest_group(tmp_path: Path):
    design, original, category = _design(tmp_path)
    asset = _asset(
        "dynamic",
        [
            ImageNodeRef(role="action", id="01_standing", ref=str(category)),
            ImageNodeRef(role="action_group", id="st_old"),
        ],
    )
    resolver = ActionNodeValueResolver(design_root=design)

    assert resolver.values_for(asset, "action") == [original.name]
    assert resolver.values_for(asset, "action_group") == ["st_sfw"]
    assert resolver.warnings == []


def test_standalone_category_action_is_not_forced_into_new(tmp_path: Path):
    design = tmp_path / "design"
    standalone = design / "动作改2" / "st_rp" / "01_independent"
    standalone.mkdir(parents=True)
    (standalone / "tags.txt").write_text("standing", encoding="utf-8")
    asset = _asset(
        "standalone",
        [ImageNodeRef(role="action", id="01_independent", ref=str(standalone))],
    )
    resolver = ActionNodeValueResolver(design_root=design)

    assert resolver.values_for(asset, "action") == ["01_independent"]
    assert resolver.values_for(asset, "action_group") == ["st_rp"]
    assert resolver.warnings == []


def test_unresolved_action_keeps_raw_values_and_is_exportable(tmp_path: Path):
    design = tmp_path / "design"
    (design / "动作改2").mkdir(parents=True)
    asset = _asset(
        "unresolved",
        [
            ImageNodeRef(role="action", id="03_unknown_action"),
            ImageNodeRef(role="action_group", id="st_rp"),
        ],
    )
    resolver = ActionNodeValueResolver(design_root=design)
    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["action_group", "action"],
        node_value_resolver=resolver,
    )

    assert [view.key for view in plan.views] == ["st_rp/03_unknown_action"]
    assert plan.warnings


def test_missing_action_group_uses_unknown_and_is_exportable(tmp_path: Path):
    asset = _asset("missing-group", [ImageNodeRef(role="action", id="action")])
    resolver = ActionNodeValueResolver(design_root=tmp_path / "missing-design")
    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["action_group", "action"],
        node_value_resolver=resolver,
        skip_missing=False,
    )

    assert [view.key for view in plan.views] == ["unknown/action"]
