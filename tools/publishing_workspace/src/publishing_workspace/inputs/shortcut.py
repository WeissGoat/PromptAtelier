from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from ..models import ImportedItem, SelectionSet
from .base import InputContext


class ShortcutResolutionError(RuntimeError):
    """Windows 快捷方式无法解析。"""


def resolve_shortcut(path: Path) -> Path:
    if path.suffix.casefold() != ".lnk":
        return path.resolve()
    script = (
        "$ErrorActionPreference='Stop';"
        "$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TMC_SHORTCUT_PATH);"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "Write-Output $shortcut.TargetPath"
    )
    # WScript.Shell 打开快捷方式时仍受旧式路径长度限制，复制到短临时路径后读取。
    with tempfile.TemporaryDirectory(prefix="publishing-workspace-shortcut-") as temporary:
        temporary_path = Path(temporary) / f"{uuid4().hex}.lnk"
        try:
            shutil.copyfile(path, temporary_path)
            environment = os.environ.copy()
            environment["TMC_SHORTCUT_PATH"] = str(temporary_path)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ShortcutResolutionError(f"无法解析快捷方式：{path}：{exc}") from exc
    target = result.stdout.strip()
    if not target:
        raise ShortcutResolutionError(f"快捷方式没有目标路径：{path}")
    return Path(target).expanduser().resolve()


def imported_item_from_path(
    value: str | Path,
    *,
    source_type: str,
    source_ref: str,
    source_order: int,
    context: InputContext,
) -> ImportedItem:
    source = Path(value).expanduser()
    if not source.is_absolute():
        source = Path(source_ref).parent / source
    source = source.resolve()
    warnings: list[str] = []
    try:
        resolved = resolve_shortcut(source)
    except ShortcutResolutionError as exc:
        if context.strict:
            raise
        resolved = None
        warnings.append(str(exc))

    if resolved is not None and not resolved.is_file():
        message = f"图片不存在：{resolved}"
        if context.strict:
            raise FileNotFoundError(message)
        warnings.append(message)
        resolved = None
    elif resolved is not None and not context.supports_image(resolved):
        message = f"不支持的图片扩展名：{resolved}"
        if context.strict:
            raise ValueError(message)
        warnings.append(message)
        resolved = None

    return ImportedItem(
        source_path=str(source),
        resolved_path=str(resolved) if resolved else None,
        source_type=source_type,
        source_ref=source_ref,
        source_order=source_order,
        display_name=(resolved or source).name,
        warnings=warnings,
    )


class ShortcutInputAdapter:
    type = "shortcut"

    def probe(self, source: Path) -> bool:
        return source.is_file() and source.suffix.casefold() == ".lnk"

    def load(self, source: Path, context: InputContext) -> SelectionSet:
        item = imported_item_from_path(
            source,
            source_type=self.type,
            source_ref=str(source),
            source_order=0,
            context=context,
        )
        return SelectionSet(
            source_type=self.type,
            source_ref=str(source),
            items=[item],
            warnings=list(item.warnings),
        )
