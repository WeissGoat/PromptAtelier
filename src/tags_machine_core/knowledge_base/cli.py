from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tags_machine_core.logging_config import get_logger

from .catalog import CatalogStore
from .config import load_knowledge_base_config
from .importer import import_catalog
from .query import ActionSearchFilters, audit_catalog, build_facets, search_actions, show_action

logger = get_logger(__name__)


def add_knowledge_base_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    output_parent: argparse.ArgumentParser | None = None,
) -> None:
    kb = subparsers.add_parser("kb", help="Import and query the action knowledge base")
    commands = kb.add_subparsers(dest="kb_command")
    parents = [output_parent] if output_parent is not None else []

    import_parser = commands.add_parser("import", parents=parents, help="Build the action Catalog")
    _add_common(import_parser)
    import_parser.set_defaults(func=cmd_import)

    audit_parser = commands.add_parser("audit", parents=parents, help="Show Catalog warnings")
    _add_common(audit_parser)
    audit_parser.set_defaults(func=cmd_audit)

    facets_parser = commands.add_parser("facets", parents=parents, help="Count Catalog facets")
    _add_common(facets_parser)
    facets_parser.set_defaults(func=cmd_facets)

    search_parser = commands.add_parser("search", parents=parents, help="Search action Catalog")
    _add_common(search_parser)
    for field in (
        "source",
        "phase",
        "species",
        "cast",
        "domain",
        "subtype",
        "pose",
        "environment",
        "tone",
        "flags",
        "clothing",
        "character-scope",
    ):
        search_parser.add_argument(f"--{field}", action="append")
    search_parser.add_argument("--text")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--all-sources", action="store_true")
    search_parser.set_defaults(func=cmd_search)

    show_parser = commands.add_parser("show", parents=parents, help="Show one exact action ref")
    _add_common(show_parser)
    show_parser.add_argument("ref")
    show_parser.set_defaults(func=cmd_show)


def cmd_import(args: argparse.Namespace) -> int:
    return _run(args, lambda config: import_catalog(config).model_dump(by_alias=True, mode="json"))


def cmd_audit(args: argparse.Namespace) -> int:
    return _run(args, lambda config: audit_catalog(CatalogStore.from_config(config).load_current()))


def cmd_facets(args: argparse.Namespace) -> int:
    return _run(args, lambda config: build_facets(CatalogStore.from_config(config).load_current()))


def cmd_search(args: argparse.Namespace) -> int:
    def execute(config):
        filters = ActionSearchFilters(
            source=args.source,
            phase=args.phase,
            species=args.species,
            cast=args.cast,
            domain=args.domain,
            subtype=args.subtype,
            pose=args.pose,
            environment=args.environment,
            tone=args.tone,
            flags=args.flags,
            clothing=args.clothing,
            character_scope=args.character_scope,
            text=args.text,
            limit=args.limit,
            all_sources=args.all_sources,
        )
        return search_actions(CatalogStore.from_config(config).load_current(), filters)

    return _run(args, execute)


def cmd_show(args: argparse.Namespace) -> int:
    return _run(
        args,
        lambda config: show_action(CatalogStore.from_config(config).load_current(), args.ref),
    )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--format", default="json", choices=("json", "yaml"))


def _run(args: argparse.Namespace, operation) -> int:
    try:
        config = load_knowledge_base_config(args.config)
        payload = operation(config)
        _print_payload(payload, args.format)
        return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError, ValidationError, OSError) as exc:
        logger.error("knowledge base command failed: %s", exc)
        print(f"knowledge base command failed: {exc}", file=sys.stderr)
        return 2


def _print_payload(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "yaml":
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text, end="" if text.endswith("\n") else "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
        if not text.endswith("\n"):
            sys.stdout.buffer.write(b"\n")
