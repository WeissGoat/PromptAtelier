from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.config import MosaicIntegrationConfig, MosaicModelConfig, init_workspace
from publishing_workspace.integrations.anr_mosaic import AnrAutoMosaicsAdapter
from publishing_workspace.tasks import OperationConfig, ProcessingConfig, TaskConfig, TaskPaths, TaskRepository
from publishing_workspace.packages import PackageBuilder


def _config(tmp_path: Path, data: bytes = b"model") -> MosaicIntegrationConfig:
    return MosaicIntegrationConfig(
        model_root="models",
        models={
            "yolo": MosaicModelConfig(
                filename="yolo/censor.pt",
                url="https://example.invalid/censor.pt",
                sha256=hashlib.sha256(data).hexdigest(),
            )
        },
    )


def test_adapter_processes_with_fake_yolo_and_keeps_target_boundary(tmp_path: Path, monkeypatch):
    import publishing_workspace.integrations.anr_mosaic.adapter as adapter_module

    class FakeYolo:
        def __init__(self, model_path: Path):
            assert model_path.is_file()

        def create_mask(self, source: Path, target: Path, labels: tuple[str, ...]) -> None:
            mask = Image.new("L", (16, 12), 0)
            for x in range(4, 12):
                for y in range(3, 9):
                    mask.putpixel((x, y), 255)
            mask.save(target)

    monkeypatch.setattr(adapter_module, "YoloDetector", FakeYolo)
    paths, _, _ = init_workspace(tmp_path / "publish")
    data = b"model"
    config = _config(tmp_path, data)
    model = paths.root / "models" / "yolo" / "censor.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(data)
    source = tmp_path / "source.png"
    target = tmp_path / "output" / "result.png"
    Image.new("RGB", (16, 12), (10, 20, 30)).save(source)

    AnrAutoMosaicsAdapter(paths, config).process(
        source,
        target,
        {"detector": "yolo", "method": "solid", "parts": ["penis"]},
    )

    assert target.is_file()
    assert Image.open(target).getpixel((8, 6)) == (128, 128, 128)
    assert Image.open(target).getpixel((0, 0)) == (10, 20, 30)
    assert not list(target.parent.glob(".mosaic-*"))


def test_adapter_anus_only_does_not_load_detector(tmp_path: Path, caplog):
    caplog.set_level(logging.WARNING)
    paths, _, _ = init_workspace(tmp_path / "publish")
    config = _config(tmp_path)
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(source)

    AnrAutoMosaicsAdapter(paths, config).process(
        source,
        target,
        {"detector": "yolo", "method": "solid", "parts": ["anus"]},
    )

    assert target.read_bytes() == source.read_bytes()
    assert "不支持部位 anus" in caplog.text


def test_adapter_rejects_missing_model_before_detector_load(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path / "publish")
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    Image.new("RGB", (4, 4), "white").save(source)

    with pytest.raises(ValueError, match="模型不可用"):
        AnrAutoMosaicsAdapter(paths, _config(tmp_path)).process(
            source,
            target,
            {"detector": "yolo", "method": "solid", "parts": ["penis"]},
        )
    assert not target.exists()


def test_package_builder_creates_default_registry_with_mosaic_adapter(tmp_path: Path, monkeypatch):
    import publishing_workspace.packages.builder as builder_module

    class FakeAdapter:
        name = "anr_plugin_auto_mosaics"

        def __init__(self, paths, config):
            pass

        def process(self, source: Path, target: Path, options: dict) -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    monkeypatch.setattr(builder_module, "AnrAutoMosaicsAdapter", FakeAdapter)
    root = tmp_path / "publish"
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, "task-001")
    TaskRepository.create(task_paths, title="mosaic")
    source = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "white").save(source)
    task_paths.selection_dirs["all"].mkdir(parents=True, exist_ok=True)
    (task_paths.selection_dirs["all"] / "source.png").write_bytes(source.read_bytes())
    TaskRepository.save(
        task_paths,
        TaskConfig(
            task_id="task-001",
            title="mosaic",
            processing=ProcessingConfig(
                operations={
                    "mosaic": OperationConfig(
                        enabled=True,
                        adapter="anr_plugin_auto_mosaics",
                    )
                }
            ),
        ),
    )

    result = PackageBuilder().build(root, "task-001")

    assert result.output_paths["all"].joinpath("source.png").is_file()
