from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from .config import load_workspace
from .integrations.anr_mosaic import MosaicModelManager
from .logging import configure_logging
from .service import PublishingService
from .plans.models import ScheduleEntry


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

    mosaic_parser = commands.add_parser("mosaic", help="管理自动打码模型")
    mosaic_commands = mosaic_parser.add_subparsers(dest="mosaic_command")

    mosaic_status_parser = mosaic_commands.add_parser("status", help="检查打码模型")
    _add_log_argument(mosaic_status_parser)
    mosaic_status_parser.add_argument("root", help="Publishing 根目录")
    mosaic_status_parser.set_defaults(func=cmd_mosaic_status)

    mosaic_install_parser = mosaic_commands.add_parser("install", help="安装打码模型")
    _add_log_argument(mosaic_install_parser)
    mosaic_install_parser.add_argument("root", help="Publishing 根目录")
    mosaic_install_parser.add_argument(
        "--source",
        help="一次性迁移用的模型目录；不传时按 manifest URL 下载",
    )
    mosaic_install_parser.set_defaults(func=cmd_mosaic_install)

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

    schedule_parser = commands.add_parser("schedule", help="月度投稿计划管理")
    schedule_commands = schedule_parser.add_subparsers(dest="schedule_command")

    schedule_create_parser = schedule_commands.add_parser("create", help="创建月度计划")
    _add_log_argument(schedule_create_parser)
    schedule_create_parser.add_argument("root", help="Publishing 根目录")
    schedule_create_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_create_parser.add_argument("--default-import-id")
    schedule_create_parser.set_defaults(func=cmd_schedule_create)

    schedule_show_parser = schedule_commands.add_parser("show", help="查看月度计划")
    _add_log_argument(schedule_show_parser)
    schedule_show_parser.add_argument("root", help="Publishing 根目录")
    schedule_show_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_show_parser.set_defaults(func=cmd_schedule_show)

    for command, help_text, function in (
        ("add-entry", "增加投稿", cmd_schedule_add_entry),
        ("update-entry", "更新投稿", cmd_schedule_update_entry),
    ):
        entry_parser = schedule_commands.add_parser(command, help=help_text)
        _add_log_argument(entry_parser)
        entry_parser.add_argument("root", help="Publishing 根目录")
        entry_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
        entry_parser.add_argument("--entry-json", required=True, help="ScheduleEntry JSON 文件")
        entry_parser.add_argument("--expected-revision", type=int)
        entry_parser.set_defaults(func=function)

    schedule_move_parser = schedule_commands.add_parser("move-date", help="拖拽投稿到其他日期")
    _add_log_argument(schedule_move_parser)
    schedule_move_parser.add_argument("root", help="Publishing 根目录")
    schedule_move_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_move_parser.add_argument("entry_id")
    schedule_move_parser.add_argument("target_date", help="目标日期，格式 YYYY-MM-DD")
    schedule_move_parser.add_argument("--expected-revision", type=int)
    schedule_move_parser.set_defaults(func=cmd_schedule_move_date)

    schedule_delete_parser = schedule_commands.add_parser("delete-entry", help="删除投稿")
    _add_log_argument(schedule_delete_parser)
    schedule_delete_parser.add_argument("root", help="Publishing 根目录")
    schedule_delete_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_delete_parser.add_argument("entry_id")
    schedule_delete_parser.add_argument("--expected-revision", type=int)
    schedule_delete_parser.set_defaults(func=cmd_schedule_delete_entry)

    for command, help_text, function in (
        ("lock", "锁定月度计划", cmd_schedule_lock),
        ("unlock", "解锁月度计划", cmd_schedule_unlock),
    ):
        lock_parser = schedule_commands.add_parser(command, help=help_text)
        _add_log_argument(lock_parser)
        lock_parser.add_argument("root", help="Publishing 根目录")
        lock_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
        lock_parser.add_argument("--expected-revision", type=int)
        lock_parser.set_defaults(func=function)

    schedule_run_parser = schedule_commands.add_parser("run-due", help="执行到期投稿")
    _add_log_argument(schedule_run_parser)
    schedule_run_parser.add_argument("root", help="Publishing 根目录")
    schedule_run_parser.add_argument("--now", help="测试或手工执行时指定当前时间，必须含时区")
    schedule_run_parser.set_defaults(func=cmd_schedule_run_due)

    schedule_build_parser = schedule_commands.add_parser("build-now", help="立即构建指定投稿")
    _add_log_argument(schedule_build_parser)
    schedule_build_parser.add_argument("root", help="Publishing 根目录")
    schedule_build_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_build_parser.add_argument("entry_id")
    schedule_build_parser.set_defaults(func=cmd_schedule_build_now)

    schedule_retry_parser = schedule_commands.add_parser("retry", help="重试失败投稿")
    _add_log_argument(schedule_retry_parser)
    schedule_retry_parser.add_argument("root", help="Publishing 根目录")
    schedule_retry_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_retry_parser.add_argument("entry_id")
    schedule_retry_parser.set_defaults(func=cmd_schedule_retry)

    schedule_status_parser = schedule_commands.add_parser("status", help="查看计划和执行记录")
    _add_log_argument(schedule_status_parser)
    schedule_status_parser.add_argument("root", help="Publishing 根目录")
    schedule_status_parser.add_argument("month", help="计划月份，格式 YYYY-MM")
    schedule_status_parser.set_defaults(func=cmd_schedule_status)
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
        help="只处理指定导入快照；默认处理整个 Catalog，局部结果写入 exports/total，局部结果按导入名称写入 exports/<name>",
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


