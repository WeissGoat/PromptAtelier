from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    import_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="强制重试相同文件指纹的 open problem",
    )
    import_parser.set_defaults(func=cmd_import)

    status_parser = commands.add_parser("status", help="查看 ImportRun 状态")
    _add_log_argument(status_parser)
    status_parser.add_argument("root", help="Publishing 根目录")
    status_parser.add_argument("run_id", nargs="?", help="可选 ImportRun id")
    status_parser.set_defaults(func=cmd_status)

    resume_parser = commands.add_parser("resume", help="恢复中断的 ImportRun")
    _add_log_argument(resume_parser)
    resume_parser.add_argument("root", help="Publishing 根目录")
    resume_parser.add_argument("run_id", help="ImportRun id")
    resume_parser.set_defaults(func=cmd_resume)

    problems_parser = commands.add_parser("problems", help="查询导入问题")
    _add_log_argument(problems_parser)
    problems_parser.add_argument("root", help="Publishing 根目录")
    problems_parser.add_argument(
        "--status", choices=("open", "resolved", "ignored"), default="open"
    )
    problems_parser.add_argument("--run-id")
    problems_parser.add_argument(
        "--code",
        choices=(
            "missing_path",
            "empty_file",
            "unreadable_image",
            "unsupported_format",
            "metadata_read_error",
            "shortcut_resolve_error",
            "legacy_failure",
        ),
    )
    problems_parser.set_defaults(func=cmd_problems)

    retry_parser = commands.add_parser("retry-problems", help="重试问题队列")
    _add_log_argument(retry_parser)
    retry_parser.add_argument("root", help="Publishing 根目录")
    retry_parser.add_argument("--run-id")
    retry_parser.add_argument("--code")
    retry_parser.set_defaults(func=cmd_retry_problems)

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

    task_parser = commands.add_parser("task", help="投稿任务管理")
    task_commands = task_parser.add_subparsers(dest="task_command")

    task_create_parser = task_commands.add_parser("create", help="创建投稿任务")
    _add_log_argument(task_create_parser)
    task_create_parser.add_argument("root", help="Publishing 根目录")
    task_create_parser.add_argument("task_id", help="任务目录名")
    task_create_parser.add_argument("--title", help="任务标题")
    task_create_parser.add_argument("--candidates", help="初始 candidates 输入")
    task_create_parser.add_argument(
        "--input-type",
        choices=("neev_playlist", "directory", "shortcut"),
    )
    task_create_parser.add_argument("--recursive", action="store_true")
    task_create_parser.set_defaults(func=cmd_task_create)

    task_import_parser = task_commands.add_parser(
        "import-selection", help="导入 all/post/cover 选择集合"
    )
    _add_log_argument(task_import_parser)
    task_import_parser.add_argument("root", help="Publishing 根目录")
    task_import_parser.add_argument("task_id", help="任务目录名")
    task_import_parser.add_argument(
        "--set",
        dest="selection_name",
        required=True,
        choices=("all", "post", "cover"),
    )
    task_import_parser.add_argument("--source", required=True, help="输入播放列表或目录")
    task_import_parser.add_argument(
        "--mode", choices=("replace", "append"), default="replace"
    )
    task_import_parser.add_argument(
        "--input-type",
        choices=("neev_playlist", "directory", "shortcut"),
    )
    task_import_parser.add_argument("--recursive", action="store_true")
    task_import_parser.set_defaults(func=cmd_task_import_selection)

    task_status_parser = task_commands.add_parser("status", help="查看投稿任务")
    _add_log_argument(task_status_parser)
    task_status_parser.add_argument("root", help="Publishing 根目录")
    task_status_parser.add_argument("task_id", help="任务目录名")
    task_status_parser.set_defaults(func=cmd_task_status)

    task_build_parser = task_commands.add_parser("build", help="构建投稿包")
    _add_log_argument(task_build_parser)
    task_build_parser.add_argument("root", help="Publishing 根目录")
    task_build_parser.add_argument("task_id", help="任务目录名")
    task_build_parser.set_defaults(func=cmd_task_build)
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
        retry_failed=args.retry_failed,
    )
    _print_json(result.model_dump(mode="json"))
    return 0


def cmd_status(args) -> int:
    result = PublishingService().import_status(args.root, args.run_id)
    _print_json(result.model_dump(mode="json"))
    return 0


def cmd_resume(args) -> int:
    result = PublishingService().resume_import(args.root, args.run_id)
    _print_json(result.model_dump(mode="json"))
    return 0


def cmd_problems(args) -> int:
    problems = PublishingService().list_problems(
        args.root,
        status=args.status,
        run_id=args.run_id,
        error_code=args.code,
    )
    _print_json(
        {
            "count": len(problems),
            "items": [problem.model_dump(mode="json") for problem in problems],
        }
    )
    return 0


def cmd_retry_problems(args) -> int:
    result = PublishingService().retry_problems(
        args.root,
        run_id=args.run_id,
        error_code=args.code,
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


def cmd_task_create(args) -> int:
    config = PublishingService().create_task(
        args.root,
        args.task_id,
        title=args.title,
        candidates=args.candidates,
        input_type=args.input_type,
        recursive=args.recursive,
    )
    task_yaml = (
        Path(args.root).expanduser().resolve()
        / "tasks"
        / config.task_id
        / "task.yaml"
    )
    _print_json(
        {
            "task_id": config.task_id,
            "title": config.title,
            "task_yaml": str(task_yaml),
        }
    )
    return 0


def cmd_task_import_selection(args) -> int:
    history = PublishingService().import_task_selection(
        args.root,
        args.task_id,
        args.selection_name,
        args.source,
        input_type=args.input_type,
        recursive=args.recursive,
        mode=args.mode,
    )
    _print_json(history.model_dump(mode="json", by_alias=True))
    return 0


def cmd_task_status(args) -> int:
    _print_json(PublishingService().task_status(args.root, args.task_id))
    return 0


def cmd_task_build(args) -> int:
    result = PublishingService().build_task(args.root, args.task_id)
    _print_json(result.model_dump(mode="json"))
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
    except (KeyError, OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
