import json
from pathlib import Path

from tags_machine_core.tools.action_resolver.index import ActionNodeIndex


def _build_design(tmp_path: Path) -> tuple[Path, Path, Path]:
    design = tmp_path / "design"
    action_root = design / "动作改2"
    source = action_root / "new" / "侧脸回眸"
    category = action_root / "pn_portrait" / "00_start_侧脸回眸"
    source.mkdir(parents=True)
    category.mkdir(parents=True)
    (action_root / "category_view_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "name": "侧脸回眸",
                        "view_name": "00_start_侧脸回眸",
                        "root": "pn_portrait",
                        "source": "new/侧脸回眸",
                        "dest": "pn_portrait/00_start_侧脸回眸",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return design, source, category


def test_manifest_maps_category_dest_and_root_view_to_new_source(tmp_path: Path) -> None:
    design, source, _ = _build_design(tmp_path)
    index = ActionNodeIndex(design)

    assert index.manifest_by_dest("pn_portrait/00_start_侧脸回眸") == {source.resolve()}
    assert index.manifest_by_root_view("pn_portrait", "00_start_侧脸回眸") == {
        source.resolve()
    }


def test_category_candidates_accept_numeric_prefix(tmp_path: Path) -> None:
    design = tmp_path / "design"
    category = design / "动作改2" / "st_old" / "2_20240720_1721464255"
    (design / "动作改2" / "new").mkdir(parents=True)
    category.mkdir(parents=True)

    index = ActionNodeIndex(design)

    assert index.category_candidates("st_old", "20240720_1721464255") == {
        category.resolve()
    }
