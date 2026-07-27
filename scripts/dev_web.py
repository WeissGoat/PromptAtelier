from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DEFAULT_BACKEND_PORT = 8765
DEFAULT_FRONTEND_PORT = 53173
STATE_PATH = ROOT / "runtime" / "dev_web.json"
STATE_SCHEMA = "promptatelier.dev-web/v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 PromptAtelier Web 前后端开发服务")
    parser.add_argument("--config", help="配置文件路径；默认优先读取 configs/local.yaml")
    parser.add_argument("--host", default="127.0.0.1", help="前后端监听地址")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--stop", action="store_true", help="停止上一轮 PromptAtelier Web 实例后退出")
    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument("--reload-backend", dest="reload_backend", action="store_true", help="后端启用 uvicorn reload")
    reload_group.add_argument("--no-reload-backend", dest="reload_backend", action="store_false", help="关闭后端 uvicorn reload")
    parser.set_defaults(reload_backend=True)
    parser.add_argument("--no-install", action="store_true", help="跳过 node_modules 自动安装检查")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _cleanup_previous_instance(args.backend_port, args.frontend_port)
    except RuntimeError as exc:
        print(f"Cannot start PromptAtelier Web: {exc}", file=sys.stderr)
        return 2
    if args.stop:
        print("PromptAtelier Web stopped.")
        return 0

    _ensure_frontend_deps(skip=args.no_install)

    env = os.environ.copy()
    env["VITE_API_ROOT"] = f"http://{args.host}:{args.backend_port}/api"
    if args.config:
        env["TAGS_MACHINE_CONFIG"] = args.config

    backend_cmd = [
        sys.executable,
        "-m",
        "tags_machine_core.web",
        "--host",
        args.host,
        "--port",
        str(args.backend_port),
    ]
    if args.config:
        backend_cmd.extend(["--config", args.config])
    if args.reload_backend:
        backend_cmd.append("--reload")

    vite = _vite_command()
    frontend_cmd = [
        *vite,
        "--host",
        args.host,
        "--port",
        str(args.frontend_port),
        "--strictPort",
        "false",
    ]

    print("Starting PromptAtelier Web...")
    print(f"  Backend : http://{args.host}:{args.backend_port}/api")
    print(f"  Frontend: http://{args.host}:{args.frontend_port}")
    print("  Config  : " + (args.config or "configs/local.yaml if present, else configs/local.example.yaml"))
    print("Press Ctrl+C to stop both services.")

    instance_id = uuid4().hex
    processes: list[subprocess.Popen] = []
    try:
        backend = subprocess.Popen(backend_cmd, cwd=ROOT, env=env)
        processes.append(backend)
        frontend = subprocess.Popen(frontend_cmd, cwd=WEB_DIR, env=env)
        processes.append(frontend)
        _write_state(
            instance_id,
            backend_pid=backend.pid,
            frontend_pid=frontend.pid,
            backend_port=args.backend_port,
            frontend_port=args.frontend_port,
        )
        return _wait_for_processes(processes)
    except KeyboardInterrupt:
        print("\nStopping PromptAtelier Web...")
        return 130
    finally:
        _terminate_all(processes)
        _clear_state(instance_id)


def _cleanup_previous_instance(
    backend_port: int,
    frontend_port: int,
    *,
    state_path: Path = STATE_PATH,
) -> None:
    terminated: set[int] = set()
    state = _read_state(state_path)
    if state and _same_root(state.get("root")):
        for key in ("backend_pid", "frontend_pid"):
            pid = _positive_int(state.get(key))
            if pid is None or pid in terminated:
                continue
            print(f"Stopping previous PromptAtelier process tree PID {pid}...")
            _terminate_pid_tree(pid)
            terminated.add(pid)
    if state_path.exists():
        state_path.unlink(missing_ok=True)

    for role, port in (("backend", backend_port), ("frontend", frontend_port)):
        pid = _port_owner_pid(port)
        if pid is None or pid in terminated:
            continue
        if not _is_owned_port_process(pid, role):
            current_pid = _port_owner_pid(port)
            if current_pid is None:
                continue
            if current_pid != pid and _is_owned_port_process(current_pid, role):
                pid = current_pid
            else:
                detail = _describe_process(current_pid)
                raise RuntimeError(
                    f"port {port} is occupied by PID {current_pid}: {detail}"
                )
        target_pid = _owned_process_root(pid, role)
        print(
            f"Stopping previous PromptAtelier {role} on port {port}, "
            f"PID {target_pid}..."
        )
        _terminate_pid_tree(target_pid)
        terminated.add(target_pid)


