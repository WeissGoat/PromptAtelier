from pathlib import Path

from tags_machine_core.knowledge_base import CatalogStore, import_catalog
from tags_machine_core.knowledge_base.config import load_knowledge_base_config
from tests.knowledge_base_fixtures import write_action, write_config


def test_import_builds_stable_catalog_and_aliases(tmp_path: Path) -> None:
    action_root = tmp_path / "actions"
    (action_root / "new").mkdir(parents=True)
    (action_root / "st_rp").mkdir()
    (action_root / "pn_skip").mkdir()
    write_action(action_root, "new/a", action_id="shared")
    first = write_action(action_root, "st_rp/b", action_id="shared")
    # 完全相同的三个源文件应属于同一个 alias group。
    for filename in ("tags.txt", "classify.yaml", "meta.yaml"):
        (first / filename).write_bytes((action_root / "new" / "a" / filename).read_bytes())
    write_action(action_root, "pn_skip/hidden")
    config = load_knowledge_base_config(write_config(tmp_path, action_root))

    result1 = import_catalog(config)
    result2 = import_catalog(config)
    catalog = CatalogStore.from_config(config).load_current()

    assert result1.record_count == 2
    assert result2.catalog_hash == result1.catalog_hash
    assert result2.reused_build is True
    assert catalog.items[0].aliases == ["new/a", "st_rp/b"]
    assert all(not item.ref.startswith("pn_") for item in catalog.items)


def test_missing_meta_warns_without_stopping_import(tmp_path: Path) -> None:
    action_root = tmp_path / "actions"
    (action_root / "new").mkdir(parents=True)
    (action_root / "st_sfw").mkdir()
    write_action(action_root, "st_sfw/legacy", include_meta=False)
    config = load_knowledge_base_config(write_config(tmp_path, action_root))

    result = import_catalog(config)
    catalog = CatalogStore.from_config(config).load_current()

    assert result.record_count == 1
    assert "missing_file" in {warning.code for warning in catalog.warnings}
    assert "empty_action_prompt" not in {warning.code for warning in catalog.warnings}
    assert catalog.items[0].action.positive_terms == ["foot focus", "barefoot"]


def test_import_uses_edited_tags_instead_of_stale_meta(tmp_path: Path) -> None:
    action_root = tmp_path / "actions"
    (action_root / "new").mkdir(parents=True)
    node = write_action(action_root, "new/a")
    config = load_knowledge_base_config(write_config(tmp_path, action_root))
    first = import_catalog(config)
    (node / "tags.txt").write_text("sitting\n=uc, new negative\n", encoding="utf-8")
    second = import_catalog(config)
    catalog = CatalogStore.from_config(config).load_current()
    assert second.catalog_hash != first.catalog_hash
    assert catalog.items[0].action.positive_terms == ["sitting"]
    assert catalog.items[0].action.negative_terms_count == 1
