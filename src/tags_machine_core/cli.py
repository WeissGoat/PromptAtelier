from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from tags_machine_core.clients import ComfyUIClient, NovelAIClient, SDClient
from tags_machine_core.composers import load_agent_result
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.config import load_config
from tags_machine_core.contracts import GeneratedImage, GenerationResult, RenderRequest
from tags_machine_core.json_tools import sanitize_json_for_display
from tags_machine_core.nodes import NodeReader, migrate_legacy_style_tags
from tags_machine_core.renderers import NovelAIStyleRepository
from tags_machine_core.services import GenerationService
from tags_machine_core.verification import (
    build_acceptance_record,
    compare_render_parameters,
    load_render_parameter_source,
    normalize_render_parameters,
    parse_whitelist_args,
    read_image_parameters,
    verify_acceptance_record,
    verify_acceptance_suite,
)


RENDER_BACKENDS = ("novelai", "comfyui", "sd")


def print_json(value, *, full: bool = False) -> None:
    data = sanitize_json_for_display(value, full=full)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_compose(args) -> int:
    service = GenerationService()
    bundle = _build_bundle(service, args)
    print_json(bundle, full=args.full)
    return 0


def cmd_compose_nodes(args) -> int:
    service = GenerationService()
    bundle = _build_bundle_from_nodes(service, args, style_ref=args.style_ref)
    print_json(bundle, full=args.full)
    return 0


def cmd_agent_task_nodes(args) -> int:
    service = GenerationService()
    character, action, background = _read_node_inputs(args)
    task = service.build_agent_composition_task(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        style_ref=args.style_ref,
        character_scope=args.character_scope or args.body_scope,
        instructions=args.instruction or [],
    )
    print_json(task, full=args.full)
    return 0


def cmd_compose_agent_nodes(args) -> int:
    service = GenerationService()
    character, action, background = _read_node_inputs(args)
    cache = PromptCache(args.cache_dir) if args.cache_dir else None
    result = load_agent_result(args.agent_result) if args.agent_result else None
    bundle = service.compose_nodes_with_agent(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        style_ref=args.style_ref,
        character_scope=args.character_scope or args.body_scope,
        instructions=args.instruction or [],
        result=result,
        cache=cache,
    )
    print_json(bundle, full=args.full)
    return 0


def cmd_render_plan(args) -> int:
    service = GenerationService()
    style_ref, style = _load_render_style(args)
    bundle = _build_bundle(service, args, style_ref=style_ref)
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
        action=_render_action(args.backend),
        params=_load_json_arg(args.params_json),
    )
    print_json(request, full=args.full)
    return 0


def cmd_render_plan_nodes(args) -> int:
    service = GenerationService()
    style_ref, style = _load_render_style(args)
    bundle = _build_bundle_from_nodes(service, args, style_ref=style_ref)
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
        action=_render_action(args.backend),
        params=_load_json_arg(args.params_json),
    )
    print_json(request, full=args.full)
    return 0


def cmd_generate(args) -> int:
    config = load_config(Path(args.config))
    service = GenerationService()
    style = None
    style_ref = args.style_ref or config.defaults.style_ref
    if style_ref:
        style = NovelAIStyleRepository(config.legacy.design_root).load(style_ref)
    bundle = _build_bundle(service, args, style_ref=style_ref)
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
        params=_load_json_arg(args.params_json),
    )
    access_token = os.environ.get(config.novelai.access_token_env)
    if not access_token:
        raise RuntimeError(
            f"Missing NovelAI token environment variable: {config.novelai.access_token_env}"
        )
    client = NovelAIClient(
        access_token=access_token,
        base_url=config.novelai.base_url,
        timeout=config.novelai.timeout,
        retry=config.novelai.retry,
    )
    images = client.generate_images(request)
    output_dir = Path(args.output_dir or config.runtime.output_dir)
    generated_images = _save_generated_images(
        images,
        output_dir=output_dir,
        request=request,
        default_format=config.defaults.image_format,
    )
    result = GenerationResult(
        backend="novelai",
        images=generated_images,
        request_body=client.build_payload(request),
        png_info=_collect_png_info(generated_images),
        cache_hit=False,
    )
    print_json(result, full=args.full)
    return 0


