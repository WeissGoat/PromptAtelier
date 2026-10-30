"""启动期刷新动作分类视图（pn_* / stn_*）。

两种模式：
- ``relink``（默认）：先 ``git pull`` 拉最新 ``category_view_manifest.json``，再照 manifest
  增量复刻链接。不解析 classify.yaml、不改 manifest，所有机器看到的分区完全一致。
- ``rebuild``：重新解析 classify.yaml 重算分桶并重写 manifest。只在本机要改分类规则时用，
  会让 Git 里跟踪的 manifest 变脏，且多台机器同时 rebuild 会互相覆盖。

刷新失败只告警，不阻止 Web 启动。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ACTION_VIEW_DIR_NAME = "动作改2"
MANIFEST_NAME = "category_view_manifest.json"
LOCK_NAME = ".category_view.lock"
DESIGN_ROOT_KEYS = ("legacy", "design_root")


def resolve_category_view_root(
    design_root: str | Path | None, explicit: str | Path | None = None
) -> Path | None:
    """解析 动作改2 根目录：显式参数 > config.legacy.design_root/动作改2。"""
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_dir() else None
    if not design_root:
        return None
    candidate = Path(design_root) / ACTION_VIEW_DIR_NAME
    return candidate if candidate.is_dir() else None


def load_design_root(config_path: str | Path) -> str | None:
    """从 Web 配置文件里读 legacy.design_root；读不到返回 None。"""
    try:
        import yaml

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 配置有问题不应该拖垮 Web 启动
        return None
    for key in DESIGN_ROOT_KEYS:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data if isinstance(data, str) and data else None


def _git(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )


# 传输层停滞检测：git 自己默认不启用（curl_low_speed_limit = -1），断流会一直挂着。
# 用 `git -c` 注入而不是环境变量 / --global，保证行为跟着代码走，换机器不用重配。
HTTP_STALL_ARGS = ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20"]
# 总耗时兜底：停滞检测已经能在几十秒内止损，这里只防极端情况无限挂着。
PULL_TIMEOUT = 300.0
SSH_STALL_COMMAND = (
    "ssh -o BatchMode=yes -o ConnectTimeout=10"
    " -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
)


def _ssh_stall_args(repo: Path) -> list[str]:
    """SSH 停滞检测；用户已自定义 core.sshCommand（如 Windows 的 plink）时不覆盖。"""
    try:
        existing = _git(["config", "core.sshCommand"], repo, 30.0)
    except (OSError, subprocess.SubprocessError):
        return []
    if existing.returncode == 0 and existing.stdout.strip():
        return []
    return ["-c", f"core.sshCommand={SSH_STALL_COMMAND}"]


def _report_stale_locks(repo: Path, report: dict[str, Any], reason: str) -> None:
    """超时被杀后 git 可能留下 lock 文件；只报告不自动删（可能有其他 git 进程在跑）。"""
    report["skipped"] = reason
    lock_dir = repo / ".git"
    try:
        locks = sorted(p.name for p in lock_dir.glob("*.lock"))
    except OSError:
        return
    if locks:
        report["stale_locks"] = locks
        report["hint"] = (
            "确认没有其他 git 进程在操作该仓库后再手动删除: "
            + ", ".join(f".git/{name}" for name in locks)
        )


def git_pull_ff_only(repo: Path, *, timeout: float = 300.0) -> dict[str, Any]:
    """安全的快进拉取。工作区有已跟踪改动、或无法快进时跳过，绝不覆盖本地内容。

    timeout 是总耗时上限（墙钟），不是停滞判定；停滞由 HTTP_STALL_ARGS /
    SSH_STALL_COMMAND 交给传输层处理——真断流几十秒就退出，慢但在传则继续。
    """
    report: dict[str, Any] = {"repo": str(repo), "pulled": False}
    if not (repo / ".git").exists():
        report["skipped"] = "not a git repo"
        return report
    try:
        dirty = _git(["status", "--porcelain", "--untracked-files=no"], repo, 60.0)
        if dirty.returncode != 0:
            report["skipped"] = f"git status failed: {dirty.stderr.strip()[:200]}"
            return report
        if dirty.stdout.strip():
            report["skipped"] = "tracked files modified locally"
            return report
        before = _git(["rev-parse", "--short", "HEAD"], repo, 30.0).stdout.strip()
        pulled = _git(
            [*HTTP_STALL_ARGS, *_ssh_stall_args(repo), "pull", "--ff-only", "--quiet"],
            repo,
            timeout,
        )
        after = _git(["rev-parse", "--short", "HEAD"], repo, 30.0).stdout.strip()
        report.update({"before": before, "after": after})
        if pulled.returncode != 0:
            report["skipped"] = pulled.stderr.strip()[:400] or "pull failed"
            return report
        report["pulled"] = before != after
        report["up_to_date"] = before == after
        return report
    except subprocess.TimeoutExpired:
        _report_stale_locks(repo, report, f"pull exceeded {timeout:.0f}s total, aborted")
        return report
    except (OSError, subprocess.SubprocessError) as exc:
        report["skipped"] = str(exc)[:400]
        return report


@contextmanager
def file_lock(path: Path, *, timeout: float = 900.0) -> Iterator[None]:
    """跨平台排他锁：防止多个进程同时改写同一个生成目录。

    非阻塞重试 + 截止时间：拿不到锁就抛 TimeoutError，绝不无限阻塞（否则重建卡住时
    Web 就永远起不来）。POSIX 与 Windows 行为一致。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock busy for {timeout:.0f}s: {path}") from None
                time.sleep(0.5)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


