from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DEFAULT_BACKEND_PORT = 8765
DEFAULT_FRONTEND_PORT = 53173


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 PromptAtelier Web 前后端开发服务")
    parser.add_argument("--config", help="配置文件路径；默认优先读取 configs/local.yaml")
    parser.add_argument("--host", default="127.0.0.1", help="前后端监听地址")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument("--reload-backend", dest="reload_backend", action="store_true", help="后端启用 uvicorn reload")
    reload_group.add_argument("--no-reload-backend", dest="reload_backend", action="store_false", help="关闭后端 uvicorn reload")
    parser.set_defaults(reload_backend=True)
    parser.add_argument("--no-install", action="store_true", help="跳过 node_modules 自动安装检查")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

    backend = subprocess.Popen(backend_cmd, cwd=ROOT, env=env)
    frontend = subprocess.Popen(frontend_cmd, cwd=WEB_DIR, env=env)
    processes = [backend, frontend]
    try:
        return _wait_for_processes(processes)
    except KeyboardInterrupt:
        print("\nStopping PromptAtelier Web...")
        return 130
    finally:
        _terminate_all(processes)


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