def _write_state(
    instance_id: str,
    *,
    backend_pid: int,
    frontend_pid: int,
    backend_port: int,
    frontend_port: int,
    state_path: Path = STATE_PATH,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": STATE_SCHEMA,
                "instance_id": instance_id,
                "root": str(ROOT),
                "launcher_pid": os.getpid(),
                "backend_pid": backend_pid,
                "frontend_pid": frontend_pid,
                "backend_port": backend_port,
                "frontend_port": frontend_port,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _clear_state(instance_id: str, *, state_path: Path = STATE_PATH) -> None:
    state = _read_state(state_path)
    if state and state.get("instance_id") == instance_id:
        state_path.unlink(missing_ok=True)


def _read_state(state_path: Path) -> dict:
    if not state_path.is_file():
        return {}
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_root(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return Path(value).resolve() == ROOT.resolve()
    except OSError:
        return False


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _port_owner_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING" or not parts[1].endswith(suffix):
            continue
        return _positive_int(parts[-1])
    return None


def _is_owned_port_process(pid: int, role: str) -> bool:
    chain = _process_chain(pid)
    command = " ".join(str(item.get("CommandLine") or "") for item in chain)
    normalized = command.lower().replace("\\", "/")
    root = str(ROOT).lower().replace("\\", "/")
    marker = "tags_machine_core.web" if role == "backend" else "/web/node_modules/vite/"
    return root in normalized and marker in normalized


def _owned_process_root(pid: int, role: str) -> int:
    chain = _process_chain(pid)
    root = str(ROOT).lower().replace("\\", "/")
    marker = "tags_machine_core.web" if role == "backend" else "/web/node_modules/vite/"
    candidates: list[int] = []
    for item in chain:
        command = str(item.get("CommandLine") or "").lower().replace("\\", "/")
        process_id = _positive_int(item.get("ProcessId"))
        if process_id is not None and root in command and marker in command:
            candidates.append(process_id)
    return candidates[-1] if candidates else pid


def _describe_process(pid: int) -> str:
    chain = _process_chain(pid)
    if not chain:
        return "unknown process"
    item = chain[0]
    name = item.get("Name") or "unknown"
    command = item.get("CommandLine") or ""
    return f"{name} {command}".strip()


def _process_chain(pid: int, *, limit: int = 8) -> list[dict]:
    if os.name != "nt":
        return []
    chain: list[dict] = []
    seen: set[int] = set()
    current = pid
    while current > 0 and current not in seen and len(chain) < limit:
        seen.add(current)
        info = _windows_process_info(current)
        if not info:
            break
        chain.append(info)
        current = _positive_int(info.get("ParentProcessId")) or 0
    return chain


def _windows_process_info(pid: int) -> dict:
    script = (
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {pid}"; '
        "if($p){$p | Select-Object ProcessId,ParentProcessId,Name,CommandLine "
        "| ConvertTo-Json -Compress}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _terminate_pid_tree(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _ensure_frontend_deps(*, skip: bool) -> None:
    if skip or (WEB_DIR / "node_modules").exists():
        return
    npm = _npm_command()
    print("web/node_modules not found; running npm install...")
    subprocess.run([npm, "install"], cwd=WEB_DIR, check=True)


def _npm_command() -> str:
    command = "npm.cmd" if os.name == "nt" else "npm"
    npm = shutil.which(command)
    if not npm:
        raise RuntimeError("npm not found; install Node.js first")
    return npm


def _vite_command() -> list[str]:
    vite_js = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node.exe" if os.name == "nt" else "node")
    if vite_js.exists() and node:
        return [node, str(vite_js)]
    binary = WEB_DIR / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
    if binary.exists():
        return [str(binary)]
    return [_npm_command(), "exec", "--", "vite"]


def _wait_for_processes(processes: list[subprocess.Popen]) -> int:
    while True:
        for process in processes:
            code = process.poll()
            if code is not None:
                return int(code)
        time.sleep(0.5)


def _terminate_all(processes: list[subprocess.Popen]) -> None:
    if os.name == "nt":
        for process in processes:
            if process.poll() is None:
                _terminate_pid_tree(process.pid)
        return
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
