"""`tm-core contract show / context / check / prompt`：给 Agent 用的契约命令（§8.1）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from tags_machine_core.logging_config import get_logger

from .parser import ContractParseError
from .service import ContractService

logger = get_logger(__name__)
CONFIG_ENV_VAR = "TAGS_MACHINE_CONFIG"
DEFAULT_CONFIGS = (Path("configs/local.yaml"), Path("configs/cloud.yaml"), Path("configs/local.example.yaml"))


def add_contract_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    output_parent: argparse.ArgumentParser | None = None,
) -> None:
    contract = subparsers.add_parser("contract", help="Agent 拼接契约：查看请求、取素材、校验")
    commands = contract.add_subparsers(dest="contract_command")
    parents = [output_parent] if output_parent is not None else []

    show = commands.add_parser("show", parents=parents, help="契约的请求部分、目标格式摘要和已写的帧")
    _add_common(show)
    show.set_defaults(func=lambda args: _run(args, lambda svc: svc.show(args.id)))

    context = commands.add_parser("context", parents=parents, help="角色分区词表、动作组成员内容、服装、背景")
    _add_common(context)
    context.add_argument("--member", type=int, help="只取动作组第 N 个成员（从 1 开始）")
    context.set_defaults(func=lambda args: _run(args, lambda svc: svc.context(args.id, member=args.member)))

    check = commands.add_parser("check", parents=parents, help="解析 + 校验，输出 issues；有 error 时退出码为 1")
    _add_common(check)
    check.set_defaults(func=cmd_check)

    prompt = commands.add_parser("prompt", parents=parents, help="输出给外部 agent 的要求 prompt")
    _add_common(prompt)
    prompt.add_argument("--kind", choices=("tools", "standalone"), default="tools")
    prompt.set_defaults(func=cmd_prompt)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", help="契约 id（契约文件名，不含 .md）")
    parser.add_argument("--config", type=Path, help="应用配置；默认 $TAGS_MACHINE_CONFIG 或 configs/local.yaml")
    parser.add_argument("--root", type=Path, help="契约目录；默认 contract.root 或 <design_root>/动作改2/contracts")


def build_service(config_path: Path | None, root: Path | None = None) -> ContractService:
    from tags_machine_core.config import contract_root, load_config

    path = config_path or _default_config_path()
    config = load_config(path)
    return ContractService(
        root=root or contract_root(config),
        design_root=config.legacy.design_root,
        output_dir=config.runtime.output_dir,
        formats_dir=config.contract.formats_dir,
        config_path=path,
    )


def _default_config_path() -> Path:
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        return Path(env)
    for candidate in DEFAULT_CONFIGS:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("找不到应用配置，请用 --config 指定")


def cmd_check(args: argparse.Namespace) -> int:
    result: dict[str, Any] = {}

    def operation(svc: ContractService) -> dict[str, Any]:
        result.update(svc.check(args.id))
        return result

    code = _run(args, operation)
    if code == 0 and not result.get("ok", False):
        return 1
    return code


def cmd_prompt(args: argparse.Namespace) -> int:
    try:
        text = build_service(args.config, args.root).prompt(args.id, args.kind)["text"]
    except (FileNotFoundError, ValueError, ContractParseError, OSError) as exc:
        print(f"contract command failed: {exc}", file=sys.stderr)
        return 2
    _write(text)
    return 0


def _run(args: argparse.Namespace, operation) -> int:
    try:
        payload = operation(build_service(args.config, args.root))
    except (FileNotFoundError, KeyError, ValueError, ContractParseError, OSError) as exc:
        logger.error("contract command failed: %s", exc)
        print(f"contract command failed: {exc}", file=sys.stderr)
        return 2
    _write(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _write(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
