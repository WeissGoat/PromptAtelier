from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from publishing_workspace.config import (
    MosaicIntegrationConfig,
    MosaicModelConfig,
    WorkspacePaths,
    init_workspace,
)
from publishing_workspace.integrations.anr_mosaic import MosaicModelManager


def _config(data: bytes, filename: str = "yolo/censor.pt") -> MosaicIntegrationConfig:
    digest = hashlib.sha256(data).hexdigest()
    return MosaicIntegrationConfig(
        model_root="models",
        models={
            "yolo": MosaicModelConfig(
                filename=filename,
                url="https://example.invalid/censor.pt",
                sha256=digest,
            )
        },
    )


def test_model_manager_copies_source_and_reports_ready(tmp_path: Path):
    source = tmp_path / "source" / "yolo" / "censor.pt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test model")
    paths, _, _ = init_workspace(tmp_path / "publish")
    manager = MosaicModelManager(paths, _config(source.read_bytes()))

    assert manager.status()[0].state == "missing"
    installed = manager.install(tmp_path / "source")

    assert installed[0].state == "ready"
    assert installed[0].actual_sha256 == installed[0].expected_sha256
    assert (
        tmp_path / "publish" / "models" / "yolo" / "censor.pt"
    ).read_bytes() == b"test model"


def test_model_manager_does_not_replace_valid_target_on_bad_source(tmp_path: Path):
    source = tmp_path / "source" / "yolo" / "censor.pt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bad")
    paths, _, _ = init_workspace(tmp_path / "publish")
    target = tmp_path / "publish" / "models" / "yolo" / "censor.pt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"valid")
    manager = MosaicModelManager(paths, _config(b"expected"))

    with pytest.raises(ValueError, match="SHA-256"):
        manager.install(tmp_path / "source")

    assert target.read_bytes() == b"valid"


def test_model_manager_rejects_path_escape(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path / "publish")
    manager = MosaicModelManager(paths, _config(b"x", "../escape.pt"))

    with pytest.raises(ValueError, match="相对路径"):
        manager.status()
