from __future__ import annotations

import argparse
import json

from .service import PublishingService


def add_publishing_subparser(subparsers, *, output_parent: argparse.ArgumentParser) -> None:
    publish = subparsers.add_parser(
        "publish",
        help="管理投稿素材工作区",
    )
    commands = publish.add_subparsers(dest="publish_command")

    init_parser = commands.add_parser(
        "init",
        parents=[output_parent],
        help="初始化公共投稿素材工作区",
    )
    init_parser.add_argument("root", help="Publishing 根目录")
    init_parser.set_defaults(func=cmd_publish_init)

    import_parser = commands.add_parser(
        "import",
        parents=[output_parent],
        help="从 NeeView 播放列表、目录或快捷方式导入图片",
    )
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
    import_parser.set_defaults(func=cmd_publish_import)

    classify_parser = commands.add_parser(
        "classify",
        parents=[output_parent],
        help="根据图片节点信息构建分类视图计划",
    )
    _add_plan_arguments(classify_parser)
    classify_parser.set_defaults(func=cmd_publish_classify)

    export_parser = commands.add_parser(
        "export",
        parents=[output_parent],
        help="构建分类计划并导出外部视图",
    )
    _add_plan_arguments(export_parser)
    export_parser.add_argument(
        "--exporter",
        action="append",
        choices=("neev", "windows_shortcut"),
        help="指定 Exporter，可重复；默认使用 workspace.yaml 中启用项",
    )
    export_parser.set_defaults(func=cmd_publish_export)


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("root", help="Publishing 根目录")
    parser.add_argument(
        "--import-id",
        help="只处理指定导入快照；默认处理整个公共 Catalog，局部导出写入 _imports/<id>",
    )
    parser.add_argument(
        "--hierarchy",
        nargs="+",
        help="临时覆盖分类层级，例如 artist character action_group action",
    )


def cmd_publish_init(args) -> int:
    _print_json(PublishingService().initialize(args.root))
    return 0


def cmd_publish_import(args) -> int:
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


def cmd_publish_classify(args) -> int:
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


def cmd_publish_export(args) -> int:
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


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
