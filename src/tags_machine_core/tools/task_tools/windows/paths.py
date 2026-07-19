from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WindowsTaskToolPaths:
    app_dir: Path
    sendto_dir: Path

    @property
    def install_manifest(self) -> Path:
        return self.app_dir / "install.json"

    @property
    def bootstrap_script(self) -> Path:
        return self.app_dir / "bootstrap.ps1"

    @property
    def log_dir(self) -> Path:
        return self.app_dir / "logs"

    @classmethod
    def discover(cls) -> "WindowsTaskToolPaths":
        local_app_data = os.environ.get("LOCALAPPDATA")
        app_data = os.environ.get("APPDATA")
        if not local_app_data or not app_data:
            raise RuntimeError(
                "缺少 LOCALAPPDATA 或 APPDATA，无法安装 Windows 任务工具"
            )
        return cls(
            app_dir=Path(local_app_data) / "PromptAtelier" / "TaskTools",
            sendto_dir=Path(app_data) / "Microsoft" / "Windows" / "SendTo",
        )
