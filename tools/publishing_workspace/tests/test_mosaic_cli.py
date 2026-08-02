from __future__ import annotations

import json
from pathlib import Path

import yaml

from publishing_workspace.cli import main


def test_mosaic_status_cli_reports_missing_models(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()

    config_path = root / "workspace" / "workspace.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["integrations"]["mosaic"]["model_root"] = "missing-models"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assert main(["mosaic", "status", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["provider"] == "anr_plugin_auto_mosaics"
    assert {item["status"] for item in result["models"]} == {"missing"}
