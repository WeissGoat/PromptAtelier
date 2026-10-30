"""启动期本地生成服装节点库（design/服装）。

``动作改2/tools/extract_action_clothes.py`` 把动作节点里的服装标签抽出来，清洗路由成
独立服装节点（schema ``tags-machine.clothing/v1``），正是 refactor 里 ``role=clothing``
池的数据源（见 ``nodes/role_paths.py`` 的 ``"clothing": ("服装", ...)``）。

这里只做**本地增量生成**：不 pull、不提交、不改动任何 git 状态。导出脚本本身幂等
（实测重跑 465 个节点全部 skip），所以启动时先比时间戳——动作库没有新的 tags.txt /
classify.yaml 就跳过，一秒内返回；有变化才重跑（约 9s）。

生成失败只告警，不阻塞 Web 启动；锁用独立文件，不复用分类视图锁（两者互不依赖）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tags_machine_core.web.category_view import (
    file_lock,
    load_design_root,
    resolve_category_view_root,
)

CLOTHING_DIR_NAME = "服装"
EXPORTER_REL = ("tools", "extract_action_clothes.py")
LOCK_NAME = ".clothing_pool.lock"
# 判定「动作库是否有新内容」只看这三类源文件：tags.txt 是标签主体，classify.yaml 决定
# 是否能被识别为服装候选，meta.yaml 只用于 action_outfit 判定。
SOURCE_NAMES = ("tags.txt", "classify.yaml", "meta.yaml")
SKIP_DIR_PREFIXES = ("pn_", "stn_")
EXPORT_TIMEOUT = 300.0
LOCK_TIMEOUT = 120.0
DEFAULT_MIN_TAGS = 4

_STAT_PATTERNS = {
    "candidates": re.compile(r"Total Candidates Scanned\s*:\s*(\d+)"),
    "exported": re.compile(r"Exported Clothing Nodes\s*:\s*(\d+)"),
    "below_threshold": re.compile(r"Skipped Below Threshold\s*:\s*(\d+)"),
    "duplicate": re.compile(r"Skipped Duplicate Content\s*:\s*(\d+)"),
    "already_existing": re.compile(r"Skipped Already Existing\s*:\s*(\d+)"),
}


def _newest_source_mtime(root: Path) -> float:
    """动作库源文件的最新修改时间；跟随链接（``new`` 是动作库的联接）。"""
    newest = 0.0
    visited: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.normcase(os.path.realpath(dirpath))
        if real in visited:  # 链接成环 / 同一真实目录被走两遍时剪掉
            dirnames[:] = []
            continue
        visited.add(real)
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(SKIP_DIR_PREFIXES) and not name.startswith(".")
        ]
        for name in filenames:
            if name not in SOURCE_NAMES:
                continue
            try:
                newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


def _scan_exports(export_root: Path) -> tuple[float, int]:
    """返回 (导出目录里 meta.yaml 的最新时间, 节点数)。目录不存在时是 (0, 0)。"""
    if not export_root.is_dir():
        return 0.0, 0
    newest = 0.0
    count = 0
    for dirpath, dirnames, filenames in os.walk(export_root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        if "meta.yaml" not in filenames:
            continue
        count += 1
        try:
            newest = max(newest, os.stat(os.path.join(dirpath, "meta.yaml")).st_mtime)
        except OSError:
            continue
    return newest, count


def _python_with_yaml() -> list[str]:
    """导出脚本需要 yaml：当前解释器有就用它，否则借 uv 临时装一个。"""
    try:
        import yaml  # noqa: F401

        return [sys.executable]
    except Exception:  # noqa: BLE001 - 没有 yaml 时退回 uv
        return ["uv", "run", "--with", "pyyaml", "python"]


def _error_headline(stderr: str) -> str:
    """从 traceback 里取最后一行（真正的异常），避免报告被整段栈淹掉。"""
    for line in reversed(stderr.splitlines()):
        text = line.strip()
        if text:
            return text[:400]
    return ""


def _parse_stats(stdout: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    for key, pattern in _STAT_PATTERNS.items():
        match = pattern.search(stdout)
        if match:
            stats[key] = int(match.group(1))
    return stats


def refresh_clothing_pool(
    root: str | Path,
    *,
    export_root: str | Path | None = None,
    force: bool = False,
    min_tags: int = DEFAULT_MIN_TAGS,
    timeout: float = EXPORT_TIMEOUT,
) -> dict[str, Any]:
    """增量生成服装节点库并返回结构化报告（不抛异常，失败体现在 ok=False）。"""
    root = Path(root).expanduser().resolve()
    target = (
        Path(export_root).expanduser().resolve()
        if export_root
        else root.parent / CLOTHING_DIR_NAME
    )
    exporter = root.joinpath(*EXPORTER_REL)
    report: dict[str, Any] = {"root": str(root), "export_dir": str(target), "ok": False}
    started = time.monotonic()
    if not exporter.is_file():
        report["skipped"] = f"exporter not found: {exporter}"
        report["seconds"] = round(time.monotonic() - started, 1)
        return report
    try:
        with file_lock(root / LOCK_NAME, timeout=LOCK_TIMEOUT):
            source_mtime = _newest_source_mtime(root)
            export_mtime, node_count = _scan_exports(target)
            report.update(
                {
                    "nodes": node_count,
                    "source_mtime": int(source_mtime),
                    "export_mtime": int(export_mtime),
                }
            )
            if not force and node_count > 0 and export_mtime >= source_mtime:
                report.update({"ok": True, "skipped": "up to date"})
                report["seconds"] = round(time.monotonic() - started, 1)
                return report
            cmd = [
                *_python_with_yaml(),
                str(exporter),
                "--export",
                "--export-dir",
                str(target),
                "--min-tags",
                str(min_tags),
            ]
            proc = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout
            )
            report["returncode"] = proc.returncode
            report["ok"] = proc.returncode == 0
            report["stats"] = _parse_stats(proc.stdout)
            if proc.returncode != 0:
                raw = (proc.stderr.strip() or proc.stdout.strip())
                report["error"] = _error_headline(raw) or f"exporter exited with {proc.returncode}"
                report["error_detail"] = raw[-1500:]
                report["stalled"] = "partial; 服装库可能是旧版本"
            elif report["stats"].get("exported") == 0 and node_count == 0:
                report["ok"] = False
                report["error"] = "exporter 退出 0 但没有任何产出（源库可能为空）"
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"[:600]
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def refresh_clothing_pool_at_startup(
    *,
    config_path: str | Path | None,
    explicit_root: str | Path | None = None,
    export_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Web 启动入口：定位 动作改2 后本地生成服装库。定位失败不视为错误。"""
    design_root = load_design_root(config_path) if config_path else None
    root = resolve_category_view_root(design_root, explicit_root)
    if root is None:
        return {
            "ok": False,
            "skipped": "action repo not found; pass --category-view-root",
            "design_root": design_root,
        }
    return refresh_clothing_pool(root, export_root=export_root, force=force)
