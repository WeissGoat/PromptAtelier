from __future__ import annotations

import argparse
import json
import sys

from .logging import configure_logging
from .service import PublishingService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publishing-workspace",
        description="投稿图片 Catalog、分类与视图导出工具",
    )
    commands = parser.add_subparsers(dest="command")

    init_parser = commands.add_parser("init", help="初始化公共投稿素材工作区")
    _add_log_argument(init_parser)
    init_parser.add_argument("root", help="Publishing 根目录")
    init_parser.set_defaults(func=cmd_init)

    import_parser = commands.add_parser(
        "import",
        help="从 NeeView 播放列表、目录或快捷方式导入图片",
    )
    _add_log_argument(import_parser)
    import_parser.add_argument("root", help="Publishing 根目录")
    import_parser.add_argument("source", help="输入播放列表、目录或快捷方式")
    import_parser.add_argument(
        "--input-type",
        choices=("neev_playlist", "directory", "shortcut"),
        help="显式指定输入适配器；默认自动探测",
    )
    import_parser.add_argument("--recursive", action="store_true", help="递归扫描目录")
    import_parser.add_argument(
        "--strict",
        action="store_true",
        help="遇到缺失、损坏或不支持的图片时立即失败",
    )
    import_parser.add_argument(
        "--legacy-tolerant",
        action="store_true",
        help="显式允许旧 NeeView JSON 的宽松控制字符解析",
    )
    import_parser.set_defaults(func=cmd_import)

    classify_parser = commands.add_parser("classify", help="构建分类视图计划")
    _add_log_argument(classify_parser)
    _add_plan_arguments(classify_parser)
    classify_parser.set_defaults(func=cmd_classify)

    export_parser = commands.add_parser("export", help="构建并导出分类视图")
    _add_log_argument(export_parser)
    _add_plan_arguments(export_parser)
    export_parser.add_argument(
        "--exporter",
        action="append",
        choices=("neev", "windows_shortcut"),
        help="指定 Exporter，可重复；默认使用 workspace.yaml 中启用项",
    )
    export_parser.set_defaults(func=cmd_export)
    return parser


def _add_log_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=("trace", "info", "warning", "error"),
        help="日志级别；默认读取 PUBLISHING_WORKSPACE_LOG_LEVEL 或 error",
    )


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", help="Publishing 根目录")
    parser.add_argument(
        "--import-id",
        help="只处理指定导入快照；默认处理整个 Catalog，局部结果写入 _imports/<id>",
    )
    parser.add_argument(
        "--hierarchy",
        nargs="+",
        help="临时覆盖分类层级，例如 artist character action_group action",
    )


def cmd_init(args) -> int:
    _print_json(PublishingService().initialize(args.root))
    return 0


def cmd_import(args) -> int:
    result = PublishingService().import_source(
        args.root,
        args.source,
        input_type=args.input_type,
        recursive=args.recursive,
        strict=args.strict,
        legacy_tolerant=args.legacy_tolerant,
    )
    _print_json(result.model_dump(mode="json"))
    return 0


def cmd_classify(args) -> int:
    plan, plan_path = PublishingService().classify(
        args.root,
        import_id=args.import_id,
        hierarchy=args.hierarchy,
    )
    _print_json(
        {
            "import_id": plan.import_id,
            "hierarchy": plan.hierarchy,
            "view_count": len(plan.views),
            "plan_path": str(plan_path),
        }
    )
    return 0


def cmd_export(args) -> int:
    plan, summary = PublishingService().export(
        args.root,
        import_id=args.import_id,
        hierarchy=args.hierarchy,
        exporter_types=args.exporter,
    )
    _print_json(
        {
            "import_id": plan.import_id,
            "hierarchy": plan.hierarchy,
            "export": summary.model_dump(mode="json"),
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    configure_logging(getattr(args, "log_level", None))
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
