import json
from pathlib import Path

from tags_machine_core.cli import build_parser, main
from tests.knowledge_base_fixtures import write_action, write_config


def test_parser_registers_nested_kb_command() -> None:
    args = build_parser().parse_args(["kb", "search", "--config", "kb.yaml", "--domain", "foot"])

    assert args.kb_command == "search"
    assert args.domain == ["foot"]


def test_cli_import_and_search_emit_json(tmp_path: Path, capsys) -> None:
    action_root = tmp_path / "actions"
    (action_root / "new").mkdir(parents=True)
    write_action(action_root, "new/foot")
    config = write_config(tmp_path, action_root)

    assert main(["kb", "import", "--config", str(config)]) == 0
    capsys.readouterr()
    assert main(["kb", "search", "--config", str(config), "--domain", "foot"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "tags-machine-core.action-search-result/v1"
    assert payload["results"][0]["ref"] == "new/foot"