def cmd_execute_render_request(args) -> int:
    config = load_config(Path(args.config))
    request = _load_render_request(args.request)
    output_dir = Path(args.output_dir or config.runtime.output_dir)

    if request.backend == "novelai":
        access_token = os.environ.get(config.novelai.access_token_env)
        if not access_token:
            raise RuntimeError(
                f"Missing NovelAI token environment variable: {config.novelai.access_token_env}"
            )
        client = NovelAIClient(
            access_token=access_token,
            base_url=config.novelai.base_url,
            timeout=config.novelai.timeout,
            retry=config.novelai.retry,
        )
        images = _save_generated_images(
            client.generate_images(request),
            output_dir=output_dir,
            request=request,
            default_format=config.defaults.image_format,
        )
        result = GenerationResult(
            backend="novelai",
            images=images,
            request_body=client.build_payload(request),
            png_info=_collect_png_info(images),
            cache_hit=False,
        )
    elif request.backend == "comfyui":
        client = ComfyUIClient(
            base_url=config.comfyui.base_url,
            timeout=config.comfyui.timeout,
        )
        queued = client.queue_prompt(request, client_id=args.client_id)
        result = GenerationResult(
            backend="comfyui",
            images=[],
            request_body=client.build_payload(request, client_id=args.client_id),
            png_info={"comfyui": {"prompt_id": queued.prompt_id, "raw": queued.raw}},
            cache_hit=False,
        )
    elif request.backend == "sd":
        client = SDClient(
            base_url=config.sd.base_url,
            timeout=config.sd.timeout,
        )
        images = _save_generated_images(
            client.generate_images(request),
            output_dir=output_dir,
            request=request,
            default_format=config.defaults.image_format,
        )
        result = GenerationResult(
            backend="sd",
            images=images,
            request_body=client.build_payload(request),
            png_info=_collect_png_info(images),
            cache_hit=False,
        )
    else:
        raise ValueError(f"Unsupported backend: {request.backend}")

    print_json(result, full=args.full)
    return 0


def cmd_inspect_style(args) -> int:
    config = load_config(Path(args.config))
    style = NovelAIStyleRepository(config.legacy.design_root).load(args.style_ref)
    print_json(style, full=args.full)
    return 0


def cmd_inspect_node(args) -> int:
    node = NodeReader().read(args.path)
    print_json(node, full=args.full)
    return 0


def cmd_config(args) -> int:
    config = load_config(Path(args.path))
    print_json(config, full=args.full)
    return 0


def cmd_inspect_image_params(args) -> int:
    params = read_image_parameters(args.path)
    if args.normalized:
        params = normalize_render_parameters(params)
    print_json(params, full=args.full)
    return 0


def cmd_compare_render_params(args) -> int:
    left = load_render_parameter_source(args.left)
    right = load_render_parameter_source(args.right)
    diffs = compare_render_parameters(left, right)
    result = {
        "match": not diffs,
        "diff_count": len(diffs),
        "diffs": [diff.as_dict() for diff in diffs],
    }
    if args.show_normalized:
        result["left_normalized"] = normalize_render_parameters(left)
        result["right_normalized"] = normalize_render_parameters(right)
    print_json(result, full=args.full)
    return 0 if not diffs else 2


def cmd_create_acceptance_record(args) -> int:
    record = build_acceptance_record(
        case_id=args.case_id,
        legacy_source=args.legacy_source,
        core_source=args.core_source,
        legacy_image=args.legacy_image,
        core_image=args.core_image,
        prompt_bundle=args.prompt_bundle,
        whitelist=parse_whitelist_args(args.whitelist),
        notes=args.note or [],
    )
    if args.output:
        _write_structured_output(record, Path(args.output), output_format=args.format)
    print_json(record, full=args.full)
    return 0 if record["result"] == "pass" else 2


def cmd_verify_acceptance_record(args) -> int:
    result = verify_acceptance_record(args.record)
    print_json(result, full=args.full)
    return 0 if result["match"] else 2


def cmd_verify_acceptance_suite(args) -> int:
    result = verify_acceptance_suite(
        args.path,
        required_cases=args.required_case,
        require_minimum_set=args.require_minimum_set,
    )
    print_json(result, full=args.full)
    return 0 if result["match"] else 2


