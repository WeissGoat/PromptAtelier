from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PromptAtelier Web API server")
    parser.add_argument("--config", help="配置文件路径；默认优先读取 configs/local.yaml")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument(
        "--static-dir",
        help="同源托管的前端构建目录（如 web/dist）；服务器部署时使用",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用 uvicorn reload，适合开发后端时使用",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.config:
        os.environ["TAGS_MACHINE_CONFIG"] = args.config
    if args.static_dir:
        os.environ["PROMPTATELIER_STATIC_DIR"] = args.static_dir
    src_dir = str(Path(__file__).resolve().parents[2])
    loop_opt = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run(
        "tags_machine_core.web:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[src_dir] if args.reload else None,
        loop=loop_opt,
    )


if __name__ == "__main__":
    main()