def cmd_mosaic_status(args) -> int:
    paths, config = load_workspace(args.root)
    manager = MosaicModelManager(paths, config.integrations.mosaic)
    _print_json(
        {
            "provider": config.integrations.mosaic.provider,
            "model_root": str(manager.model_root),
            "models": [item.as_dict() for item in manager.status()],
        }
    )
    return 0


def cmd_mosaic_install(args) -> int:
    paths, config = load_workspace(args.root)
    manager = MosaicModelManager(paths, config.integrations.mosaic)
    statuses = manager.install(args.source)
    _print_json(
        {
            "provider": config.integrations.mosaic.provider,
            "model_root": str(manager.model_root),
            "models": [item.as_dict() for item in statuses],
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


def cmd_schedule_create(args) -> int:
    result = PublishingService().schedule_create(
        args.root,
        args.month,
        default_import_id=args.default_import_id,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_show(args) -> int:
    result = PublishingService().schedule_show(args.root, args.month)
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_add_entry(args) -> int:
    entry = _read_schedule_entry(args.entry_json)
    result = PublishingService().schedule_add_entry(
        args.root,
        args.month,
        entry,
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_update_entry(args) -> int:
    entry = _read_schedule_entry(args.entry_json)
    result = PublishingService().schedule_update_entry(
        args.root,
        args.month,
        entry,
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_move_date(args) -> int:
    result = PublishingService().schedule_move_date(
        args.root,
        args.month,
        args.entry_id,
        date.fromisoformat(args.target_date),
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_delete_entry(args) -> int:
    result = PublishingService().schedule_delete_entry(
        args.root,
        args.month,
        args.entry_id,
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_lock(args) -> int:
    result = PublishingService().schedule_lock(
        args.root,
        args.month,
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_unlock(args) -> int:
    result = PublishingService().schedule_unlock(
        args.root,
        args.month,
        expected_revision=args.expected_revision,
    )
    _print_json(result.model_dump(mode="json", by_alias=True))
    return 0


def cmd_schedule_run_due(args) -> int:
    now = datetime.fromisoformat(args.now) if args.now else None
    records = PublishingService().schedule_run_due(args.root, now=now)
    _print_json([record.model_dump(mode="json") for record in records])
    return 0


def cmd_schedule_build_now(args) -> int:
    result = PublishingService().schedule_build_now(
        args.root,
        args.month,
        args.entry_id,
    )
    _print_json(result.model_dump(mode="json"))
    return 0


def cmd_schedule_retry(args) -> int:
    result = PublishingService().schedule_retry(
        args.root,
        args.month,
        args.entry_id,
    )
    _print_json(result.model_dump(mode="json") if result is not None else None)
    return 0


def cmd_schedule_status(args) -> int:
    _print_json(PublishingService().schedule_status(args.root, args.month))
    return 0


def _read_schedule_entry(path: str | Path) -> ScheduleEntry:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 ScheduleEntry JSON：{path}：{exc}") from exc
    return ScheduleEntry.model_validate(data)


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