def cmd_migrate_style_tags(args) -> int:
    node = migrate_legacy_style_tags(
        args.source,
        node_id=args.id,
        name=args.name,
    )
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(f"Output already exists, pass --overwrite to replace: {output_path}")
        _write_structured_output(node, output_path, output_format=args.format)
    print_json(node, full=args.full)
    return 0


def _load_json_arg(value: str | None) -> dict:
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("--params-json must be a JSON object")
    return data


def _load_render_request(path: str | Path) -> RenderRequest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected RenderRequest JSON object: {path}")
    return RenderRequest.model_validate(data)


def _build_bundle(service: GenerationService, args, *, style_ref: str | None = None):
    return service.compose_full_prompt(
        prompt=args.prompt,
        negative=args.negative or "",
        style_ref=style_ref if style_ref is not None else args.style_ref,
    )


def _build_bundle_from_nodes(
    service: GenerationService,
    args,
    *,
    style_ref: str | None = None,
):
    character, action, background = _read_node_inputs(args)
    return service.compose_nodes(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        style_ref=style_ref if style_ref is not None else args.style_ref,
        character_scope=args.character_scope,
        body_scope=args.body_scope,
    )


def _read_node_inputs(args):
    reader = NodeReader()
    character = reader.read(args.character) if args.character else None
    action = reader.read(args.action) if args.action else None
    background = reader.read(args.background) if args.background else None
    return character, action, background


def _load_render_style(args):
    if args.style_node:
        node = NodeReader().read(args.style_node)
        return args.style_ref or node.id, node

    style_ref = args.style_ref
    if args.config:
        config = load_config(Path(args.config))
        if args.backend == "novelai":
            style_ref = style_ref or config.defaults.style_ref
            if style_ref:
                return style_ref, NovelAIStyleRepository(config.legacy.design_root).load(style_ref)
    return style_ref, None


def _render_action(backend: str) -> str:
    return "generate" if backend == "novelai" else "render-plan"


