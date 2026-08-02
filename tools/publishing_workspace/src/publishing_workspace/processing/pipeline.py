from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from ..tasks.models import OperationConfig, ProcessingConfig
from .cache import ProcessingCache
from .models import ProcessingResult
from .operations import OperationRegistry, default_operation_registry


class ImageProcessingPipeline:
    def __init__(
        self,
        *,
        cache_root: str | Path | None = None,
        registry: OperationRegistry | None = None,
    ):
        self.cache = ProcessingCache(cache_root) if cache_root is not None else None
        self.registry = registry or default_operation_registry()

    def process(
        self,
        source: str | Path,
        target: str | Path,
        config: ProcessingConfig,
    ) -> ProcessingResult:
        source = Path(source)
        target = Path(target)
        if not source.is_file():
            raise ValueError(f"处理输入图片不存在：{source}")
        operations = list(config.operations.items())
        resolved = [
            (operation_type, operation_config, self.registry.get(operation_type))
            for operation_type, operation_config in operations
            if operation_config.enabled
        ]
        for operation_type, operation_config, operation in resolved:
            options = _operation_options(operation_config)
            operation.validate(options)

        input_hash = _sha256(source)
        cache_path = None
        if self.cache is not None:
            cache_operations = [
                (
                    name,
                    _cache_operation_config(name, operation_config, operation),
                )
                for name, operation_config, operation in resolved
            ]
            cache_key = self.cache.key(
                input_hash,
                config.profile,
                cache_operations,
            )
            cache_path = self.cache.path(cache_key, source.suffix.casefold())
            if cache_path.is_file():
                self.cache.copy_to(cache_path, target)
                return ProcessingResult(
                    output_path=str(target),
                    cache_hit=True,
                    skipped_operations=[
                        name for name, operation_config in operations
                        if not operation_config.enabled
                    ],
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".processing-", dir=str(target.parent)) as temporary:
            temporary_root = Path(temporary)
            current = source
            processed: list[str] = []
            skipped = [name for name, item in operations if not item.enabled]
            for index, (operation_type, operation_config, operation) in enumerate(resolved):
                output = temporary_root / f"step-{index}{source.suffix.casefold()}"
                operation.process(current, output, _operation_options(operation_config))
                _verify_image(output)
                current = output
                processed.append(operation_type)
            if not resolved:
                shutil.copy2(source, target)
            else:
                shutil.copy2(current, target)
            _verify_image(target)
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_cache = cache_path.with_name(f".{cache_path.name}.tmp")
                shutil.copy2(target, temporary_cache)
                os.replace(temporary_cache, cache_path)
        return ProcessingResult(
            output_path=str(target),
            cache_hit=False,
            processed_operations=processed,
            skipped_operations=skipped,
        )


def _operation_options(config: OperationConfig) -> dict:
    options = dict(config.options)
    if config.adapter:
        options["adapter"] = config.adapter
    return options


def _cache_operation_config(
    name: str,
    config: OperationConfig,
    operation,
) -> OperationConfig:
    if name != "mosaic":
        return config
    implementation_version = str(getattr(operation, "version", "1"))
    return config.model_copy(
        update={"version": f"{implementation_version}:{config.version}"}
    )


def _verify_image(path: Path) -> None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError) as exc:
        raise ValueError(f"处理结果不是可读取图片：{path}：{exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
