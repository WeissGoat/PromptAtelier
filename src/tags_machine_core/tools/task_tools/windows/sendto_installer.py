from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
from pathlib import Path
import re
from typing import Any

from ..config import OperationPlacement, TaskToolsConfig
from ..registry import OperationRegistry
from .paths import WindowsTaskToolPaths


@dataclass(frozen=True, slots=True)
class SendToInstallResult:
    app_dir: Path
    sendto_entries: list[Path]
    manifest_path: Path


class SendToInstaller:
    def __init__(self, *, paths: WindowsTaskToolPaths | None = None):
        self.paths = paths or WindowsTaskToolPaths.discover()

    def install(
        self,
        *,
        project_root: Path,
        pythonw_path: Path,
        config_path: Path | None,
        registry: OperationRegistry,
        config: TaskToolsConfig,
    ) -> SendToInstallResult:
        install: dict[str, Any] = {
            "schema": "prompt-atelier.task-tools-install/v1",
            "project_root": str(project_root.resolve()),
            "pythonw_path": str(pythonw_path.resolve()),
            "config_path": str(config_path.resolve()) if config_path else None,
            "managed_sendto_entries": [],
        }
        return self._write_install(install=install, registry=registry, config=config)

    def sync(
        self,
        *,
        registry: OperationRegistry,
        config: TaskToolsConfig,
        config_path: Path | None = None,
    ) -> SendToInstallResult:
        install = self._read_manifest(required=True)
        if config_path is not None:
            install["config_path"] = str(config_path.resolve())
        return self._write_install(install=install, registry=registry, config=config)

    def uninstall(self) -> list[Path]:
        install = self._read_manifest(required=False)
        removed: list[Path] = []
        for name in _managed_entry_names(install):
            target = self.paths.sendto_dir / name
            if target.is_file():
                target.unlink()
                removed.append(target)
        for target in (self.paths.bootstrap_script, self.paths.install_manifest):
            if target.is_file():
                target.unlink()
                removed.append(target)
        return removed

    def _write_install(
        self,
        *,
        install: dict[str, Any],
        registry: OperationRegistry,
        config: TaskToolsConfig,
    ) -> SendToInstallResult:
        old = self._read_manifest(required=False)
        for name in _managed_entry_names(old):
            target = self.paths.sendto_dir / name
            if target.is_file():
                target.unlink()

        self.paths.app_dir.mkdir(parents=True, exist_ok=True)
        self.paths.sendto_dir.mkdir(parents=True, exist_ok=True)
        self.paths.log_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(
            self.paths.bootstrap_script,
            _read_packaged_text("bootstrap.ps1"),
            encoding="utf-8-sig",
        )

        entries: list[Path] = []
        for spec in registry.all():
            override = config.operations[spec.id]
            if not override.enabled or override.placement not in {
                OperationPlacement.QUICK,
                OperationPlacement.BOTH,
            }:
                continue
            label = _safe_filename(override.label or spec.default_label)
            entry = self.paths.sendto_dir / f"Refactor - {label}.vbs"
            _write_atomic(
                entry,
                _render_sendto_entry(
                    bootstrap_path=self.paths.bootstrap_script,
                    mode="run",
                    operation_id=spec.id,
                ),
                encoding="utf-16",
            )
            entries.append(entry)

        launcher = self.paths.sendto_dir / "Refactor 工具.vbs"
        _write_atomic(
            launcher,
            _render_sendto_entry(
                bootstrap_path=self.paths.bootstrap_script,
                mode="launcher",
                operation_id="",
            ),
            encoding="utf-16",
        )
        entries.append(launcher)

        install["managed_sendto_entries"] = [entry.name for entry in entries]
        _write_atomic(
            self.paths.install_manifest,
            json.dumps(install, ensure_ascii=False, indent=2) + "\n",
        )
        return SendToInstallResult(
            app_dir=self.paths.app_dir,
            sendto_entries=entries,
            manifest_path=self.paths.install_manifest,
        )

    def _read_manifest(self, *, required: bool) -> dict[str, Any]:
        if not self.paths.install_manifest.is_file():
            if required:
                raise RuntimeError("任务工具尚未安装，请先执行 install-sendto")
            return {}
        try:
            value = json.loads(self.paths.install_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("任务工具安装清单读取失败") from exc
        if not isinstance(value, dict):
            raise RuntimeError("任务工具安装清单格式错误")
        return value


def _managed_entry_names(install: dict[str, Any]) -> list[str]:
    value = install.get("managed_sendto_entries", [])
    if not isinstance(value, list):
        raise RuntimeError("任务工具安装清单中的 managed_sendto_entries 格式错误")
    result: list[str] = []
    for item in value:
        name = Path(str(item)).name
        if name and name not in result:
            result.append(name)
    return result


def _write_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding=encoding)
    temporary.replace(path)


def _safe_filename(value: str) -> str:
    result = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    if not result:
        raise ValueError("SendTo 显示名称不能为空")
    return result


def _read_packaged_text(name: str) -> str:
    package = resources.files("tags_machine_core.tools.task_tools.windows")
    return package.joinpath(name).read_text(encoding="utf-8")


def _render_sendto_entry(
    *,
    bootstrap_path: Path,
    mode: str,
    operation_id: str,
) -> str:
    template = _read_packaged_text("sendto_entry.vbs")
    operation_argument = (
        f' -OperationId ""{operation_id.replace(chr(34), chr(34) * 2)}""'
        if operation_id
        else ""
    )
    return (
        template.replace("{bootstrap_path}", str(bootstrap_path).replace('"', '""'))
        .replace("{mode}", mode)
        .replace("{operation_argument}", operation_argument)
    )
