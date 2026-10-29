from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def _refresh_category_view(args: argparse.Namespace) -> None:
    """启动前刷新分类视图；失败只告警，不阻止 Web 启动。"""
    import json

    from tags_machine_core.web.app import resolve_web_config_path
    from tags_machine_core.web.category_view import refresh_category_view_at_startup

    try:
        config_path = resolve_web_config_path(args.config)
        report = refresh_category_view_at_startup(
            config_path=config_path,
            explicit_root=args.category_view_root,
            mode=args.refresh_category_view,
            pull=not args.skip_category_view_pull,
        )
    except Exception as exc:  # noqa: BLE001 - 刷新失败不应该让 Web 起不来
        print(f"[category-view] refresh failed: {type(exc).__name__}: {exc}", flush=True)
        return
    print("[category-view] " + json.dumps(report, ensure_ascii=False), flush=True)
    if not report.get("ok"):
        print(
            "[category-view] view may be stale; web will start anyway: "
            + str(report.get("error") or report.get("skipped") or "see report above"),
            flush=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PromptAtelier Web API server")
    parser.add_argument("--config", help="配置文件路径；默认优先读取 configs/local.yaml")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=53211, help="监听端口")
    parser.add_argument(
        "--static-dir",
        help="同源托管的前端构建目录（如 web/dist）；服务器部署时使用",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用 uvicorn reload，适合开发后端时使用",
    )
    parser.add_argument(
        "--refresh-category-view",
        nargs="?",
        const="relink",
        choices=["relink", "rebuild"],
        default=None,
        help=(
            "启动前刷新动作分类视图 pn_*/stn_*：默认 relink（git pull 后按 manifest 增量复刻链接，"
            "不改 manifest）；传 rebuild 则重新解析 classify.yaml 并重写 manifest"
        ),
    )
    parser.add_argument(
        "--category-view-root",
        help="动作改2 仓库根目录；默认由配置文件 legacy.design_root 推断",
    )
    parser.add_argument(
        "--skip-category-view-pull",
        action="store_true",
        help="刷新分类视图前不执行 git pull（离线 / 不想联网时使用）",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.config:
        os.environ["TAGS_MACHINE_CONFIG"] = args.config
    if args.static_dir:
        os.environ["PROMPTATELIER_STATIC_DIR"] = args.static_dir
    src_dir = str(Path(__file__).resolve().parents[2])
    if args.refresh_category_view:
        _refresh_category_view(args)
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
