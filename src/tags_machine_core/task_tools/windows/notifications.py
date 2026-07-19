import ctypes
import sys


def show_error(title: str, message: str) -> None:
    """显示 Windows 错误提示；非 Windows 平台输出到标准错误。"""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        return
    print(f"{title}：{message}", file=sys.stderr)
