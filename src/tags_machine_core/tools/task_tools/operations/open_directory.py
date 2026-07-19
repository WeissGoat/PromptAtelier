import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..models import TaskContextSet

if TYPE_CHECKING:
    from ..runner import OperationResult


DirectoryOpener = Callable[[Path], None]


def open_directory_with_explorer(path: Path) -> None:
    """使用 Windows 资源管理器打开目录。"""
    if sys.platform != "win32":
        raise RuntimeError("打开关联目录当前只支持 Windows")
    subprocess.Popen(["explorer.exe", str(path)], close_fds=True)


def open_related_directories(
    contexts: TaskContextSet,
    *,
    role: str,
    opener: DirectoryOpener = open_directory_with_explorer,
) -> "OperationResult":
    """打开指定角色的全部存在目录，并保持首次出现顺序。"""
    paths = contexts.existing_paths(role)
    if not paths:
        from ..runner import OperationUnavailableError

        raise OperationUnavailableError(f"没有可用的 {role} 目录")
    for path in paths:
        opener(path)

    from ..runner import OperationResult

    return OperationResult(operation_id=f"open_{role}_directory", affected_paths=paths)
