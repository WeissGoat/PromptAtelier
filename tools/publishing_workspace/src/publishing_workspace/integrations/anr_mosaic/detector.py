from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

from ...logging import get_logger


logger = get_logger(__name__)


class MosaicDetector(Protocol):
    def create_mask(
        self,
        source: Path,
        target: Path,
        labels: tuple[str, ...],
    ) -> None: ...


class YoloDetector:
    def __init__(self, model_path: Path):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "YOLO 打码需要安装 mosaic extra：uv sync --extra mosaic"
            ) from exc
        self.model = YOLO(str(model_path))

    def create_mask(self, source: Path, target: Path, labels: tuple[str, ...]) -> None:
        if not labels:
            _write_empty_mask(source, target)
            return

        results = self.model(str(source), verbose=False)
        wanted = set(labels)
        boxes: list[tuple[float, float, float, float]] = []
        for result in results:
            names = result.names
            result_boxes = getattr(result, "boxes", None)
            if result_boxes is None:
                continue
            for index, xyxy in enumerate(result_boxes.xyxy.tolist()):
                class_id = int(result_boxes.cls[index].item())
                label = names[class_id] if isinstance(names, dict) else names[class_id]
                if label in wanted and len(xyxy) == 4:
                    boxes.append(tuple(float(value) for value in xyxy))
        _write_rectangle_mask(source, target, boxes)
        logger.info("YOLO 检测到 %d 个待处理区域：%s", len(boxes), ", ".join(labels))


class YoloSamDetector:
    def __init__(self, yolo_model: Path, sam_model: Path):
        try:
            from .sam_detector import MaskProcessor
        except ImportError as exc:
            raise RuntimeError(
                "YOLO+SAM 打码需要安装 mosaic extra：uv sync --extra mosaic"
            ) from exc
        self.processor = MaskProcessor(str(yolo_model), str(sam_model))

    def create_mask(self, source: Path, target: Path, labels: tuple[str, ...]) -> None:
        if not labels:
            _write_empty_mask(source, target)
            return
        self.processor.generate_combined_mask(
            str(source),
            str(target),
            filter=",".join(labels),
        )


def _write_empty_mask(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        mask = Image.new("L", image.size, 0)
    target.parent.mkdir(parents=True, exist_ok=True)
    mask.save(target, format="PNG")


def _write_rectangle_mask(
    source: Path,
    target: Path,
    boxes: list[tuple[float, float, float, float]],
) -> None:
    with Image.open(source) as image:
        mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    for x1, y1, x2, y2 in boxes:
        draw.rectangle(
            (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
            fill=255,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    mask.save(target, format="PNG")


__all__ = ["MosaicDetector", "YoloDetector", "YoloSamDetector"]
