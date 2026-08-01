from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_SUCCESSFUL = 9987
EXPECTED_PROBLEMS = 23


def main() -> int:
    parser = argparse.ArgumentParser(description="Publishing Workspace 可恢复导入真实业务验收")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("first", "repeat", "interrupt-resume", "report"),
    )
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    playlist = args.playlist.expanduser().resolve()
    catalog = workspace / "workspace" / "catalog.sqlite"
    project_root = Path(__file__).resolve().parents[1]

    if args.mode == "report":
        _print_report(catalog)
        return 0
    if not playlist.is_file():
        raise FileNotFoundError(f"NeeView 播放列表不存在：{playlist}")
    workspace.mkdir(parents=True, exist_ok=True)
    _run(["init", str(workspace)], project_root)
    if _has_imports(catalog) and args.mode in {"first", "interrupt-resume"}:
        raise RuntimeError(f"验收 workspace 已有 ImportRun，请换一个目录：{workspace}")

    if args.mode == "interrupt-resume":
        run_id = _interrupt_after_first_batch(workspace, playlist, catalog, project_root)
        _wait_for_lease_expiry(catalog)
        result = _run(
            ["resume", str(workspace), run_id, "--log-level", "info"],
            project_root,
        )
    else:
        result = _run(
            [
                "import",
                str(workspace),
                str(playlist),
                "--input-type",
                "neev_playlist",
                "--log-level",
                "info",
            ],
            project_root,
        )
    summary = json.loads(result.stdout)
    _validate_summary(summary, args.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run(arguments: list[str], project_root: Path) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "publishing_workspace", *arguments]
    process = subprocess.Popen(
        command,
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    stderr_lines: list[str] = []

    def forward_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)
            print(line, end="", file=sys.stderr, flush=True)

    stderr_thread = threading.Thread(target=forward_stderr, daemon=True)
    stderr_thread.start()
    assert process.stdout is not None
    stdout = process.stdout.read()
    process.wait()
    stderr_thread.join(timeout=5)
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode,
            command,
            output=stdout,
            stderr="".join(stderr_lines),
        )
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout=stdout,
        stderr="".join(stderr_lines),
    )


def _spawn_import(workspace: Path, playlist: Path, project_root: Path) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "publishing_workspace",
        "import",
        str(workspace),
        str(playlist),
        "--input-type",
        "neev_playlist",
        "--log-level",
        "info",
    ]
    return subprocess.Popen(command, cwd=project_root)


def _interrupt_after_first_batch(
    workspace: Path,
    playlist: Path,
    catalog: Path,
    project_root: Path,
) -> str:
    process = _spawn_import(workspace, playlist, project_root)
    run_id = _wait_for_latest_run(catalog, timeout_seconds=60)
    _wait_for_processed_items(catalog, run_id, minimum=200, timeout_seconds=900)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=60)
    with sqlite3.connect(catalog) as connection:
        row = connection.execute(
            "SELECT status, processed_items FROM imports WHERE import_id=?", (run_id,)
        ).fetchone()
    if row is None or int(row[1]) < 200:
        raise RuntimeError("中断验收未保留至少一个已提交批次")
    print(f"interrupted run_id={run_id} status={row[0]} processed_items={row[1]}")
    return run_id


def _wait_for_latest_run(catalog: Path, *, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if catalog.is_file():
            with sqlite3.connect(catalog) as connection:
                row = connection.execute(
                    "SELECT import_id FROM imports ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
            if row:
                return str(row[0])
        time.sleep(0.5)
    raise TimeoutError("等待 ImportRun 创建超时")


def _wait_for_processed_items(
    catalog: Path,
    run_id: str,
    *,
    minimum: int,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with sqlite3.connect(catalog) as connection:
            row = connection.execute(
                "SELECT processed_items FROM imports WHERE import_id=?", (run_id,)
            ).fetchone()
        if row and int(row[0]) >= minimum:
            return
        time.sleep(1)
    raise TimeoutError(f"等待 processed_items >= {minimum} 超时")


def _wait_for_lease_expiry(catalog: Path, *, timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with sqlite3.connect(catalog) as connection:
            row = connection.execute(
                "SELECT lease_expires_at FROM workspace_locks "
                "WHERE lock_name='publishing_import'"
            ).fetchone()
        if row is None or datetime.fromisoformat(row[0]) <= datetime.now(timezone.utc):
            return
        time.sleep(1)
    raise TimeoutError("等待 workspace 写入租约过期超时")


def _has_imports(catalog: Path) -> bool:
    if not catalog.is_file():
        return False
    with sqlite3.connect(catalog) as connection:
        return connection.execute("SELECT 1 FROM imports LIMIT 1").fetchone() is not None


def _validate_summary(summary: dict, mode: str) -> None:
    successful = (
        summary.get("reused_path_items", 0)
        + summary.get("reused_content_items", 0)
        + summary.get("parsed_new_items", 0)
    )
    problems = (
        summary.get("missing_items", 0)
        + summary.get("failed_items", 0)
        + summary.get("held_problem_items", 0)
    )
    if summary.get("total_items") != EXPECTED_SUCCESSFUL + EXPECTED_PROBLEMS:
        raise AssertionError(f"总项目数不符：{summary.get('total_items')}")
    if successful != EXPECTED_SUCCESSFUL:
        raise AssertionError(f"成功项目数不符：{successful}")
    if problems != EXPECTED_PROBLEMS:
        raise AssertionError(f"问题项目数不符：{problems}")
    if mode == "repeat" and summary.get("held_problem_items") != EXPECTED_PROBLEMS:
        raise AssertionError("重复导入未将原问题保持为 held_problem")
    if summary.get("status") not in {"completed", "completed_with_errors"}:
        raise AssertionError(f"Run 未完成：{summary.get('status')}")


def _print_report(catalog: Path) -> None:
    if not catalog.is_file():
        raise FileNotFoundError(f"Catalog 不存在：{catalog}")
    with sqlite3.connect(catalog) as connection:
        connection.row_factory = sqlite3.Row
        runs = [dict(row) for row in connection.execute(
            "SELECT import_id, mode, status, total_items, processed_items, "
            "reused_path_items, reused_content_items, parsed_new_items, missing_items, "
            "failed_items, held_problem_items, created_at, completed_at "
            "FROM imports ORDER BY rowid"
        )]
        problem_codes = [dict(row) for row in connection.execute(
            "SELECT error_code, status, COUNT(*) AS count FROM import_problems "
            "GROUP BY error_code, status ORDER BY error_code, status"
        )]
    print(json.dumps({"runs": runs, "problem_codes": problem_codes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
