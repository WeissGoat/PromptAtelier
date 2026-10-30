from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def _refresh_category_view(
    args: argparse.Namespace, config_path: str | Path | None
) -> None:
    """启动前刷新分类视图；失败只告警，不阻止 Web 启动。"""
    from tags_machine_core.web.category_view import refresh_category_view_at_startup

    try:
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
        detail = report.get("error") or report.get("skipped") or "see report above"
        if args.category_view_strict:
            raise SystemExit(f"[category-view] refresh failed (strict): {detail}")
        print(
            f"[category-view] view may be stale; web will start anyway: {detail}",
            flush=True,
        )


def _refresh_clothing_pool(
    args: argparse.Namespace, config_path: str | Path | None
) -> None:
    """启动前本地生成服装节点库（design/服装）；失败只告警，不阻止 Web 启动。"""
    from tags_machine_core.web.clothing_pool import refresh_clothing_pool_at_startup

    try:
        report = refresh_clothing_pool_at_startup(
            config_path=config_path,
            explicit_root=args.category_view_root,
            export_root=args.clothing_pool_dir,
            force=args.refresh_clothing_pool,
        )
    except Exception as exc:  # noqa: BLE001 - 派生库生成失败不应该让 Web 起不来
        print(f"[clothing-pool] refresh failed: {type(exc).__name__}: {exc}", flush=True)
        return
    print("[clothing-pool] " + json.dumps(report, ensure_ascii=False), flush=True)
    if not report.get("ok"):
        detail = report.get("error") or report.get("skipped") or "see report above"
        print(
            f"[clothing-pool] pool may be stale; web will start anyway: {detail}",
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
    parser.add_argument(
        "--category-view-strict",
        action="store_true",
        help="分类视图刷新失败时直接退出，而不是带病启动（CI / 部署校验用）",
    )
    parser.add_argument(
        "--skip-clothing-pool",
        action="store_true",
        help="启动时不本地生成服装节点库（design/服装）",
    )
    parser.add_argument(
        "--refresh-clothing-pool",
        action="store_true",
        help="忽略时间戳判断，强制重跑服装节点库生成",
    )
    parser.add_argument(
        "--clothing-pool-dir",
        help="服装节点库目录；默认 design/服装（动作改2 的兄弟目录）",
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
        from tags_machine_core.web.app import resolve_web_config_path

        try:
            config_path = resolve_web_config_path(args.config)
        except Exception as exc:  # noqa: BLE001 - 定位不到配置就各自降级
            print(f"[startup] config not resolved: {type(exc).__name__}: {exc}", flush=True)
            config_path = None
        _refresh_category_view(args, config_path)
        if args.skip_clothing_pool:
            print(
                "[clothing-pool] " + json.dumps({"ok": True, "skipped": "--skip-clothing-pool"}),
                flush=True,
            )
        else:
            _refresh_clothing_pool(args, config_path)
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
