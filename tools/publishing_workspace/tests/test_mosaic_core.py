from __future__ import annotations

from pathlib import Path

from PIL import Image

from publishing_workspace.config import MosaicIntegrationConfig
from publishing_workspace.integrations.anr_mosaic.mosaics import ImageMosaicProcessor
from publishing_workspace.integrations.anr_mosaic.settings import MosaicSettings


def _settings(method: str) -> MosaicSettings:
    return MosaicSettings.from_options(
        {"method": method, "parts": ["penis"]},
        default_emoji_dir=Path("emoji"),
    )


def test_mosaic_settings_normalizes_supported_options():
    settings = MosaicSettings.from_options(
        {
            "detector": "yolo",
            "method": "solid",
            "parts": ["penis", "female_nipple", "anus"],
            "color": [1, 2, 3],
        },
        default_emoji_dir=Path("emoji"),
    )

    assert settings.detector == "yolo"
    assert settings.parts == ("penis", "female_nipple", "anus")
    assert settings.detector_labels == ("penis", "nipple_f")
    assert settings.unsupported_detector_parts == ("anus",)
    assert settings.color == (1, 2, 3)


def test_solid_mosaic_writes_target_and_preserves_dimensions(tmp_path: Path):
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    target = tmp_path / "nested" / "target.png"
    Image.new("RGB", (16, 12), (10, 20, 30)).save(source)
    mask_image = Image.new("L", (16, 12), 0)
    for x in range(4, 12):
        for y in range(3, 9):
            mask_image.putpixel((x, y), 255)
    mask_image.save(mask)

    ImageMosaicProcessor().process(source, mask, target, _settings("solid"))

    assert target.is_file()
    assert Image.open(target).size == (16, 12)
    assert Image.open(target).getpixel((0, 0)) == (10, 20, 30)
    assert Image.open(target).getpixel((8, 6)) == (128, 128, 128)
    assert Image.open(source).getpixel((8, 6)) == (10, 20, 30)


def test_blur_mosaic_does_not_require_heavy_detector_imports(tmp_path: Path):
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    target = tmp_path / "target.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(source)
    Image.new("L", (4, 4), 255).save(mask)

    ImageMosaicProcessor().process(source, mask, target, _settings("blur"))

    assert target.is_file()


def test_mosaic_config_import_does_not_load_optional_detector_modules():
    assert MosaicIntegrationConfig().provider == "anr_plugin_auto_mosaics"
