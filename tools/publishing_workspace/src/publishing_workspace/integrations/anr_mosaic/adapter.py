from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image

from ...config import MosaicIntegrationConfig, WorkspacePaths
from ...logging import get_logger
from .detector import YoloDetector, YoloSamDetector
from .model_manager import MosaicModelManager
from .mosaics import ImageMosaicProcessor
from .settings import MosaicSettings


logger = get_logger(__name__)


class AnrAutoMosaicsAdapter:
    name = "anr_plugin_auto_mosaics"

    def __init__(
        self,
        paths: WorkspacePaths,
        config: MosaicIntegrationConfig,
        emoji_dir: str | Path | None = None,
    ):
        self.paths = paths
        self.config = config
        self.models = MosaicModelManager(paths, config)
        self.emoji_dir = (
            Path(emoji_dir).expanduser().resolve()
            if emoji_dir is not None
            else Path(__file__).resolve().parents[4]
            / "assets"
            / "anr_plugin_auto_mosaics"
            / "emoji"
        )
        self._detectors: dict[str, Any] = {}
        self._verified_models: set[str] = set()

    def validate(self, options: dict[str, Any]) -> None:
        settings = MosaicSettings.from_options(options, default_emoji_dir=self.emoji_dir)
        for part in settings.unsupported_detector_parts:
            logger.warning("当前检测器不支持部位 %s，已忽略", part)
        if settings.detector_labels:
            for model_name in self._required_models(settings.detector):
                self._require_model(model_name)

    def process(self, source: Path, target: Path, options: dict[str, Any]) -> None:
        settings = MosaicSettings.from_options(options, default_emoji_dir=self.emoji_dir)
        self.validate(options)
        for part in settings.unsupported_detector_parts:
            logger.warning("当前检测器不支持部位 %s，已忽略", part)

        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".mosaic-", dir=str(target.parent)) as temporary:
            temporary_root = Path(temporary)
            mask_path = temporary_root / "mask.png"
            if settings.detector_labels:
                detector = self._detector(settings.detector)
                detector.create_mask(source, mask_path, settings.detector_labels)
            else:
                _write_empty_mask(source, mask_path)
            ImageMosaicProcessor().process(source, mask_path, target, settings)

    def _detector(self, detector_name: str):
        cached = self._detectors.get(detector_name)
        if cached is not None:
            return cached

        if detector_name == "yolo":
            yolo_path = self._require_model("yolo")
            detector = YoloDetector(yolo_path)
        elif detector_name == "yolo_sam":
            yolo_path = self._require_model("yolo")
            sam_path = self._require_model("sam")
            detector = YoloSamDetector(yolo_path, sam_path)
        else:
            raise ValueError(f"不支持的检测器：{detector_name}")
        self._detectors[detector_name] = detector
        return detector

    @staticmethod
    def _required_models(detector_name: str) -> tuple[str, ...]:
        if detector_name == "yolo":
            return ("yolo",)
        if detector_name == "yolo_sam":
            return ("yolo", "sam")
        raise ValueError(f"不支持的检测器：{detector_name}")

    def _require_model(self, name: str) -> Path:
        if name in self._verified_models:
            return self.models.model_root / self.config.models[name].filename
        if name not in self.config.models:
            raise ValueError(f"mosaic 未配置模型：{name}")
        status = {item.name: item for item in self.models.status()}.get(name)
        if status is None or status.state != "ready":
            state = status.state if status is not None else "missing"
            target = status.target if status is not None else self.models.model_root
            raise ValueError(f"mosaic 模型不可用：{name}，status={state}，target={target}")
        self._verified_models.add(name)
        return status.target


def _write_empty_mask(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        mask = Image.new("L", image.size, 0)
    mask.save(target, format="PNG")


__all__ = ["AnrAutoMosaicsAdapter"]
