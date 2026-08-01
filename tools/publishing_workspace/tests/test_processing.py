from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from publishing_workspace.processing import ImageProcessingPipeline
from publishing_workspace.processing.models import ProcessingResult
from publishing_workspace.tasks import OperationConfig, ProcessingConfig
from publishing_workspace.png_metadata import read_png_text_chunks


def _image(path: Path, color: str = "white", text: dict[str, str] | None = None) -> Path:
    image = Image.new("RGB", (8, 8), color=color)
    if text:
        info = PngImagePlugin.PngInfo()
        for key, value in text.items():
            info.add_text(key, value)
        image.save(path, pnginfo=info)
    else:
        image.save(path)
    return path


def test_strip_metadata_removes_png_text_and_preserves_dimensions(tmp_path: Path):
    source = _image(
        tmp_path / "source.png",
        text={"prompt": "secret", "seed": "42"},
    )
    output = tmp_path / "output.png"

    result = ImageProcessingPipeline().process(
        source,
        output,
        ProcessingConfig(profile="pixiv_default"),
    )

    assert isinstance(result, ProcessingResult)
    assert Image.open(output).size == Image.open(source).size
    assert read_png_text_chunks(output) == {}


def test_processing_cache_reuses_same_input_and_config(tmp_path: Path):
    source = _image(tmp_path / "source.png")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    pipeline = ImageProcessingPipeline(cache_root=tmp_path / "cache")
    config = ProcessingConfig(profile="pixiv_default")

    first_result = pipeline.process(source, first, config)
    second_result = pipeline.process(source, second, config)

    assert first_result.cache_hit is False
    assert second_result.cache_hit is True
    assert first.read_bytes() == second.read_bytes()


def test_mosaic_without_adapter_fails_before_output(tmp_path: Path):
    with pytest.raises(ValueError, match="mosaic.*adapter"):
        ImageProcessingPipeline().process(
            _image(tmp_path / "source.png"),
            tmp_path / "output.png",
            ProcessingConfig(
                operations={"mosaic": OperationConfig(enabled=True)},
            ),
        )
