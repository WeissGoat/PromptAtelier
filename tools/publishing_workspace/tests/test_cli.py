from __future__ import annotations

import json
from pathlib import Path

from publishing_workspace.cli import main


def test_publish_cli_init_and_empty_import(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()

    assert main(["init", str(root)]) == 0
    init_result = json.loads(capsys.readouterr().out)
    assert init_result["created"] is True

    assert main(
        [
            "import",
            str(root),
            str(source),
            "--input-type",
            "directory",
        ]
    ) == 0
    import_result = json.loads(capsys.readouterr().out)
    assert import_result["total_items"] == 0
    assert import_result["unique_assets"] == 0
