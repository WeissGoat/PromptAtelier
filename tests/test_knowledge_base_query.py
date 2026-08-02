from pathlib import Path

from tags_machine_core.knowledge_base import CatalogStore, import_catalog
from tags_machine_core.knowledge_base.config import load_knowledge_base_config
from tags_machine_core.knowledge_base.query import (
    ActionSearchFilters,
    build_facets,
    search_actions,
    show_action,
)
from tests.knowledge_base_fixtures import write_action, write_config


def _catalog(tmp_path: Path):
    action_root = tmp_path / "actions"
    (action_root / "new").mkdir(parents=True)
    (action_root / "st_sfw").mkdir()
    write_action(action_root, "new/foot", prompt=["2.0::foot focus::", "barefoot"])
    write_action(
        action_root,
        "st_sfw/portrait",
        domain="sfw",
        prompt=["portrait"],
        negative=["forbidden-only-token"],
        scope="portrait",
    )
    config = load_knowledge_base_config(write_config(tmp_path, action_root))
    import_catalog(config)
    return CatalogStore.from_config(config).load_current()


def test_search_combines_filters_and_never_searches_negative(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    result = search_actions(
        catalog,
        ActionSearchFilters(domain="foot", cast="solo", text="foot focus"),
    )
    negative_only = search_actions(
        catalog,
        ActionSearchFilters(text="forbidden-only-token"),
    )

    assert [item["ref"] for item in result["results"]] == ["new/foot"]
    assert "positive_terms" not in result["results"][0]
    assert negative_only["results"] == []


def test_facets_and_show_return_structured_and_raw_sources(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)

    facets = build_facets(catalog)
    shown = show_action(catalog, "new/foot")

    assert facets["facets"]["domain"]["foot"] == 1
    assert shown["meta"]["tags"]["action"][0] == "2.0::foot focus::"
    assert "2.0::foot focus::" in shown["tags_text"]
