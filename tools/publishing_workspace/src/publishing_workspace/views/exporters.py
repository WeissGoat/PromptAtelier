from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from ..models import ViewEntry


_SHORTCUT_COM_PATH_LIMIT = 240


class ViewExporter(Protocol):
    type: str
    version: str

    def output_paths(self, view: ViewEntry, target_root: Path) -> list[Path]: ...

    def export_view(self, view: ViewEntry, target_root: Path) -> list[Path]: ...


class NeeViewPlaylistExporter:
    type = "neev"
    version = "1"

    def output_paths(self, view: ViewEntry, target_root: Path) -> list[Path]:
        return [_leaf_file(target_root, view.path, ".nvpls")]

    def export_view(self, view: ViewEntry, target_root: Path) -> list[Path]:
        output = self.output_paths(view, target_root)[0]
        payload = {
            "Format": "NeeView.Playlist/2.0.0",
            "Items": [{"Path": item.source_path} for item in view.items],
        }
        _write_text_atomic(
            output,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        return [output]


class WindowsShortcutExporter:
    type = "windows_shortcut"
    version = "1"

    def output_paths(self, view: ViewEntry, target_root: Path) -> list[Path]:
        directory = _leaf_directory(target_root, view.path)
        return [
            directory / f"{index:04d}_{_safe_filename(item.display_name)}.lnk"
            for index, item in enumerate(view.items, start=1)
        ]

    def export_view(self, view: ViewEntry, target_root: Path) -> list[Path]:
        if os.name != "nt":
            raise RuntimeError("WindowsShortcutExporter 只能在 Windows 上运行")
        outputs = self.output_paths(view, target_root)
        target_root.mkdir(parents=True, exist_ok=True)
        temporary_parent = _shortcut_temporary_parent(target_root)
        with tempfile.TemporaryDirectory(
            prefix=".shortcut-",
            dir=temporary_parent,
        ) as temporary:
            temporary_root = Path(temporary)
            for item, output in zip(view.items, outputs, strict=True):
                output.parent.mkdir(parents=True, exist_ok=True)
                _create_windows_shortcut(output, Path(item.source_path), temporary_root)
        return outputs


def _create_windows_shortcut(output: Path, target: Path, temporary_root: Path) -> None:
    script = (
        "$ErrorActionPreference='Stop';"
        "$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TMC_SHORTCUT_OUTPUT);"
        "$shortcut.TargetPath=$env:TMC_SHORTCUT_TARGET;"
        "$shortcut.WorkingDirectory=(Split-Path -Parent $env:TMC_SHORTCUT_TARGET);"
        "$shortcut.Save()"
    )
    # WScript.Shell 创建快捷方式时仍受旧式路径长度限制，先在同卷短路径创建再移动。
    temporary_output = temporary_root / f"{uuid4().hex}.lnk"
    environment = os.environ.copy()
    environment["TMC_SHORTCUT_OUTPUT"] = str(temporary_output)
    environment["TMC_SHORTCUT_TARGET"] = str(target)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            env=environment,
        )
        os.replace(temporary_output, output)
    except OSError as exc:
        raise RuntimeError(f"创建快捷方式失败：{output} -> {target}：{exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"创建快捷方式失败：{output} -> {target}：{detail}") from exc


def _shortcut_temporary_parent(target_root: Path) -> Path:
    resolved = target_root.resolve()
    sample_directory = ".shortcut-xxxxxxxx"
    sample_file = f"{'x' * 32}.lnk"
    for parent in (resolved, *resolved.parents):
        sample = parent / sample_directory / sample_file
        if len(str(sample)) <= _SHORTCUT_COM_PATH_LIMIT:
            return parent
    raise RuntimeError(f"找不到可用的同卷快捷方式临时目录：{target_root}")


def _leaf_file(root: Path, path: list[str], suffix: str) -> Path:
    if not path:
        raise ValueError("分类视图 path 不能为空")
    parent = root.joinpath(*(_safe_segment(item) for item in path[:-1]))
    return parent / f"{_safe_segment(path[-1])}{suffix}"


def _leaf_directory(root: Path, path: list[str]) -> Path:
    if not path:
        raise ValueError("分类视图 path 不能为空")
    return root.joinpath(*(_safe_segment(item) for item in path))


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip().rstrip(".")
    return cleaned or "unknown"


def _safe_filename(value: str) -> str:
    name = _safe_segment(Path(value).name)
    return name[:180]


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
