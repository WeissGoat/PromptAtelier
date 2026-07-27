"""旧 tags.txt 迁移工具的命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.json_tools import sanitize_json_for_display

from .migration import (
    apply_legacy_tags_migration,
    audit_legacy_tags,
    migrate_legacy_action_tags,
    migrate_legacy_artist_tags,
    migrate_legacy_background_tags,
    migrate_legacy_character_tags,
    plan_legacy_tags_migration,
)
from .sync_action_meta import ActionMetaSyncLockedError, sync_action_meta


def _write_output(data: dict[str, Any], path: Path, output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "auto":
        output_format = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    if output_format == "yaml":
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _print(data: dict[str, Any], *, full: bool) -> None:
    print(json.dumps(sanitize_json_for_display(data, full=full), ensure_ascii=False, indent=2))


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output")
    parser.add_argument("--format", default="auto", choices=("auto", "json", "yaml"))
    parser.add_argument("--full", action="store_true")


def _add_migrate_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source")
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--output")
    parser.add_argument("--format", default="auto", choices=("auto", "json", "yaml"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--full", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线迁移旧 tags.txt 与结构化节点")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("migrate-artist-tags", "迁移旧 artist tags.txt"),
        ("migrate-action-tags", "迁移旧 action tags.txt"),
        ("migrate-character-tags", "迁移旧 character tags.txt"),
        ("migrate-background-tags", "迁移旧 background tags.txt"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_migrate_options(command)
    subparsers.choices["migrate-action-tags"].add_argument("--character-scope")
    subparsers.choices["migrate-character-tags"].add_argument("--character-id")
    subparsers.choices["migrate-character-tags"].add_argument("--variant")

    audit = subparsers.add_parser("audit-legacy-tags", help="审计旧 tags.txt")
    audit.add_argument("source")
    audit.add_argument("--kind", required=True, choices=("artist", "character", "action", "background"))
    _add_output_options(audit)

    plan = subparsers.add_parser("plan-legacy-tags-migration", help="生成迁移计划")
    plan.add_argument("source")
    plan.add_argument("--kind", required=True, choices=("artist", "character", "action", "background"))
    plan.add_argument("--output-root", required=True)
    _add_output_options(plan)

    apply = subparsers.add_parser("apply-legacy-tags-migration", help="写出 ready 迁移节点")
    apply.add_argument("source")
    apply.add_argument("--kind", required=True, choices=("artist", "character", "action", "background"))
    apply.add_argument("--output-root", required=True)
    _add_output_options(apply)

    sync = subparsers.add_parser(
        "sync-action-meta",
        help="同步动作目录的 meta.yaml 与 clothing 元数据",
    )
    sync.add_argument("root", help="动作根目录或单个动作节点目录")
    sync.add_argument("--write", action="store_true", help="写入 meta.yaml；默认只预览")
    sync.add_argument("--backup", action="store_true", help="更新已有 meta.yaml 前创建 .bak")
    sync.add_argument("--no-lock", action="store_true", help="关闭写模式的根目录运行锁")
    sync.add_argument("--report", help="写入完整 JSON 报告")
    sync.add_argument("--full", action="store_true", help="在标准输出显示完整报告")
    return parser


def _migrate(args) -> dict[str, Any]:
    migrator = {
        "migrate-artist-tags": migrate_legacy_artist_tags,
        "migrate-action-tags": migrate_legacy_action_tags,
        "migrate-character-tags": migrate_legacy_character_tags,
        "migrate-background-tags": migrate_legacy_background_tags,
    }[args.command]
    kwargs = {"node_id": args.id, "name": args.name}
    if args.command == "migrate-action-tags":
        kwargs["character_scope"] = args.character_scope
    elif args.command == "migrate-character-tags":
        kwargs["character_id"] = args.character_id
        kwargs["variant"] = args.variant
    return migrator(args.source, **kwargs)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sync-action-meta":
        try:
            data = sync_action_meta(
                Path(args.root),
                write=args.write,
                backup=args.backup,
                lock=not args.no_lock,
            )
        except (ActionMetaSyncLockedError, FileNotFoundError, ValueError) as exc:
            print(f"sync-action-meta failed: {exc}", file=sys.stderr)
            return 2
        if args.report:
            _write_output(data, Path(args.report), "json")
            _print(data["summary"], full=True)
        else:
            _print(data, full=args.full)
        return 1 if data["summary"]["errors"] else 0
    if args.command.startswith("migrate-"):
        data = _migrate(args)
    elif args.command == "audit-legacy-tags":
        data = audit_legacy_tags(args.source, kind=args.kind)
    elif args.command == "plan-legacy-tags-migration":
        data = plan_legacy_tags_migration(args.source, kind=args.kind, output_root=args.output_root)
    else:
        data = apply_legacy_tags_migration(args.source, kind=args.kind, output_root=args.output_root)

    output = getattr(args, "output", None)
    if output:
        output_path = Path(output)
        if args.command.startswith("migrate-") and output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"Output already exists, pass --overwrite to replace: {output_path}"
            )
        _write_output(data, output_path, args.format)
    _print(data, full=args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