@contextmanager
def category_view_lock(root: Path, *, timeout: float = 900.0) -> Iterator[None]:
    """分类视图专用锁：防止 Web 刷新与定时重建互相删链接。"""
    with file_lock(root / LOCK_NAME, timeout=timeout):
        yield


def _last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def refresh_category_view(
    root: str | Path,
    *,
    mode: str = "relink",
    pull: bool = True,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """刷新分类视图并返回结构化报告（不抛异常，失败体现在 ok=False）。"""
    root = Path(root).expanduser().resolve()
    report: dict[str, Any] = {"root": str(root), "mode": mode, "ok": False}
    started = time.monotonic()
    try:
        with category_view_lock(root):
            if pull:
                report["pull_design_repo"] = git_pull_ff_only(root)
                new_dir = root / "new"
                report["pull_action_repo"] = (
                    git_pull_ff_only(new_dir, timeout=PULL_TIMEOUT)
                    if new_dir.exists()
                    else {"repo": str(new_dir), "pulled": False, "skipped": "new missing"}
                )
            if mode == "rebuild":
                cmd = [
                    sys.executable,
                    str(root / "tools" / "generate_category_view.py"),
                    "--root",
                    str(root),
                    "--apply",
                ]
                report["warning"] = "rebuild rewrites category_view_manifest.json (git tracked)"
            else:
                cmd = [
                    sys.executable,
                    str(root / "tools" / "link_views_from_manifest.py"),
                    "--root",
                    str(root),
                    "--only-missing",
                ]
            proc = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout
            )
            report["returncode"] = proc.returncode
            report["ok"] = proc.returncode == 0
            report["stats"] = _last_json_line(proc.stdout)
            stats = report.get("stats") or {}
            if stats.get("failed"):
                report["partial"] = True  # 部分链接失败，其余已建好
            if proc.returncode != 0:
                report["stderr"] = proc.stderr.strip()[-1500:]
                if mode == "rebuild":
                    dirty = _git(
                        ["status", "--porcelain", "--untracked-files=no", "--", MANIFEST_NAME],
                        root,
                        30.0,
                    )
                    if dirty.returncode == 0 and dirty.stdout.strip():
                        report["dirty_manifest"] = True
                        report["hint"] = (
                            f"manifest 已被改写但刷新失败；确认后执行 git checkout -- {MANIFEST_NAME}"
                        )
            elif proc.stderr.strip():
                report["stderr"] = proc.stderr.strip()[-800:]
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"[:600]
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def refresh_category_view_at_startup(
    *,
    config_path: str | Path | None,
    explicit_root: str | Path | None = None,
    mode: str = "relink",
    pull: bool = True,
) -> dict[str, Any]:
    """Web 启动入口：定位 动作改2 并刷新视图。定位失败不视为错误。"""
    design_root = load_design_root(config_path) if config_path else None
    root = resolve_category_view_root(design_root, explicit_root)
    if root is None:
        return {
            "ok": False,
            "skipped": "category view root not found; pass --category-view-root",
            "design_root": design_root,
            "config": str(config_path) if config_path else None,
        }
    if not (root / MANIFEST_NAME).is_file() and not (root / "tools" / "generate_category_view.py").is_file():
        return {"ok": False, "skipped": f"not a category view repo: {root}"}
    return refresh_category_view(root, mode=mode, pull=pull)
