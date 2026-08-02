from pathlib import Path

import pytest

from tags_machine_core.knowledge_base.config import load_knowledge_base_config
from tests.knowledge_base_fixtures import write_config


def test_config_resolves_sources_without_implicit_folders(tmp_path: Path) -> None:
    action_root = tmp_path / "actions"
    for name in ("new", "st_rp", "pn_skip", "story_skip"):
        (action_root / name).mkdir(parents=True)
    config = load_knowledge_base_config(write_config(tmp_path, action_root))

    roots, issues = config.resolve_source_roots()

    assert [root.path.name for root in roots] == ["new", "st_rp"]
    assert issues == []


def test_config_rejects_path_and_pattern_together(tmp_path: Path) -> None:
    action_root = tmp_path / "actions"
    action_root.mkdir()
    config_path = write_config(tmp_path, action_root)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(text.replace("path: new", "path: new\n  pattern: st_*"), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one"):
        load_knowledge_base_config(config_path)
