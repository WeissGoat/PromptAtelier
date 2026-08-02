from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

from ...config import MosaicIntegrationConfig, WorkspacePaths
from .constants import (
    MODEL_STATUS_CHECKSUM_MISMATCH,
    MODEL_STATUS_MISSING,
    MODEL_STATUS_READY,
)


@dataclass(frozen=True)
class ModelStatus:
    name: str
    target: Path
    expected_sha256: str
    actual_sha256: str | None
    state: str

    @property
    def exists(self) -> bool:
        return self.actual_sha256 is not None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "name": self.name,
            "target": str(self.target),
            "exists": self.exists,
            "actual_sha256": self.actual_sha256,
            "expected_sha256": self.expected_sha256,
            "status": self.state,
        }


class MosaicModelManager:
    def __init__(self, paths: WorkspacePaths, config: MosaicIntegrationConfig):
        self.paths = paths
        self.config = config
        self.model_root = paths.resolve_mosaic_model_root(config.model_root)

    def status(self) -> list[ModelStatus]:
        return [
            self._status(name, model)
            for name, model in sorted(self.config.models.items())
        ]

    def install(self, source: str | Path | None = None) -> list[ModelStatus]:
        source_root = Path(source).expanduser().resolve() if source is not None else None
        for name, model in sorted(self.config.models.items()):
            current = self._status(name, model)
            if current.state == MODEL_STATUS_READY:
                continue

            relative = self._safe_relative_path(model.filename)
            if source_root is not None:
                input_path = (source_root / relative).resolve()
                if not input_path.is_file():
                    raise ValueError(f"模型源文件不存在：{input_path}")
                self._install_file(input_path, current.target, model.sha256)
            else:
                self._download_file(model.url, current.target, model.sha256)
        return self.status()

    def _status(self, name: str, model) -> ModelStatus:
        target = self._target_path(model.filename)
        if not target.is_file():
            return ModelStatus(
                name=name,
                target=target,
                expected_sha256=model.sha256,
                actual_sha256=None,
                state=MODEL_STATUS_MISSING,
            )
        actual = _sha256(target)
        return ModelStatus(
            name=name,
            target=target,
            expected_sha256=model.sha256,
            actual_sha256=actual,
            state=MODEL_STATUS_READY if actual == model.sha256 else MODEL_STATUS_CHECKSUM_MISMATCH,
        )

    def _target_path(self, filename: str) -> Path:
        relative = self._safe_relative_path(filename)
        root = self.model_root.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"模型文件路径必须位于 model_root 内：{filename}") from exc
        return target

    def _safe_relative_path(self, filename: str) -> Path:
        relative = Path(str(filename))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"模型文件名必须是 model_root 下的相对路径：{filename}")
        return relative

    def _install_file(self, source: Path, target: Path, expected: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, temporary, length=1024 * 1024)
        try:
            _replace_verified(temporary_path, target, expected)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _download_file(self, url: str, target: Path, expected: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "publishing-workspace/0.1"})
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with urlopen(request, timeout=120) as response:
                    shutil.copyfileobj(response, temporary, length=1024 * 1024)
                _replace_verified(temporary_path, target, expected)
            finally:
                temporary_path.unlink(missing_ok=True)


def _replace_verified(temporary: Path, target: Path, expected: str) -> None:
    actual = _sha256(temporary)
    if actual != expected:
        raise ValueError(
            f"模型 SHA-256 校验失败：{target.name}，expected={expected}，actual={actual}"
        )
    os.replace(temporary, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ModelStatus", "MosaicModelManager"]
