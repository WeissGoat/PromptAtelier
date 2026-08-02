from __future__ import annotations

from pathlib import Path

import yaml

from publishing_workspace.config import (
    MosaicIntegrationConfig,
    PublishingWorkspaceConfig,
    WorkspacePaths,
    init_workspace,
    load_workspace,
)


def test_mosaic_config_has_stable_default_manifest():
    config = PublishingWorkspaceConfig()

    assert config.integrations.mosaic.provider == "anr_plugin_auto_mosaics"
    assert config.integrations.mosaic.model_root is None
    assert config.integrations.mosaic.models["yolo"].filename == "yolo/censor.pt"
    assert len(config.integrations.mosaic.models["sam"].sha256) == 64


def test_workspace_resolves_default_and_relative_mosaic_model_roots(tmp_path: Path):
    paths = WorkspacePaths.from_root(tmp_path / "publish")

    assert paths.default_mosaic_models.parts[-2:] == (
        "models",
        "anr_plugin_auto_mosaics",
    )
    assert paths.resolve_mosaic_model_root(None) == paths.default_mosaic_models
    assert paths.resolve_mosaic_model_root("workspace/models") == (
        paths.root / "workspace/models"
    ).resolve()


def test_workspace_init_serializes_mosaic_defaults(tmp_path: Path):
    paths, _, created = init_workspace(tmp_path / "publish")

    assert created is True
    _, config = load_workspace(tmp_path / "publish")
    assert isinstance(config.integrations.mosaic, MosaicIntegrationConfig)
    data = yaml.safe_load(paths.config.read_text(encoding="utf-8"))
    assert data["integrations"]["mosaic"]["provider"] == "anr_plugin_auto_mosaics"
