import json
from pathlib import Path

import pytest

from tags_machine_core.tools.task_tools.config import (
    OperationPlacement,
    load_task_tools_config,
)
from tags_machine_core.tools.task_tools.registry import build_default_registry
from tags_machine_core.tools.task_tools.windows.paths import WindowsTaskToolPaths
from tags_machine_core.tools.task_tools.windows.sendto_installer import SendToInstaller


def _installer(tmp_path: Path) -> tuple[SendToInstaller, WindowsTaskToolPaths]:
    paths = WindowsTaskToolPaths(
        app_dir=tmp_path / "local" / "PromptAtelier" / "TaskTools",
        sendto_dir=tmp_path / "sendto",
    )
    return SendToInstaller(paths=paths), paths


def test_path_discovery_requires_windows_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    with pytest.raises(RuntimeError, match="缺少 LOCALAPPDATA 或 APPDATA"):
        WindowsTaskToolPaths.discover()


def test_install_creates_quick_entries_launcher_and_manifest(tmp_path: Path) -> None:
    installer, paths = _installer(tmp_path)
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)

    result = installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "refactor" / ".venv" / "Scripts" / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )

    names = [path.name for path in result.sendto_entries]
    assert names == [
        "Refactor - 打开 Action 目录.vbs",
        "Refactor - 打开 Artist 目录.vbs",
        "Refactor 工具.vbs",
    ]
    manifest = json.loads(paths.install_manifest.read_text(encoding="utf-8"))
    assert manifest["managed_sendto_entries"] == names
    assert paths.bootstrap_script.is_file()
    assert paths.log_dir.is_dir()
    assert paths.bootstrap_script.read_bytes().startswith(b"\xef\xbb\xbf")
    bootstrap = paths.bootstrap_script.read_text(encoding="utf-8-sig")
    assert '$pythonPath = Join-Path' in bootstrap
    assert "& $pythonPath @arguments" in bootstrap
    assert '[Parameter()][string]$OperationId' in bootstrap
    assert 'Position = 0, ValueFromRemainingArguments = $true' in bootstrap
    assert result.sendto_entries[0].read_bytes().startswith(b"\xff\xfe")
    assert "open_action_directory" in result.sendto_entries[0].read_text(encoding="utf-16")
    launcher_text = result.sendto_entries[-1].read_text(encoding="utf-16")
    assert '-Mode ""launcher""' in launcher_text
    assert "-OperationId" not in launcher_text


def test_install_respects_quick_placement_and_safe_custom_label(tmp_path: Path) -> None:
    installer, _ = _installer(tmp_path)
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    config.operations["open_action_directory"].label = 'Action: "Main"'
    config.operations["open_artist_directory"].placement = OperationPlacement.LAUNCHER

    result = installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )

    assert [path.name for path in result.sendto_entries] == [
        "Refactor - Action_ _Main_.vbs",
        "Refactor 工具.vbs",
    ]


def test_sync_removes_only_previous_managed_entries(tmp_path: Path) -> None:
    installer, paths = _installer(tmp_path)
    paths.sendto_dir.mkdir(parents=True)
    user_file = paths.sendto_dir / "ct.blackboard.run_actions.bat"
    user_file.write_text("keep", encoding="utf-8")
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )
    config.operations["open_artist_directory"].placement = OperationPlacement.LAUNCHER

    result = installer.sync(registry=registry, config=config)

    assert user_file.read_text(encoding="utf-8") == "keep"
    assert not (paths.sendto_dir / "Refactor - 打开 Artist 目录.vbs").exists()
    assert [path.name for path in result.sendto_entries] == [
        "Refactor - 打开 Action 目录.vbs",
        "Refactor 工具.vbs",
    ]


def test_sync_can_persist_new_config_path(tmp_path: Path) -> None:
    installer, paths = _installer(tmp_path)
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )
    config_path = tmp_path / "task-tools.yaml"

    installer.sync(registry=registry, config=config, config_path=config_path)

    manifest = json.loads(paths.install_manifest.read_text(encoding="utf-8"))
    assert manifest["config_path"] == str(config_path.resolve())


def test_uninstall_preserves_unmanaged_sendto_items(tmp_path: Path) -> None:
    installer, paths = _installer(tmp_path)
    paths.sendto_dir.mkdir(parents=True)
    user_file = paths.sendto_dir / "ct.keep.bat"
    user_file.write_text("keep", encoding="utf-8")
    registry = build_default_registry()
    config = load_task_tools_config(None, registry=registry)
    result = installer.install(
        project_root=tmp_path / "refactor",
        pythonw_path=tmp_path / "pythonw.exe",
        config_path=None,
        registry=registry,
        config=config,
    )

    removed = installer.uninstall()

    assert user_file.read_text(encoding="utf-8") == "keep"
    assert all(not path.exists() for path in result.sendto_entries)
    assert paths.bootstrap_script in removed
    assert not paths.install_manifest.exists()


def test_uninstall_ignores_manifest_path_traversal(tmp_path: Path) -> None:
    installer, paths = _installer(tmp_path)
    paths.app_dir.mkdir(parents=True)
    paths.sendto_dir.mkdir(parents=True)
    outside = tmp_path / "outside.vbs"
    outside.write_text("keep", encoding="utf-8")
    paths.install_manifest.write_text(
        json.dumps({"managed_sendto_entries": ["../outside.vbs"]}),
        encoding="utf-8",
    )

    installer.uninstall()

    assert outside.read_text(encoding="utf-8") == "keep"
