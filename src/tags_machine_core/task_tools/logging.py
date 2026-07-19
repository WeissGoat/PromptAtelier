import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tags_machine_core.logging_config import normalize_log_level


def default_task_tool_log_dir() -> Path:
    """返回 Windows LocalAppData 下的任务工具日志目录。"""
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "PromptAtelier" / "TaskTools" / "logs"


def configure_task_tool_file_logging(
    log_dir: Path | None = None,
    level: str = "error",
) -> logging.Logger:
    """配置任务工具的轮转文件日志。"""
    resolved_log_dir = (log_dir or default_task_tool_log_dir()).resolve()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tags_machine_core.task_tools")
    level_number = normalize_log_level(level)
    logger.setLevel(level_number)
    logger.propagate = False
    target = resolved_log_dir / "task-tools.log"
    for handler in logger.handlers:
        if getattr(handler, "task_tools_target", None) == target:
            handler.setLevel(level_number)
            return logger
    handler = RotatingFileHandler(
        target,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.task_tools_target = target
    handler.setLevel(level_number)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger
