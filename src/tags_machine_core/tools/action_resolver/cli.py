from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tags_machine_core.config import load_config

from .models import ResolvedAction
from .resolver import deduplicate_resolved_actions, resolve_generated_actions


STRICT_FAILURE_STATUSES = {"category_fallback", "ambiguous", "unresolved", "read_error"}


def add_action_resolver_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    output_parent: argparse.ArgumentParser | None = None,
) -> None:
    parents = [output_parent] if output_parent is not None else []
    parser = subparsers.add_parser(
        "resolve-actions",
        parents=parents,
        help="Resolve generated image inputs to Action node directories",
    )
    add_arguments(parser)
    parser.set_defaults(func=cmd_resolve_actions)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Legacy images or core task/output directories")
    parser.add_argument("--config", type=Path, help="Core config containing legacy.design_root")
    parser.add_argument("--design-root", type=Path, help="Override legacy.design_root")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--table", action="store_true", help="Print one tabular row per result")
    output.add_argument("--json", action="store_true", help="Print structured JSON results")
    parser.add_argument(
        "--per-input",
        action="store_true",
        help="Keep each evidence record instead of aggregating duplicate results",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return 1 when a result is not resolved to a new/ node",
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tags_machine_core.tools.action_resolver",
        description="Resolve generated images to Action node directories.",
    )
    add_arguments(parser)
    args = parser.parse_args(argv)
    return cmd_resolve_actions(args)


def cmd_resolve_actions(args: argparse.Namespace) -> int:
    try:
        design_root = _resolve_design_root(
            config_path=getattr(args, "config", None),
            design_root=getattr(args, "design_root", None),
        )
        results = resolve_generated_actions(args.inputs, design_root=design_root)
        display_results = (
            results
            if args.per_input
            else [
                item
                for item in deduplicate_resolved_actions(results)
                if item.status != "missing_action"
            ]
        )
        if args.json:
            print(json.dumps([item.as_dict() for item in display_results], ensure_ascii=False, indent=2))
        elif args.table:
            _print_table(display_results)
        else:
            _print_paths(display_results)
        if args.strict and any(item.status in STRICT_FAILURE_STATUSES for item in results):
            return 1
        return 0
    except Exception as exc:
        print(f"resolve-actions failed: {exc}", file=sys.stderr)
        return 2


def _resolve_design_root(
    *,
    config_path: Path | None,
    design_root: Path | None,
) -> Path:
    if design_root is not None:
        return design_root.expanduser().resolve()
    resolved_config = config_path or _default_config_path()
    resolved_config = _prefer_local_config_path(resolved_config.expanduser().resolve())
    config = load_config(resolved_config)
    return config.legacy.design_root.expanduser().resolve()


def _default_config_path() -> Path:
    project_root = Path(__file__).resolve().parents[4]
    return project_root / "configs" / "local.example.yaml"


def _prefer_local_config_path(path: Path) -> Path:
    if path.name != "local.example.yaml":
        return path
    local = path.with_name("local.yaml")
    return local if local.is_file() else path


def _print_paths(results: list[ResolvedAction]) -> None:
    seen: set[str] = set()
    for result in results:
        if not result.relative_path or result.relative_path in seen:
            continue
        seen.add(result.relative_path)
        print(str(Path(result.relative_path)))


def _print_table(results: list[ResolvedAction]) -> None:
    print("status\tsource\taction\ttopic\tpath\treason")
    for result in results:
        print(
            "\t".join(
                [
                    result.status,
                    result.evidence.source_kind,
                    result.evidence.action,
                    result.evidence.topic,
                    result.relative_path,
                    result.reason,
                ]
            )
        )