def _write_structured_output(data: dict, path: Path, *, output_format: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    format_name = output_format
    if format_name == "auto":
        format_name = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    if format_name == "yaml":
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_generated_images(
    images,
    *,
    output_dir: Path,
    request: RenderRequest,
    default_format: str,
) -> list[GeneratedImage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid4().hex[:8]
    generated_images: list[GeneratedImage] = []
    for index, image in enumerate(images, start=1):
        suffix = Path(image.filename).suffix or f".{default_format}"
        filename = f"{batch_id}_{request.seed or 0}_{index:02d}{suffix}"
        path = output_dir / filename
        path.write_bytes(image.content)
        generated_images.append(
            GeneratedImage(
                path=path,
                filename=filename,
                meta={"source_filename": image.filename, "index": index},
            )
        )
    return generated_images


def _collect_png_info(images: list[GeneratedImage]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for image in images:
        record: dict[str, Any] = {
            "filename": image.filename,
            "path": str(image.path),
        }
        try:
            record.update(read_image_parameters(image.path))
        except Exception as exc:  # 图片可能不是 PNG，或者后端没有写入文本参数。
            record["error"] = str(exc)
        records.append(record)
    return {"images": records}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tags Machine Core CLI")
    subparsers = parser.add_subparsers(dest="command")
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument(
        "--full",
        action="store_true",
        help="Print full JSON without truncating long image/base64 fields",
    )

    compose = subparsers.add_parser("compose", parents=[output_parent], help="Build a PromptBundle")
    compose.add_argument("--prompt", required=True)
    compose.add_argument("--negative")
    compose.add_argument("--style-ref")
    compose.set_defaults(func=cmd_compose)

    compose_nodes = subparsers.add_parser(
        "compose-nodes",
        parents=[output_parent],
        help="Build a PromptBundle from structured nodes",
    )
    _add_node_compose_arguments(compose_nodes)
    compose_nodes.set_defaults(func=cmd_compose_nodes)

    agent_task_nodes = subparsers.add_parser(
        "agent-task-nodes",
        parents=[output_parent],
        help="Build an agent-readable prompt composition task",
    )
    _add_node_compose_arguments(agent_task_nodes)
    _add_agent_arguments(agent_task_nodes, result=False)
    agent_task_nodes.set_defaults(func=cmd_agent_task_nodes)

    compose_agent_nodes = subparsers.add_parser(
        "compose-agent-nodes",
        parents=[output_parent],
        help="Build a PromptBundle from an agent composition result",
    )
    _add_node_compose_arguments(compose_agent_nodes)
    _add_agent_arguments(compose_agent_nodes, result=True)
    compose_agent_nodes.set_defaults(func=cmd_compose_agent_nodes)

    render_plan = subparsers.add_parser(
        "render-plan",
        parents=[output_parent],
        help="Build a RenderRequest",
    )
    render_plan.add_argument("--prompt", required=True)
    render_plan.add_argument("--negative")
    render_plan.add_argument("--style-ref")
    render_plan.add_argument("--style-node", help="Path to a structured style node")
    render_plan.add_argument("--backend", default="novelai", choices=RENDER_BACKENDS)
    render_plan.add_argument("--seed", type=int)
    render_plan.add_argument("--width", type=int, default=1024)
    render_plan.add_argument("--height", type=int, default=1024)
    render_plan.add_argument("--model")
    render_plan.add_argument("--params-json", help="Extra renderer params as a JSON object")
    render_plan.add_argument("--config", help="Load style nodes through this config file")
    render_plan.set_defaults(func=cmd_render_plan)

    render_plan_nodes = subparsers.add_parser(
        "render-plan-nodes",
        parents=[output_parent],
        help="Build a RenderRequest from structured nodes",
    )
    _add_node_compose_arguments(render_plan_nodes)
    render_plan_nodes.add_argument("--style-node", help="Path to a structured style node")
    render_plan_nodes.add_argument("--backend", default="novelai", choices=RENDER_BACKENDS)
    render_plan_nodes.add_argument("--seed", type=int)
    render_plan_nodes.add_argument("--width", type=int, default=1024)
    render_plan_nodes.add_argument("--height", type=int, default=1024)
    render_plan_nodes.add_argument("--model")
    render_plan_nodes.add_argument("--params-json", help="Extra renderer params as a JSON object")
    render_plan_nodes.add_argument("--config", help="Load style nodes through this config file")
    render_plan_nodes.set_defaults(func=cmd_render_plan_nodes)

    generate = subparsers.add_parser(
        "generate",
        parents=[output_parent],
        help="Generate image(s) with NovelAI",
    )
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--negative")
    generate.add_argument("--style-ref")
    generate.add_argument("--seed", type=int)
    generate.add_argument("--width", type=int, default=1024)
    generate.add_argument("--height", type=int, default=1024)
    generate.add_argument("--model", default="nai-diffusion-4-5-full")
    generate.add_argument("--params-json", help="Extra renderer params as a JSON object")
    generate.add_argument("--config", required=True, help="Load runtime and NovelAI config")
    generate.add_argument("--output-dir", help="Override output directory")
    generate.set_defaults(func=cmd_generate)

    execute_render_request = subparsers.add_parser(
        "execute-render-request",
        parents=[output_parent],
        help="Execute a serialized RenderRequest with its backend client",
    )
    execute_render_request.add_argument("request", help="Path to RenderRequest JSON")
    execute_render_request.add_argument("--config", required=True, help="Load backend config")
    execute_render_request.add_argument("--output-dir", help="Override output directory")
    execute_render_request.add_argument(
        "--client-id",
        help="Optional ComfyUI client_id when queueing a prompt",
    )
    execute_render_request.set_defaults(func=cmd_execute_render_request)

    inspect_node = subparsers.add_parser(
        "inspect-node",
        parents=[output_parent],
        help="Read a node file/directory",
    )
    inspect_node.add_argument("path")
    inspect_node.set_defaults(func=cmd_inspect_node)

    inspect_style = subparsers.add_parser(
        "inspect-style",
        parents=[output_parent],
        help="Read a NovelAI style node",
    )
    inspect_style.add_argument("--config", required=True)
    inspect_style.add_argument("--style-ref", required=True)
    inspect_style.set_defaults(func=cmd_inspect_style)

    config = subparsers.add_parser("config", parents=[output_parent], help="Read an app config file")
    config.add_argument("path")
    config.set_defaults(func=cmd_config)

    inspect_image_params = subparsers.add_parser(
        "inspect-image-params",
        parents=[output_parent],
        help="Read PNG generation parameters without legacy runtime imports",
    )
    inspect_image_params.add_argument("path")
    inspect_image_params.add_argument(
        "--normalized",
        action="store_true",
        help="Print normalized NovelAI parameters for comparison",
    )
    inspect_image_params.set_defaults(func=cmd_inspect_image_params)

    compare_render_params = subparsers.add_parser(
        "compare-render-params",
        parents=[output_parent],
        help="Compare NovelAI request/render/png parameters after normalization",
    )
    compare_render_params.add_argument("left")
    compare_render_params.add_argument("right")
    compare_render_params.add_argument(
        "--show-normalized",
        action="store_true",
        help="Include both normalized parameter trees in the output",
    )
    compare_render_params.set_defaults(func=cmd_compare_render_params)

    create_acceptance_record = subparsers.add_parser(
        "create-acceptance-record",
        parents=[output_parent],
        help="Create an archived legacy-vs-core acceptance record",
    )
    create_acceptance_record.add_argument("--case-id", required=True)
    create_acceptance_record.add_argument("--legacy-source", required=True)
    create_acceptance_record.add_argument("--core-source", required=True)
    create_acceptance_record.add_argument("--legacy-image")
    create_acceptance_record.add_argument("--core-image")
    create_acceptance_record.add_argument("--prompt-bundle")
    create_acceptance_record.add_argument(
        "--whitelist",
        action="append",
        help="Approved diff path with optional reason, for example $.parameters.sampler=alias",
    )
    create_acceptance_record.add_argument(
        "--note",
        action="append",
        help="Human note stored in the acceptance record; can be repeated",
    )
    create_acceptance_record.add_argument("--output", help="Write the record to JSON/YAML")
    create_acceptance_record.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    create_acceptance_record.set_defaults(func=cmd_create_acceptance_record)

    verify_acceptance = subparsers.add_parser(
        "verify-acceptance-record",
        parents=[output_parent],
        help="Recompute an archived acceptance record and fail on unapproved diffs",
    )
    verify_acceptance.add_argument("record")
    verify_acceptance.set_defaults(func=cmd_verify_acceptance_record)

    verify_acceptance_suite_parser = subparsers.add_parser(
        "verify-acceptance-suite",
        parents=[output_parent],
        help="Verify a directory or manifest of acceptance records",
    )
    verify_acceptance_suite_parser.add_argument(
        "path",
        help="Acceptance record, suite manifest, or directory containing records",
    )
    verify_acceptance_suite_parser.add_argument(
        "--required-case",
        action="append",
        help="Required case id or prefix; can be repeated",
    )
    verify_acceptance_suite_parser.add_argument(
        "--require-minimum-set",
        action="store_true",
        help="Require the documented minimum legacy regression cases",
    )
    verify_acceptance_suite_parser.set_defaults(func=cmd_verify_acceptance_suite)

    migrate_style_tags = subparsers.add_parser(
        "migrate-style-tags",
        parents=[output_parent],
        help="Convert a legacy style tags.txt into a structured style node",
    )
    migrate_style_tags.add_argument("source", help="Legacy style directory or tags.txt path")
    migrate_style_tags.add_argument("--id", help="Override generated style node id")
    migrate_style_tags.add_argument("--name", help="Override generated style node name")
    migrate_style_tags.add_argument("--output", help="Write node.yaml to this path")
    migrate_style_tags.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    migrate_style_tags.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output if it already exists",
    )
    migrate_style_tags.set_defaults(func=cmd_migrate_style_tags)

    return parser


def _add_node_compose_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--character", help="Path to a character node")
    parser.add_argument("--action", help="Path to an action node")
    parser.add_argument("--background", help="Path to a background node")
    parser.add_argument("--extra-prompt", help="Additional positive prompt text")
    parser.add_argument("--negative")
    parser.add_argument("--style-ref")
    parser.add_argument("--character-scope", help="Override character_scope for node composition")
    parser.add_argument("--body-scope", help="Compatibility alias for --character-scope")


def _add_agent_arguments(parser: argparse.ArgumentParser, *, result: bool) -> None:
    parser.add_argument(
        "--instruction",
        action="append",
        help="Instruction passed through to the external agent; can be repeated",
    )
    if result:
        parser.add_argument("--agent-result", help="Path to agent result JSON")
        parser.add_argument("--cache-dir", help="PromptBundle cache directory")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)
