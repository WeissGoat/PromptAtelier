from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from tags_machine_core.clients import NovelAIClient
from tags_machine_core.composers import load_agent_result
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.config import load_config
from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.json_tools import sanitize_json_for_display
from tags_machine_core.nodes import NodeReader
from tags_machine_core.renderers import NovelAIStyleRepository
from tags_machine_core.services import GenerationService
from tags_machine_core.verification import (
    compare_render_parameters,
    load_render_parameter_source,
    normalize_render_parameters,
    read_image_parameters,
)


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
    if args.backend != "novelai":
        raise ValueError(f"Unsupported backend in first scaffold: {args.backend}")
    style = None
    style_ref = args.style_ref
    if args.config:
        config = load_config(Path(args.config))
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
    print_json(request, full=args.full)
    return 0


def cmd_render_plan_nodes(args) -> int:
    service = GenerationService()
    if args.backend != "novelai":
        raise ValueError(f"Unsupported backend in first scaffold: {args.backend}")
    style = None
    style_ref = args.style_ref
    if args.config:
        config = load_config(Path(args.config))
        style_ref = args.style_ref or config.defaults.style_ref
        if style_ref:
            style = NovelAIStyleRepository(config.legacy.design_root).load(style_ref)
    bundle = _build_bundle_from_nodes(service, args, style_ref=style_ref)
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        style=style,
        width=args.width,
        height=args.height,
        model=args.model,
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
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid4().hex[:8]
    generated_images: list[GeneratedImage] = []
    for index, image in enumerate(images, start=1):
        suffix = Path(image.filename).suffix or f".{config.defaults.image_format}"
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
    result = GenerationResult(
        backend="novelai",
        images=generated_images,
        request_body=client.build_payload(request),
        png_info={},
        cache_hit=False,
    )
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


def _load_json_arg(value: str | None) -> dict:
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("--params-json must be a JSON object")
    return data


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
    render_plan.add_argument("--backend", default="novelai", choices=["novelai"])
    render_plan.add_argument("--seed", type=int)
    render_plan.add_argument("--width", type=int, default=1024)
    render_plan.add_argument("--height", type=int, default=1024)
    render_plan.add_argument("--model", default="nai-diffusion-4-5-full")
    render_plan.add_argument("--params-json", help="Extra renderer params as a JSON object")
    render_plan.add_argument("--config", help="Load style nodes through this config file")
    render_plan.set_defaults(func=cmd_render_plan)

    render_plan_nodes = subparsers.add_parser(
        "render-plan-nodes",
        parents=[output_parent],
        help="Build a RenderRequest from structured nodes",
    )
    _add_node_compose_arguments(render_plan_nodes)
    render_plan_nodes.add_argument("--backend", default="novelai", choices=["novelai"])
    render_plan_nodes.add_argument("--seed", type=int)
    render_plan_nodes.add_argument("--width", type=int, default=1024)
    render_plan_nodes.add_argument("--height", type=int, default=1024)
    render_plan_nodes.add_argument("--model", default="nai-diffusion-4-5-full")
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
