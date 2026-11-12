"""`tm-core contract …`：新建 / 复制、取素材、校验、生图与复核。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from tags_machine_core.logging_config import get_logger

from .parser import ContractParseError
from .review import results_report, review_contract
from .service import ContractService

logger = get_logger(__name__)
CONFIG_ENV_VAR = "TAGS_MACHINE_CONFIG"
DEFAULT_CONFIGS = (Path("configs/local.yaml"), Path("configs/cloud.yaml"), Path("configs/local.example.yaml"))


def add_contract_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    output_parent: argparse.ArgumentParser | None = None,
) -> None:
    contract = subparsers.add_parser("contract", help="Agent 拼接契约：取素材、校验、生图与复核")
    commands = contract.add_subparsers(dest="contract_command")
    parents = [output_parent] if output_parent is not None else []

    create = commands.add_parser("create", parents=parents, help="新建契约（等同 Web 的「新建并生成要求」）")
    _add_config(create)
    create.add_argument("--action-group", required=True, help="动作组 ref（st_* / stn_*）")
    create.add_argument("--character", action="append", required=True, help="角色节点 ref；多个角色重复写，依次为 c1、c2…")
    _add_request_options(create)
    create.set_defaults(func=cmd_create)

    clone = commands.add_parser("clone", parents=parents, help="基于已有契约新建：复制请求部分，可替换定制要求和选项")
    _add_common(clone)
    clone.add_argument("--action-group", help="换一个动作组")
    clone.add_argument("--character", action="append", help="换角色；写了就整组替换")
    clone.add_argument("--with-frames", action="store_true", help="连已写的帧一起复制（在旧版上修改时用）")
    _add_request_options(clone)
    clone.set_defaults(func=cmd_clone)

    show = commands.add_parser("show", parents=parents, help="契约的请求部分、目标格式摘要和已写的帧")
    _add_common(show)
    show.add_argument("--frames", help="只列这些帧，如 f01-f30、f01,f05,f10-f12")
    show.add_argument("--summary", action="store_true", help="每帧只给标题、来源、角色和 token 数，不给提示词")
    show.set_defaults(func=lambda args: _run(args, lambda svc: svc.show(args.id, frames=args.frames, summary=args.summary)))

    context = commands.add_parser("context", parents=parents, help="角色分区词表、动作组成员内容、服装、背景")
    _add_common(context)
    context.add_argument("--member", type=int, help="只取动作组第 N 个成员（从 1 开始）")
    context.add_argument("--members", help="只取这些成员，如 1-20、3,5,8-10、30-（到最后）")
    context.add_argument("--summary", action="store_true", help="成员只给序号、标题、ref 和分类，不给提示词；先用它看全组结构")
    context.set_defaults(
        func=lambda args: _run(args, lambda svc: svc.context(args.id, member=args.member, members=args.members, summary=args.summary))
    )

    check = commands.add_parser("check", parents=parents, help="解析 + 校验，输出 issues；有 error 时退出码为 1")
    _add_common(check)
    check.set_defaults(func=cmd_check)

    prompt = commands.add_parser("prompt", parents=parents, help="输出给外部 agent 的要求 prompt")
    _add_common(prompt)
    prompt.add_argument("--kind", choices=("tools", "standalone"), default="tools")
    prompt.set_defaults(func=cmd_prompt)

    artists = commands.add_parser("artists", parents=parents, help="列出后台可用画风及 ref，供用户指定")
    artists.add_argument("--server", help="后台 URL；默认 PROMPTATELIER_URL 或 runtime/dev_web.json")
    artists.add_argument("--query", default="", help="画风搜索词")
    artists.set_defaults(func=cmd_artists)

    generate = commands.add_parser("generate", parents=parents, help="按契约生图（需先询问用户指定画风；复用 Web 后台任务）")
    generate.add_argument("id", help="后台中的契约 id")
    generate.add_argument("--artist", required=True, help="用户指定的画风 ref（contract artists 可查）")
    generate.add_argument("--frames", help="指定示例帧，如 f01,f05 或 f01-f03；省略时生成全部帧")
    generate.add_argument("--nt", type=int, default=1, help="每帧张数")
    generate.add_argument("--seed", type=int, help="省略或负数表示随机")
    generate.add_argument("--size", choices=("contract", "random", "portrait", "landscape", "square", "custom"), default="contract")
    generate.add_argument("--width", type=int, default=832)
    generate.add_argument("--height", type=int, default=1216)
    generate.add_argument("--negative", default="", help="追加负面提示词")
    generate.add_argument("--character-prompts", choices=("auto", "off"), default="auto")
    generate.add_argument("--add-male-caption", action="store_true")
    generate.add_argument("--comfyui-target", help="ComfyUI 运行位置")
    generate.add_argument("--force", action="store_true", help="重新生成，不复用相同参数的成功结果")
    generate.add_argument("--dry-run", action="store_true", help="只返回最终提示词、参数和 token 检查；不生图")
    generate.add_argument("--allow-over-limit", action="store_true", help="允许提交超出 token 上限的提示词")
    _add_remote_options(generate)
    generate.set_defaults(func=cmd_generate)

    job = commands.add_parser("job", parents=parents, help="查看契约出图任务；可等待完成并返回图片路径")
    job.add_argument("id", help="出图任务 id")
    _add_remote_options(job)
    job.set_defaults(func=cmd_generation_job)

    results = commands.add_parser("results", parents=parents, help="每帧的出图状态、最新一轮的图、各轮次和失败原因")
    _add_common(results)
    _add_result_filters(results)
    results.add_argument("--all", action="store_true", help="列出每帧全部图片，而不只是最新一轮")
    results.set_defaults(func=lambda args: _run(args, lambda svc: results_report(
        svc, args.id, frames=args.frames, artist=args.artist, current_only=args.current_only, all_images=args.all,
    )))

    review = commands.add_parser("review", parents=parents, help="出图复核：代表图、元数据检查、连续性问题、待办；--sheets 生成联系表")
    _add_common(review)
    _add_result_filters(review)
    review.add_argument("--sheets", action="store_true", help="生成联系表（总览 + 每帧候选），路径见输出的 sheets")
    review.add_argument("--out", type=Path, help="联系表目录；默认 <出图目录>/.contract_review/<id>")
    review.add_argument("--per-frame", type=int, default=8, help="每帧最多列几张候选（默认 8）")
    review.set_defaults(func=lambda args: _run(args, lambda svc: review_contract(
        svc, args.id, frames=args.frames, artist=args.artist, current_only=args.current_only,
        sheets=args.sheets, out_dir=args.out, per_frame=max(1, args.per_frame),
    )))


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="应用配置；默认 $TAGS_MACHINE_CONFIG 或 configs/local.yaml")
    parser.add_argument("--root", type=Path, help="契约目录；默认 contract.root 或 <design_root>/动作改2/contracts")


def _add_remote_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", help="后台 URL；默认 PROMPTATELIER_URL 或 runtime/dev_web.json；使用该后台的配置和契约目录")
    parser.add_argument("--wait", action="store_true", help="等待任务结束，返回逐帧结果与图片绝对路径")
    parser.add_argument("--timeout", type=float, default=600, help="等待上限（秒）；超时任务仍在后台继续，稍后用 contract job 查看")


def _remote(args: argparse.Namespace, operation) -> int:
    from .generation_client import GenerationClient

    try:
        if getattr(args, "timeout", 0) < 0:
            raise ValueError("timeout 不能为负数")
        client = GenerationClient(args.server)
        with client.session:
            result = operation(client)
    except (ValueError, OSError) as exc:
        print(f"contract command failed: {exc}", file=sys.stderr)
        return 2
    _write(json.dumps(result, ensure_ascii=False, indent=2))
    counts = (result.get("result") or {}).get("counts") or {}
    return 1 if result.get("status") in {"failed", "cancelled", "interrupted"} or result.get("wait_timed_out") or counts.get("failed") else 0


def cmd_artists(args: argparse.Namespace) -> int:
    return _remote(args, lambda client: client.request("GET", "/nodes", params={"role": "artist", "q": args.query, "limit": 100}))


def cmd_generate(args: argparse.Namespace) -> int:
    def operation(client):
        payload = {key: getattr(args, key) for key in (
            "artist", "frames", "nt", "seed", "size", "width", "height", "negative", "character_prompts",
            "add_male_caption", "comfyui_target", "dry_run", "allow_over_limit",
        )}
        payload["skip_duplicates"] = not args.force
        result = client.generate(args.id, payload)
        if args.wait and not args.dry_run:
            return client.job(result["id"], wait=True, timeout=args.timeout)
        return result

    return _remote(args, operation)


def cmd_generation_job(args: argparse.Namespace) -> int:
    return _remote(args, lambda client: client.job(args.id, wait=args.wait, timeout=args.timeout))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", help="契约 id（契约文件名，不含 .md）")
    _add_config(parser)


def _add_result_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frames", help="只看这些帧，如 f01-f30")
    parser.add_argument("--artist", help="只看这个画风（画风名，同 Web 故事板的画风筛选）")
    parser.add_argument("--current-only", action="store_true", help="只看用当前提示词出的图")


def _add_request_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--clothing", help="服装节点 ref")
    parser.add_argument("--background", help="背景节点 ref")
    parser.add_argument("--format", dest="target_format", help="目标格式 id，如 nai-v4.5")
    text = parser.add_mutually_exclusive_group()
    text.add_argument("--requirements", help="定制要求（自然语言）")
    text.add_argument("--requirements-file", type=Path, help="从文件读定制要求（UTF-8）")
    order = parser.add_mutually_exclusive_group()
    order.add_argument("--keep-order", dest="keep_order", action="store_true", default=None, help="保持动作组顺序")
    order.add_argument("--no-keep-order", dest="keep_order", action="store_false", help="允许重排帧顺序")
    frames = parser.add_mutually_exclusive_group()
    frames.add_argument("--allow-new-frames", dest="allow_new_frames", action="store_true", default=None)
    frames.add_argument("--no-new-frames", dest="allow_new_frames", action="store_false", help="不允许新增帧")
    parser.add_argument("--max-new-frames", type=int, help="最多新增几帧")


def _request_payload(args: argparse.Namespace) -> dict[str, Any]:
    requirements = args.requirements
    if args.requirements_file is not None:
        requirements = args.requirements_file.read_text(encoding="utf-8")
    options = {
        key: value
        for key, value in (("keep_order", args.keep_order), ("allow_new_frames", args.allow_new_frames), ("max_new_frames", args.max_new_frames))
        if value is not None
    }
    payload: dict[str, Any] = {
        "action_group": getattr(args, "action_group", None),
        "characters": getattr(args, "character", None),
        "clothing": args.clothing,
        "background": args.background,
        "target_format": args.target_format,
        "requirements": requirements,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    if options:
        payload["options"] = options
    return payload


def _created(svc: ContractService, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail["id"],
        "path": detail["file"]["path"],
        "status": detail["request"]["status"],
        "target_format": detail["request"]["target_format"],
        "frame_count": len(detail["frames"]),
        "issue_counts": detail["issue_counts"],
        "next": f"{svc.cli} contract prompt {detail['id']}{svc.config_arg}{svc.root_arg}",
    }


def cmd_create(args: argparse.Namespace) -> int:
    return _run(args, lambda svc: _created(svc, svc.create(_request_payload(args))))


def cmd_clone(args: argparse.Namespace) -> int:
    return _run(args, lambda svc: _created(svc, svc.clone(args.id, _request_payload(args), with_frames=args.with_frames)))


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
        root_arg=f" --root {root}" if root else "",
        cli="uv run tm-core",
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
