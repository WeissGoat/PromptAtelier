from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.backends import (
    RENDER_BACKENDS,
    backend_support_report,
    ensure_backend_can_execute,
)
from tags_machine_core.composers import AgentCompositionRequired, load_agent_result
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.config import load_config
from tags_machine_core.contracts import GenerationResult, RenderRequest
from tags_machine_core.execution import execute_render_request as _execute_render_request
from tags_machine_core.json_tools import sanitize_json_for_display
from tags_machine_core.logging_config import configure_logging, get_logger
from tags_machine_core.nodes import (
    NodeInput,
    NodeReader,
    NovelAIArtistRepository,
    ResolvedNode,
    ResolvedNodeSet,
    apply_legacy_tags_migration,
    audit_legacy_tags,
    migrate_legacy_action_tags,
    migrate_legacy_artist_tags,
    migrate_legacy_background_tags,
    migrate_legacy_character_tags,
    plan_legacy_tags_migration,
    validate_node_tree,
)
from tags_machine_core.services import GenerationJsonApi, GenerationService
from tags_machine_core.policies import PromptPolicyConfig
from tags_machine_core.verification import (
    archive_acceptance_case,
    build_image_comparison_report,
    build_acceptance_record,
    build_prompt_policy_acceptance_report,
    compare_render_parameters,
    load_render_parameter_source,
    normalize_render_parameters,
    parse_intentional_difference_args,
    parse_whitelist_args,
    read_image_parameters,
    run_core_verification,
    verify_acceptance_record,
    verify_acceptance_suite,
)
from tags_machine_core.batch import (
    BatchPlanner,
    BatchRunner,
    latest_manifest_entries,
    load_batch_spec,
    write_initial_manifest,
)


logger = get_logger(__name__)


def _agent_instructions(args) -> list[str]:
    return (getattr(args, "agent_instruction", None) or []) + (
        getattr(args, "instruction", None) or []
    )


def print_json(value, *, full: bool = False) -> None:
    data = sanitize_json_for_display(value, full=full)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_command_config(path: str | Path, args=None):
    config = load_config(Path(path))
    if args is None or not getattr(args, "log_level", None):
        configure_logging(config.logging.level)
    logger.trace("loaded config path=%s logging.level=%s", path, config.logging.level)
    return config


def cmd_compose(args) -> int:
    service = GenerationService()
    bundle = _build_bundle(service, args)
    print_json(bundle, full=args.full)
    return 0


def cmd_compose_nodes(args) -> int:
    service = GenerationService()
    bundle = _build_bundle_from_nodes(service, args)
    print_json(bundle, full=args.full)
    return 0


def cmd_agent_task_nodes(args) -> int:
    service = GenerationService()
    resolved_nodes = _read_resolved_nodes(args)
    task = service.build_agent_composition_task_resolved_nodes(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
        instructions=_agent_instructions(args),
        agent_model=args.agent_model,
    )
    print_json(task, full=args.full)
    return 0


def cmd_compose_agent_nodes(args) -> int:
    service = GenerationService()
    resolved_nodes = _read_resolved_nodes(args)
    cache = PromptCache(args.cache_dir) if args.cache_dir else None
    result = load_agent_result(args.agent_result) if args.agent_result else None
    bundle = service.compose_resolved_nodes_with_agent(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
        instructions=_agent_instructions(args),
        agent_model=args.agent_model,
        result=result,
        cache=cache,
    )
    print_json(bundle, full=args.full)
    return 0


def cmd_render_plan(args) -> int:
    service = GenerationService()
    artist_ref, artist = _load_render_artist(args)
    bundle = _build_bundle(service, args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
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
    artist_ref, artist = _load_render_artist(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_resolved_nodes(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
    )
    request = service.build_render_request(
        bundle,
        backend=args.backend,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
        width=args.width,
        height=args.height,
        model=args.model,
        action=_render_action(args.backend),
        params=_load_json_arg(args.params_json),
    )
    print_json(request, full=args.full)
    return 0


def cmd_run_prompt(args) -> int:
    service = GenerationService()
    logger.info(
        "run-prompt start composer=%s dry_run=%s artist=%s model=%s nt=%s",
        getattr(args, "composer", "full"),
        args.dry_run,
        getattr(args, "artist", None) or getattr(args, "artist_node", None),
        args.model,
        args.nt,
    )
    try:
        bundle, request = _build_novelai_prompt_artifacts(service, args)
    except AgentCompositionRequired as exc:
        result = {
            "schema": "tags-machine-core.run-prompt-result/v1",
            "status": "requires_agent",
            "dry_run": True,
            "agent_task": exc.task,
        }
        print_json(result, full=args.full)
        return 0
    result: dict[str, Any] = {
        "schema": "tags-machine-core.run-prompt-result/v1",
        "status": "ready",
        "dry_run": args.dry_run,
        "prompt_bundle": bundle,
        "render_request": request,
    }
    if not args.dry_run:
        if not args.config:
            raise ValueError("run-prompt without --dry-run requires --config")
        config = _load_command_config(args.config, args)
        result["generation_result"] = _execute_render_request(
            config,
            request,
            output_dir=args.output_dir,
            image_format=args.format,
            allow_experimental_backend=False,
        )
        images = result["generation_result"].images
        logger.info(
            "run-prompt generation complete image_count=%s paths=%s",
            len(images),
            [str(image.path) for image in images],
        )
    print_json(result, full=args.full)
    return 0


def cmd_run_action(args) -> int:
    service = GenerationService()
    logger.info(
        "run-action start dry_run=%s artist=%s model=%s nt=%s",
        args.dry_run,
        getattr(args, "artist", None) or getattr(args, "artist_node", None),
        args.model,
        args.nt,
    )
    bundle, request = _build_novelai_action_artifacts(service, args)
    result: dict[str, Any] = {
        "schema": "tags-machine-core.run-action-result/v1",
        "status": "ready",
        "dry_run": args.dry_run,
        "prompt_bundle": bundle,
        "render_request": request,
    }
    if not args.dry_run:
        if not args.config:
            raise ValueError("run-action without --dry-run requires --config")
        config = _load_command_config(args.config, args)
        result["generation_result"] = _execute_render_request(
            config,
            request,
            output_dir=args.output_dir,
            image_format=args.format,
            allow_experimental_backend=False,
        )
    print_json(result, full=args.full)
    return 0


def cmd_generate(args) -> int:
    config = _load_command_config(args.config, args)
    service = GenerationService()
    artist_ref, artist = _load_render_artist(args)
    bundle = _build_bundle(service, args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
        width=args.width,
        height=args.height,
        model=args.model,
        params=_load_json_arg(args.params_json),
    )
    result = _execute_render_request(
        config,
        request,
        output_dir=args.output_dir,
        image_format=config.defaults.image_format,
        allow_experimental_backend=False,
    )
    print_json(result, full=args.full)
    return 0


def cmd_execute_render_request(args) -> int:
    config = _load_command_config(args.config, args)
    request = _load_render_request(args.request)
    result = _execute_render_request(
        config,
        request,
        output_dir=args.output_dir,
        image_format=config.defaults.image_format,
        allow_experimental_backend=args.allow_experimental_backend,
        client_id=args.client_id,
        comfyui_no_wait=args.comfyui_no_wait,
        comfyui_poll_interval=args.comfyui_poll_interval,
        comfyui_max_wait_seconds=args.comfyui_max_wait_seconds,
    )
    print_json(result, full=args.full)
    return 0


def cmd_inspect_artist(args) -> int:
    config = _load_command_config(args.config, args)
    artist = NovelAIArtistRepository(config.legacy.design_root).load_node(args.artist)
    print_json(artist, full=args.full)
    return 0


def cmd_inspect_node(args) -> int:
    node = NodeReader().read(args.path)
    print_json(node, full=args.full)
    return 0


def cmd_validate_node_tree(args) -> int:
    result = validate_node_tree(args.path)
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0 if result["valid"] else 2


def cmd_config(args) -> int:
    config = _load_command_config(args.path, args)
    print_json(config, full=args.full)
    return 0


def cmd_backend_support(args) -> int:
    print_json(backend_support_report(), full=args.full)
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


def cmd_compare_image_result(args) -> int:
    report = build_image_comparison_report(
        args.legacy_image,
        args.core_generation_result,
        core_image=args.core_image,
        visual_result=args.visual_result,
        visual_notes=args.visual_note or [],
    )
    if args.output:
        _write_structured_output(report, Path(args.output), output_format=args.format)
    print_json(report, full=args.full)
    return 0 if report["match"] else 2


def cmd_verify_prompt_policy_acceptance(args) -> int:
    report = build_prompt_policy_acceptance_report(
        legacy_image=args.legacy_image,
        core_run_result=args.core_run_result,
        core_generation_result=args.core_generation_result,
        prompt_bundle=args.prompt_bundle,
        core_image=args.core_image,
        visual_result=args.visual_result,
        visual_notes=args.visual_note or [],
        whitelist=parse_whitelist_args(args.whitelist),
        intentional_differences=parse_intentional_difference_args(args.intentional_difference),
        expected_profile=args.expected_profile,
        required_rules=args.require_policy_rule or [],
        expect_tokens=args.expect_token or [],
        reject_tokens=args.reject_token or [],
    )
    if args.output:
        _write_structured_output(report, Path(args.output), output_format=args.format)
    print_json(report, full=args.full)
    return 0 if report["result"] == "pass" else 2


def cmd_create_acceptance_record(args) -> int:
    record = build_acceptance_record(
        case_id=args.case_id,
        legacy_source=args.legacy_source,
        core_source=args.core_source,
        legacy_image=args.legacy_image,
        core_image=args.core_image,
        prompt_bundle=args.prompt_bundle,
        generation_result=args.generation_result,
        whitelist=parse_whitelist_args(args.whitelist),
        intentional_differences=parse_intentional_difference_args(args.intentional_difference),
        notes=args.note or [],
        oracle_kind=args.oracle_kind,
    )
    if args.output:
        _write_structured_output(record, Path(args.output), output_format=args.format)
    print_json(record, full=args.full)
    return 0 if record["result"] == "pass" else 2


def cmd_archive_acceptance_case(args) -> int:
    archive = archive_acceptance_case(
        case_id=args.case_id,
        output_dir=args.output_dir,
        legacy_source=args.legacy_source,
        core_source=args.core_source,
        legacy_image=args.legacy_image,
        core_image=args.core_image,
        prompt_bundle=args.prompt_bundle,
        generation_result=args.generation_result,
        whitelist=parse_whitelist_args(args.whitelist),
        intentional_differences=parse_intentional_difference_args(args.intentional_difference),
        notes=args.note or [],
        manifest=args.manifest,
        required_cases=args.required_case or [],
        update_manifest=not args.no_manifest,
        overwrite=args.overwrite,
        record_format=args.format,
        oracle_kind=args.oracle_kind,
    )
    print_json(archive, full=args.full)
    return 0 if archive["result"] == "pass" else 2


def cmd_archive_novelai_acceptance_nodes(args) -> int:
    service = GenerationService()
    artist_ref, artist = _load_novelai_artist_for_nodes(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_resolved_nodes(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
    )
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        artist=artist,
        resolved_nodes=resolved_nodes,
        width=args.width,
        height=args.height,
        model=args.model,
        params=_load_json_arg(args.params_json),
    )

    case_dir = _acceptance_case_dir(args.output_dir, args.case_id)
    core_dir = case_dir / "core"
    prompt_bundle_path = core_dir / "prompt_bundle.json"
    render_request_path = core_dir / "render_request.json"
    _write_generated_core_artifact(
        bundle.model_dump(by_alias=True, mode="json"),
        prompt_bundle_path,
        overwrite=args.overwrite,
    )
    _write_generated_core_artifact(
        request.model_dump(by_alias=True, mode="json"),
        render_request_path,
        overwrite=args.overwrite,
    )

    archive = archive_acceptance_case(
        case_id=args.case_id,
        output_dir=args.output_dir,
        legacy_source=args.legacy_source,
        core_source=render_request_path,
        legacy_image=args.legacy_image,
        core_image=args.core_image,
        prompt_bundle=prompt_bundle_path,
        generation_result=args.generation_result,
        whitelist=parse_whitelist_args(args.whitelist),
        intentional_differences=parse_intentional_difference_args(args.intentional_difference),
        notes=args.note or [],
        manifest=args.manifest,
        required_cases=args.required_case or [],
        update_manifest=not args.no_manifest,
        overwrite=args.overwrite,
        record_format=args.format,
        oracle_kind=args.oracle_kind,
    )
    print_json(archive, full=args.full)
    return 0 if archive["result"] == "pass" else 2


def cmd_archive_novelai_acceptance_prompt(args) -> int:
    service = GenerationService()
    bundle, request = _build_novelai_prompt_artifacts(service, args)

    case_dir = _acceptance_case_dir(args.output_dir, args.case_id)
    core_dir = case_dir / "core"
    prompt_bundle_path = core_dir / "prompt_bundle.json"
    render_request_path = core_dir / "render_request.json"
    _write_generated_core_artifact(
        bundle.model_dump(by_alias=True, mode="json"),
        prompt_bundle_path,
        overwrite=args.overwrite,
    )
    _write_generated_core_artifact(
        request.model_dump(by_alias=True, mode="json"),
        render_request_path,
        overwrite=args.overwrite,
    )

    archive = archive_acceptance_case(
        case_id=args.case_id,
        output_dir=args.output_dir,
        legacy_source=args.legacy_source,
        core_source=render_request_path,
        legacy_image=args.legacy_image,
        core_image=args.core_image,
        prompt_bundle=prompt_bundle_path,
        generation_result=args.generation_result,
        whitelist=parse_whitelist_args(args.whitelist),
        intentional_differences=parse_intentional_difference_args(args.intentional_difference),
        notes=args.note or [],
        manifest=args.manifest,
        required_cases=args.required_case or [],
        update_manifest=not args.no_manifest,
        overwrite=args.overwrite,
        record_format=args.format,
        oracle_kind=args.oracle_kind,
    )
    print_json(archive, full=args.full)
    return 0 if archive["result"] == "pass" else 2


def cmd_verify_acceptance_record(args) -> int:
    result = verify_acceptance_record(args.record)
    print_json(result, full=args.full)
    return 0 if result["match"] else 2


def cmd_verify_acceptance_suite(args) -> int:
    result = verify_acceptance_suite(
        args.path,
        required_cases=args.required_case,
        require_minimum_set=args.require_minimum_set,
        require_legacy_oracle=args.require_legacy_oracle,
        require_legacy_evidence=args.require_legacy_evidence,
    )
    print_json(result, full=args.full)
    return 0 if result["match"] else 2


def cmd_verify_core(args) -> int:
    result = run_core_verification(cwd=args.cwd, dry_run=args.dry_run)
    print_json(result, full=args.full)
    return 0 if result["match"] else 2


def cmd_migrate_artist_tags(args) -> int:
    node = migrate_legacy_artist_tags(
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


def cmd_migrate_action_tags(args) -> int:
    node = migrate_legacy_action_tags(
        args.source,
        node_id=args.id,
        name=args.name,
        character_scope=args.character_scope,
    )
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(f"Output already exists, pass --overwrite to replace: {output_path}")
        _write_structured_output(node, output_path, output_format=args.format)
    print_json(node, full=args.full)
    return 0


def cmd_migrate_character_tags(args) -> int:
    node = migrate_legacy_character_tags(
        args.source,
        node_id=args.id,
        name=args.name,
        character_id=args.character_id,
        variant=args.variant,
    )
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(f"Output already exists, pass --overwrite to replace: {output_path}")
        _write_structured_output(node, output_path, output_format=args.format)
    print_json(node, full=args.full)
    return 0


def cmd_migrate_background_tags(args) -> int:
    node = migrate_legacy_background_tags(
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


def cmd_audit_legacy_tags(args) -> int:
    report = audit_legacy_tags(args.source, kind=args.kind)
    if args.output:
        _write_structured_output(report, Path(args.output), output_format=args.format)
    print_json(report, full=args.full)
    return 0


def cmd_plan_legacy_tags_migration(args) -> int:
    plan = plan_legacy_tags_migration(
        args.source,
        kind=args.kind,
        output_root=args.output_root,
    )
    if args.output:
        _write_structured_output(plan, Path(args.output), output_format=args.format)
    print_json(plan, full=args.full)
    return 0


def cmd_apply_legacy_tags_migration(args) -> int:
    result = apply_legacy_tags_migration(
        args.source,
        kind=args.kind,
        output_root=args.output_root,
    )
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_compose(args) -> int:
    result = GenerationJsonApi().compose(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_agent_task(args) -> int:
    result = GenerationJsonApi().agent_task(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_compose_agent(args) -> int:
    result = GenerationJsonApi().compose_agent(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_resolve_agent(args) -> int:
    result = GenerationJsonApi().resolve_agent(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_render_plan(args) -> int:
    result = GenerationJsonApi().render_plan(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_compose_render_plan(args) -> int:
    result = GenerationJsonApi().compose_render_plan(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_resolve_compose_render_plan(args) -> int:
    result = GenerationJsonApi().resolve_compose_render_plan(
        _load_json_mapping_file(args.request)
    )
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_resolve_batch_item(args) -> int:
    result = GenerationJsonApi().resolve_batch_item(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_backend_support(args) -> int:
    result = GenerationJsonApi().backend_support(_load_json_mapping_file(args.request))
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_api_generate(args) -> int:
    config = _load_command_config(args.config, args)

    def executor(request: RenderRequest, request_data: dict[str, Any]) -> GenerationResult:
        ensure_backend_can_execute(
            request.backend,
            allow_experimental_backend=False,
            entrypoint="api-generate",
            experimental_flag=None,
        )
        return _execute_render_request(
            config,
            request,
            output_dir=args.output_dir or request_data.get("output_dir"),
            image_format=config.defaults.image_format,
            allow_experimental_backend=False,
        )

    result = GenerationJsonApi(generation_executor=executor).generate(
        _load_json_mapping_file(args.request)
    )
    if args.output:
        _write_structured_output(result, Path(args.output), output_format=args.format)
    print_json(result, full=args.full)
    return 0


def cmd_plan_batch(args) -> int:
    spec_path = Path(args.batch_spec)
    spec = load_batch_spec(spec_path)
    run_dir = _batch_run_dir(spec, output_root=args.output_root)
    planner = BatchPlanner(base_dir=spec_path.parent)
    tasks = planner.plan(spec, run_dir=run_dir)
    manifest_path = write_initial_manifest(run_dir, tasks)
    _write_batch_source(run_dir, spec_path)
    _copy_batch_spec(run_dir, spec_path)
    print_json(
        {
            "schema": "tags-machine-core.plan-batch-result/v1",
            "batch": spec.name,
            "task_count": len(tasks),
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
        },
        full=args.full,
    )
    return 0


def cmd_run_batch(args) -> int:
    spec_path = Path(args.batch_spec)
    spec = load_batch_spec(spec_path)
    run_dir = _batch_run_dir(spec, output_root=args.output_root)
    planner = BatchPlanner(base_dir=spec_path.parent)
    tasks = planner.plan(spec, run_dir=run_dir)
    config_path = _batch_config_path(spec, spec_path=spec_path, override=args.config)
    config = _load_command_config(config_path, args)
    _write_batch_source(run_dir, spec_path)
    _copy_batch_spec(run_dir, spec_path)
    result = BatchRunner().run_tasks(
        run_dir=run_dir,
        tasks=tasks,
        config=config,
        run_config=spec.run,
        archive_config=spec.archive,
        report_config=spec.report,
        limit=args.limit,
    )
    print_json(
        {
            "schema": "tags-machine-core.run-batch-result/v1",
            "batch": spec.name,
            **result,
        },
        full=args.full,
    )
    return 0


def cmd_resume_batch(args) -> int:
    run_dir = Path(args.run_dir)
    spec_path = Path(args.batch_spec) if args.batch_spec else _batch_source_path(run_dir)
    spec = load_batch_spec(spec_path)
    planner = BatchPlanner(base_dir=spec_path.parent)
    tasks = planner.plan(spec, run_dir=run_dir)
    config_path = _batch_config_path(spec, spec_path=spec_path, override=args.config)
    config = _load_command_config(config_path, args)
    result = BatchRunner().run_tasks(
        run_dir=run_dir,
        tasks=tasks,
        config=config,
        run_config=spec.run,
        archive_config=spec.archive,
        report_config=spec.report,
        limit=args.limit,
    )
    print_json(
        {
            "schema": "tags-machine-core.resume-batch-result/v1",
            "batch": spec.name,
            **result,
        },
        full=args.full,
    )
    return 0


def cmd_inspect_batch(args) -> int:
    run_dir = Path(args.run_dir)
    entries = latest_manifest_entries(run_dir)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    print_json(
        {
            "schema": "tags-machine-core.inspect-batch-result/v1",
            "run_dir": str(run_dir),
            "counts": counts,
            "tasks": entries,
        },
        full=args.full,
    )
    return 0


def _load_json_arg(value: str | None) -> dict:
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("--params-json must be a JSON object")
    return data


def _load_json_mapping_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _load_render_request(path: str | Path) -> RenderRequest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected RenderRequest JSON object: {path}")
    return RenderRequest.model_validate(data)


def _batch_run_dir(spec, *, output_root: str | None) -> Path:
    root = Path(output_root or spec.output_root)
    return root / spec.name


def _batch_config_path(spec, *, spec_path: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    raw = Path(spec.config)
    if raw.is_absolute():
        return raw
    if raw.exists():
        return raw
    return spec_path.parent / raw


def _write_batch_source(run_dir: str | Path, spec_path: Path) -> Path:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "batch_source.json"
    path.write_text(
        json.dumps(
            {
                "schema": "tags-machine-core.batch-source/v1",
                "spec_path": str(spec_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _copy_batch_spec(run_dir: str | Path, spec_path: Path) -> Path:
    target = Path(run_dir) / "batch.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(spec_path, target)
    return target


def _batch_source_path(run_dir: str | Path) -> Path:
    source_path = Path(run_dir) / "batch_source.json"
    if source_path.exists():
        data = json.loads(source_path.read_text(encoding="utf-8"))
        value = data.get("spec_path")
        if value:
            return Path(value)
    fallback = Path(run_dir) / "batch.yaml"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Cannot resume batch without batch_source.json or batch.yaml under {run_dir}"
    )


def _read_prompt_value(args) -> str:
    if getattr(args, "prompt_file", None):
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return str(args.prompt or "").strip()


def _build_bundle(service: GenerationService, args):
    return service.compose_full_prompt(
        prompt=args.prompt,
        negative=args.negative or "",
        prompt_policy=_prompt_policy_from_args(args, target="full_prompt"),
    )


def _build_bundle_from_nodes(
    service: GenerationService,
    args,
):
    resolved_nodes = _read_resolved_nodes(args)
    if resolved_nodes:
        return service.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=args.extra_prompt or "",
            negative=args.negative or "",
            character_scope=args.character_scope,
            body_scope=args.body_scope,
            prompt_policy=_prompt_policy_from_args(args, target="script"),
        )
    character, action, background = _read_node_inputs(args)
    return service.compose_nodes(
        character=character,
        action=action,
        background=background,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope,
        body_scope=args.body_scope,
        prompt_policy=_prompt_policy_from_args(args, target="script"),
    )


def _build_novelai_prompt_artifacts(service: GenerationService, args):
    if getattr(args, "composer", "full") == "agent":
        return _build_novelai_agent_prompt_artifacts(service, args)
    prompt = _read_prompt_value(args)
    if not prompt:
        raise ValueError("run-prompt requires --prompt or --prompt-file unless --composer agent is used")
    artist_ref, artist = _load_novelai_artist_for_prompt(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_full_prompt(
        prompt=prompt,
        negative=args.negative or "",
        prompt_policy=_prompt_policy_from_args(args, target="full_prompt"),
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        artist=artist,
        width=args.width,
        height=args.height,
        model=args.model,
        params=params,
        resolved_nodes=resolved_nodes,
    )
    return bundle, request


def _build_novelai_agent_prompt_artifacts(service: GenerationService, args):
    artist_ref, artist = _load_novelai_artist_for_prompt(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    cache = PromptCache(args.cache_dir) if args.cache_dir else None
    result = load_agent_result(args.agent_result) if args.agent_result else None
    prompt = _read_prompt_value(args)
    task_negative = args.negative or ""
    if prompt and result is None:
        result = {
            "positive": prompt,
            "negative": args.negative or "",
            "character_scope": args.character_scope or args.body_scope,
        }
        task_negative = ""
    bundle = service.compose_resolved_nodes_with_agent(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=task_negative,
        character_scope=args.character_scope or args.body_scope,
        instructions=_agent_instructions(args),
        agent_model=args.agent_model,
        result=result,
        cache=cache,
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        artist=artist,
        width=args.width,
        height=args.height,
        model=args.model,
        params=params,
        resolved_nodes=resolved_nodes,
    )
    return bundle, request


def _build_novelai_action_artifacts(service: GenerationService, args):
    artist_ref, artist = _load_novelai_artist_for_nodes(args)
    resolved_nodes = _read_resolved_nodes(args, artist_ref=artist_ref, artist=artist)
    bundle = service.compose_resolved_nodes(
        resolved_nodes,
        extra_prompt=args.extra_prompt or "",
        negative=args.negative or "",
        character_scope=args.character_scope or args.body_scope,
        prompt_policy=_prompt_policy_from_args(args, target="script"),
    )
    params = _load_json_arg(args.params_json)
    params["n_samples"] = args.nt
    request = service.build_novelai_request(
        bundle,
        seed=args.seed,
        artist=artist,
        width=args.width,
        height=args.height,
        model=args.model,
        params=params,
        resolved_nodes=resolved_nodes,
    )
    return bundle, request


def _prompt_policy_from_args(args, *, target: str):
    profile = getattr(args, "prompt_policy_profile", None)
    enabled_rules = getattr(args, "prompt_policy_rule", None) or []
    disabled_rules = getattr(args, "no_prompt_policy_rule", None) or []
    if not profile and not enabled_rules and not disabled_rules:
        config_path = getattr(args, "config", None)
        if config_path:
            return _load_command_config(config_path, args).prompt_policy
        return None
    apply_to = {
        "script": False,
        "agent": False,
        "full_prompt": False,
    }
    apply_to[target] = True
    return PromptPolicyConfig(
        enabled=True,
        profile=profile or "balanced",
        apply_to=apply_to,
        enabled_rules=enabled_rules,
        disabled_rules=disabled_rules,
        normalization={
            "output_style": getattr(args, "prompt_policy_output_style", "underscore"),
        },
    )


def _read_node_inputs(args):
    reader = NodeReader()
    character = reader.read(args.character) if args.character else None
    action = reader.read(args.action) if args.action else None
    background = reader.read(args.background) if args.background else None
    return character, action, background


def _read_resolved_nodes(
    args,
    *,
    artist_ref: str | None = None,
    artist=None,
) -> ResolvedNodeSet:
    reader = NodeReader()
    items: list[tuple[str, str, object]] = []
    if artist is not None and artist_ref:
        items.append(("artist", artist_ref, artist))
    elif getattr(args, "artist_node", None):
        node = reader.read(args.artist_node)
        items.append(("artist", node.id, node))
    for role, attr in (
        ("character", "character"),
        ("action", "action"),
        ("background", "background"),
    ):
        value = getattr(args, attr, None)
        if value:
            items.append((role, str(value), reader.read(value)))
    for value in getattr(args, "node", None) or []:
        node_input = NodeInput.parse(value)
        items.append((node_input.role, node_input.ref, reader.read(node_input.ref)))

    role_counts: dict[str, int] = {}
    resolved: list[ResolvedNode] = []
    for role, ref, node in items:
        index = role_counts.get(role, 0)
        role_counts[role] = index + 1
        resolved.append(ResolvedNode(role=role, ref=ref, index=index, node=node))
    return ResolvedNodeSet(resolved)


def _load_render_artist(args):
    if getattr(args, "artist_node", None):
        node = NodeReader().read(args.artist_node)
        return node.id, node
    artist_ref = getattr(args, "artist", None)
    if artist_ref and getattr(args, "config", None):
        config = _load_command_config(args.config, args)
        return artist_ref, NovelAIArtistRepository(config.legacy.design_root).load_node(artist_ref)
    return artist_ref, None


def _load_novelai_artist_for_nodes(args):
    return _load_render_artist(args)


def _load_novelai_artist_for_prompt(args):
    return _load_render_artist(args)


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


def _write_generated_core_artifact(data: dict, path: Path, *, overwrite: bool) -> None:
    # Write core acceptance artifacts without replacing existing manual archives.
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists, pass --overwrite to replace: {path}")
    _write_structured_output(data, path, output_format="json")


def _acceptance_case_dir(output_dir: str | Path, case_id: str) -> Path:
    value = str(case_id).strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"case_id must be a plain directory name: {case_id!r}")
    return Path(output_dir) / value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tags Machine Core CLI")
    subparsers = parser.add_subparsers(dest="command")
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument(
        "--full",
        action="store_true",
        help="Print full JSON without truncating long image/base64 fields",
    )
    output_parent.add_argument(
        "--log-level",
        choices=("trace", "info", "warning", "error"),
        help="Write diagnostic logs to stderr; defaults to TAGS_MACHINE_CORE_LOG_LEVEL or error",
    )

    compose = subparsers.add_parser("compose", parents=[output_parent], help="Build a PromptBundle")
    compose.add_argument("--prompt", required=True)
    compose.add_argument("--negative")
    _add_prompt_policy_arguments(compose)
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
    render_plan.add_argument("--artist")
    render_plan.add_argument("--artist-node", help="Path to a structured artist node")
    render_plan.add_argument("--backend", default="novelai", choices=RENDER_BACKENDS)
    render_plan.add_argument("--seed", type=int)
    render_plan.add_argument("--width", type=int, default=1024)
    render_plan.add_argument("--height", type=int, default=1024)
    render_plan.add_argument("--model")
    render_plan.add_argument("--params-json", help="Extra renderer params as a JSON object")
    render_plan.add_argument("--config", help="Load artist nodes through this config file")
    render_plan.set_defaults(func=cmd_render_plan)

    render_plan_nodes = subparsers.add_parser(
        "render-plan-nodes",
        parents=[output_parent],
        help="Build a RenderRequest from structured nodes",
    )
    _add_node_compose_arguments(render_plan_nodes)
    render_plan_nodes.add_argument("--artist")
    render_plan_nodes.add_argument("--artist-node", help="Path to a structured artist node")
    render_plan_nodes.add_argument("--backend", default="novelai", choices=RENDER_BACKENDS)
    render_plan_nodes.add_argument("--seed", type=int)
    render_plan_nodes.add_argument("--width", type=int, default=1024)
    render_plan_nodes.add_argument("--height", type=int, default=1024)
    render_plan_nodes.add_argument("--model")
    render_plan_nodes.add_argument("--params-json", help="Extra renderer params as a JSON object")
    render_plan_nodes.add_argument("--config", help="Load artist nodes through this config file")
    render_plan_nodes.set_defaults(func=cmd_render_plan_nodes)

    run_prompt = subparsers.add_parser(
        "run-prompt",
        parents=[output_parent],
        help="Run or plan a full character+action prompt with a NovelAI artist node",
    )
    _add_prompt_run_arguments(
        run_prompt,
        output_options=True,
        prompt_required=False,
        agent_options=True,
    )
    run_prompt.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print PromptBundle and RenderRequest; do not call NovelAI",
    )
    run_prompt.add_argument("--config", help="Load runtime config and artist nodes")
    run_prompt.set_defaults(func=cmd_run_prompt)

    run_action = subparsers.add_parser(
        "run-action",
        parents=[output_parent],
        help="Compose character/action nodes and run NovelAI",
    )
    _add_node_compose_arguments(run_action)
    _add_novelai_render_arguments(run_action)
    run_action.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print PromptBundle and RenderRequest; do not call NovelAI",
    )
    run_action.add_argument("--config", help="Load runtime config and artist nodes")
    run_action.set_defaults(func=cmd_run_action)

    plan_batch = subparsers.add_parser(
        "plan-batch",
        parents=[output_parent],
        help="Expand a BatchSpec into tasks without calling NovelAI",
    )
    plan_batch.add_argument("batch_spec")
    plan_batch.add_argument("--output-root")
    plan_batch.set_defaults(func=cmd_plan_batch)

    run_batch = subparsers.add_parser(
        "run-batch",
        parents=[output_parent],
        help="Run a BatchSpec through the generation pipeline",
    )
    run_batch.add_argument("batch_spec")
    run_batch.add_argument("--config", help="Override BatchSpec config")
    run_batch.add_argument("--output-root")
    run_batch.add_argument("--limit", type=int)
    run_batch.set_defaults(func=cmd_run_batch)

    resume_batch = subparsers.add_parser(
        "resume-batch",
        parents=[output_parent],
        help="Resume a previous batch run directory",
    )
    resume_batch.add_argument("run_dir")
    resume_batch.add_argument("--batch-spec", help="Override stored source BatchSpec")
    resume_batch.add_argument("--config", help="Override BatchSpec config")
    resume_batch.add_argument("--limit", type=int)
    resume_batch.set_defaults(func=cmd_resume_batch)

    inspect_batch = subparsers.add_parser(
        "inspect-batch",
        parents=[output_parent],
        help="Inspect a batch run manifest",
    )
    inspect_batch.add_argument("run_dir")
    inspect_batch.set_defaults(func=cmd_inspect_batch)

    api_compose = subparsers.add_parser(
        "api-compose",
        parents=[output_parent],
        help="Build a PromptBundle from a JSON API request file",
    )
    _add_api_request_arguments(api_compose)
    api_compose.set_defaults(func=cmd_api_compose)

    api_agent_task = subparsers.add_parser(
        "api-agent-task",
        parents=[output_parent],
        help="Build an agent-readable composition task from a JSON API request file",
    )
    _add_api_request_arguments(api_agent_task)
    api_agent_task.set_defaults(func=cmd_api_agent_task)

    api_compose_agent = subparsers.add_parser(
        "api-compose-agent",
        parents=[output_parent],
        help="Build a PromptBundle from an agent JSON API request file",
    )
    _add_api_request_arguments(api_compose_agent)
    api_compose_agent.set_defaults(func=cmd_api_compose_agent)

    api_resolve_agent = subparsers.add_parser(
        "api-resolve-agent",
        parents=[output_parent],
        help="Return a cached/ready PromptBundle or an AgentCompositionTask",
    )
    _add_api_request_arguments(api_resolve_agent)
    api_resolve_agent.set_defaults(func=cmd_api_resolve_agent)

    api_render_plan = subparsers.add_parser(
        "api-render-plan",
        parents=[output_parent],
        help="Build a RenderRequest from a JSON API request file",
    )
    _add_api_request_arguments(api_render_plan)
    api_render_plan.set_defaults(func=cmd_api_render_plan)

    api_compose_render_plan = subparsers.add_parser(
        "api-compose-render-plan",
        parents=[output_parent],
        help="Build PromptBundle and RenderRequest from one JSON API request file",
    )
    _add_api_request_arguments(api_compose_render_plan)
    api_compose_render_plan.set_defaults(func=cmd_api_compose_render_plan)

    api_resolve_compose_render_plan = subparsers.add_parser(
        "api-resolve-compose-render-plan",
        parents=[output_parent],
        help="Return a ready PromptBundle+RenderRequest or an AgentCompositionTask",
    )
    _add_api_request_arguments(api_resolve_compose_render_plan)
    api_resolve_compose_render_plan.set_defaults(
        func=cmd_api_resolve_compose_render_plan
    )

    api_resolve_batch_item = subparsers.add_parser(
        "api-resolve-batch-item",
        parents=[output_parent],
        help="Resolve one batch item to ready PromptBundle+RenderRequest or AgentCompositionTask",
    )
    _add_api_request_arguments(api_resolve_batch_item)
    api_resolve_batch_item.set_defaults(func=cmd_api_resolve_batch_item)

    api_backend_support = subparsers.add_parser(
        "api-backend-support",
        parents=[output_parent],
        help="Return backend support policy from a JSON API request file",
    )
    _add_api_request_arguments(api_backend_support)
    api_backend_support.set_defaults(func=cmd_api_backend_support)

    api_generate = subparsers.add_parser(
        "api-generate",
        parents=[output_parent],
        help="Execute a RenderRequest JSON API request and return a GenerationResult",
    )
    _add_api_request_arguments(api_generate)
    api_generate.add_argument("--config", required=True, help="Load runtime and NovelAI config")
    api_generate.add_argument("--output-dir", help="Override generated image output directory")
    api_generate.set_defaults(func=cmd_api_generate)

    generate = subparsers.add_parser(
        "generate",
        parents=[output_parent],
        help="Generate image(s) with NovelAI",
    )
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--negative")
    generate.add_argument("--artist")
    generate.add_argument("--artist-node", help="Path to a structured artist node")
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
    execute_render_request.add_argument(
        "--comfyui-no-wait",
        action="store_true",
        help="Only queue a ComfyUI prompt and return prompt_id without polling history",
    )
    execute_render_request.add_argument(
        "--comfyui-poll-interval",
        type=float,
        default=1.0,
        help="Seconds between ComfyUI history polls",
    )
    execute_render_request.add_argument(
        "--comfyui-max-wait-seconds",
        type=float,
        help="Maximum seconds to wait for ComfyUI output; defaults to comfyui.timeout",
    )
    execute_render_request.add_argument(
        "--allow-experimental-backend",
        action="store_true",
        help="Allow executing pre-v1 ComfyUI/SD clients; NovelAI is the only default v1 backend",
    )
    execute_render_request.set_defaults(func=cmd_execute_render_request)

    inspect_node = subparsers.add_parser(
        "inspect-node",
        parents=[output_parent],
        help="Read a node file/directory",
    )
    inspect_node.add_argument("path")
    inspect_node.set_defaults(func=cmd_inspect_node)

    validate_node_tree_parser = subparsers.add_parser(
        "validate-node-tree",
        parents=[output_parent],
        help="Validate structured node YAML files under a directory",
    )
    validate_node_tree_parser.add_argument("path")
    validate_node_tree_parser.add_argument("--output", help="Write validation report JSON/YAML")
    validate_node_tree_parser.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output report file format when --output is used",
    )
    validate_node_tree_parser.set_defaults(func=cmd_validate_node_tree)

    inspect_artist = subparsers.add_parser(
        "inspect-artist",
        parents=[output_parent],
        help="Read a NovelAI artist node",
    )
    inspect_artist.add_argument("--config", required=True)
    inspect_artist.add_argument("--artist", required=True)
    inspect_artist.set_defaults(func=cmd_inspect_artist)

    config = subparsers.add_parser("config", parents=[output_parent], help="Read an app config file")
    config.add_argument("path")
    config.set_defaults(func=cmd_config)

    backend_support = subparsers.add_parser(
        "backend-support",
        parents=[output_parent],
        help="Print backend support stages and execution gate policy",
    )
    backend_support.set_defaults(func=cmd_backend_support)

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

    compare_image_result = subparsers.add_parser(
        "compare-image-result",
        parents=[output_parent],
        help="Build a legacy image vs core GenerationResult comparison report",
    )
    compare_image_result.add_argument("--legacy-image", required=True)
    compare_image_result.add_argument("--core-generation-result", required=True)
    compare_image_result.add_argument(
        "--core-image",
        help="Override the core image path; defaults to GenerationResult.images[0].path",
    )
    compare_image_result.add_argument(
        "--visual-result",
        default="pending",
        choices=("pending", "pass", "fail", "review"),
        help="Manual visual check result stored in the report",
    )
    compare_image_result.add_argument(
        "--visual-note",
        action="append",
        help="Manual visual check note; can be repeated",
    )
    compare_image_result.add_argument("--output", help="Write the report to JSON/YAML")
    compare_image_result.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output report file format when --output is used",
    )
    compare_image_result.set_defaults(func=cmd_compare_image_result)

    prompt_policy_acceptance = subparsers.add_parser(
        "verify-prompt-policy-acceptance",
        parents=[output_parent],
        help="Verify real PromptPolicyPipeline output against legacy image evidence",
    )
    prompt_policy_acceptance.add_argument("--legacy-image", required=True)
    prompt_policy_acceptance.add_argument(
        "--core-run-result",
        help="JSON/YAML output from run-prompt containing prompt_bundle and generation_result",
    )
    prompt_policy_acceptance.add_argument(
        "--core-generation-result",
        help="GenerationResult JSON/YAML when not using --core-run-result",
    )
    prompt_policy_acceptance.add_argument(
        "--prompt-bundle",
        help="PromptBundle JSON/YAML when not using --core-run-result",
    )
    prompt_policy_acceptance.add_argument(
        "--core-image",
        help="Override the core image path; defaults to GenerationResult.images[0].path",
    )
    prompt_policy_acceptance.add_argument(
        "--visual-result",
        default="pending",
        choices=("pending", "pass", "fail", "review"),
        help="Manual visual check result; pass is required for acceptance",
    )
    prompt_policy_acceptance.add_argument(
        "--visual-note",
        action="append",
        help="Manual visual check note; can be repeated",
    )
    prompt_policy_acceptance.add_argument(
        "--expected-profile",
        help="Expected PromptPolicyPipeline profile, for example balanced",
    )
    prompt_policy_acceptance.add_argument(
        "--require-policy-rule",
        action="append",
        help="Required policy rule id; can be repeated",
    )
    prompt_policy_acceptance.add_argument(
        "--expect-token",
        action="append",
        help="Token/text that must appear in the core PNG prompt; can be repeated",
    )
    prompt_policy_acceptance.add_argument(
        "--reject-token",
        action="append",
        help="Token/text that must not appear in the core PNG prompt; can be repeated",
    )
    prompt_policy_acceptance.add_argument(
        "--whitelist",
        action="append",
        help="Approved legacy-vs-core diff path with optional reason, for example $.parameters.sampler=alias",
    )
    prompt_policy_acceptance.add_argument(
        "--intentional-difference",
        action="append",
        help="Intentional legacy-vs-core diff path with optional reason",
    )
    prompt_policy_acceptance.add_argument("--output", help="Write the report to JSON/YAML")
    prompt_policy_acceptance.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output report file format when --output is used",
    )
    prompt_policy_acceptance.set_defaults(func=cmd_verify_prompt_policy_acceptance)

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
    create_acceptance_record.add_argument("--generation-result")
    create_acceptance_record.add_argument(
        "--oracle-kind",
        default="legacy_oracle",
        choices=("legacy_oracle", "fixture"),
        help="Acceptance source kind; use fixture only for synthetic/static mechanism tests",
    )
    create_acceptance_record.add_argument(
        "--whitelist",
        action="append",
        help="Approved diff path with optional reason, for example $.parameters.sampler=alias",
    )
    create_acceptance_record.add_argument(
        "--intentional-difference",
        action="append",
        help=(
            "Intentional core-vs-legacy diff path with optional reason, "
            "for example $.parameters.prompt=foot_detail filters face tags"
        ),
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

    archive_acceptance = subparsers.add_parser(
        "archive-acceptance-case",
        parents=[output_parent],
        help="Copy legacy/core artifacts into a replayable acceptance case directory",
    )
    archive_acceptance.add_argument("--case-id", required=True)
    archive_acceptance.add_argument("--output-dir", required=True)
    archive_acceptance.add_argument("--legacy-source", required=True)
    archive_acceptance.add_argument("--core-source", required=True)
    archive_acceptance.add_argument("--legacy-image")
    archive_acceptance.add_argument("--core-image")
    archive_acceptance.add_argument("--prompt-bundle")
    archive_acceptance.add_argument("--generation-result")
    archive_acceptance.add_argument(
        "--oracle-kind",
        default="legacy_oracle",
        choices=("legacy_oracle", "fixture"),
        help="Acceptance source kind; use fixture only for synthetic/static mechanism tests",
    )
    archive_acceptance.add_argument(
        "--whitelist",
        action="append",
        help="Approved diff path with optional reason, for example $.parameters.sampler=alias",
    )
    archive_acceptance.add_argument(
        "--intentional-difference",
        action="append",
        help=(
            "Intentional core-vs-legacy diff path with optional reason, "
            "for example $.parameters.prompt=foot_detail filters face tags"
        ),
    )
    archive_acceptance.add_argument(
        "--note",
        action="append",
        help="Human note stored in the acceptance record; can be repeated",
    )
    archive_acceptance.add_argument(
        "--manifest",
        help="Suite manifest to create or update; defaults to output-dir\\suite.yaml",
    )
    archive_acceptance.add_argument(
        "--required-case",
        action="append",
        help="Required suite case id/prefix to add to the manifest; can be repeated",
    )
    archive_acceptance.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not create or update a suite manifest",
    )
    archive_acceptance.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing copied artifacts in the case directory",
    )
    archive_acceptance.add_argument(
        "--format",
        default="yaml",
        choices=("json", "yaml"),
        help="Acceptance record format written inside the case directory",
    )
    archive_acceptance.set_defaults(func=cmd_archive_acceptance_case)

    archive_novelai_acceptance_nodes = subparsers.add_parser(
        "archive-novelai-acceptance-nodes",
        parents=[output_parent],
        help="Build NovelAI core artifacts from nodes and archive a legacy acceptance case",
    )
    _add_node_compose_arguments(archive_novelai_acceptance_nodes)
    archive_novelai_acceptance_nodes.add_argument("--case-id", required=True)
    archive_novelai_acceptance_nodes.add_argument("--output-dir", required=True)
    archive_novelai_acceptance_nodes.add_argument("--legacy-source", required=True)
    archive_novelai_acceptance_nodes.add_argument("--legacy-image")
    archive_novelai_acceptance_nodes.add_argument("--core-image")
    archive_novelai_acceptance_nodes.add_argument("--generation-result")
    archive_novelai_acceptance_nodes.add_argument(
        "--oracle-kind",
        default="legacy_oracle",
        choices=("legacy_oracle", "fixture"),
        help="Acceptance source kind; use fixture only for synthetic/static mechanism tests",
    )
    archive_novelai_acceptance_nodes.add_argument("--artist")
    archive_novelai_acceptance_nodes.add_argument("--artist-node", help="Path to a structured artist node")
    archive_novelai_acceptance_nodes.add_argument("--config", help="Load artist nodes through this config")
    archive_novelai_acceptance_nodes.add_argument("--seed", type=int)
    archive_novelai_acceptance_nodes.add_argument("--width", type=int, default=1024)
    archive_novelai_acceptance_nodes.add_argument("--height", type=int, default=1024)
    archive_novelai_acceptance_nodes.add_argument(
        "--model",
        default="nai-diffusion-4-5-full",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--params-json",
        help="Extra NovelAI renderer params as a JSON object",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--whitelist",
        action="append",
        help="Approved diff path with optional reason, for example $.parameters.sampler=alias",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--intentional-difference",
        action="append",
        help=(
            "Intentional core-vs-legacy diff path with optional reason, "
            "for example $.parameters.prompt=foot_detail filters face tags"
        ),
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--note",
        action="append",
        help="Human note stored in the acceptance record; can be repeated",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--manifest",
        help="Suite manifest to create or update; defaults to output-dir\\suite.yaml",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--required-case",
        action="append",
        help="Required suite case id/prefix to add to the manifest; can be repeated",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not create or update a suite manifest",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing generated core artifacts and copied archive artifacts",
    )
    archive_novelai_acceptance_nodes.add_argument(
        "--format",
        default="yaml",
        choices=("json", "yaml"),
        help="Acceptance record format written inside the case directory",
    )
    archive_novelai_acceptance_nodes.set_defaults(func=cmd_archive_novelai_acceptance_nodes)

    archive_novelai_acceptance_prompt = subparsers.add_parser(
        "archive-novelai-acceptance-prompt",
        parents=[output_parent],
        help="Build NovelAI core artifacts from a full prompt and archive a legacy acceptance case",
    )
    _add_prompt_run_arguments(archive_novelai_acceptance_prompt, output_options=False)
    archive_novelai_acceptance_prompt.add_argument("--case-id", required=True)
    archive_novelai_acceptance_prompt.add_argument("--output-dir", required=True)
    archive_novelai_acceptance_prompt.add_argument("--legacy-source", required=True)
    archive_novelai_acceptance_prompt.add_argument("--legacy-image")
    archive_novelai_acceptance_prompt.add_argument("--core-image")
    archive_novelai_acceptance_prompt.add_argument("--generation-result")
    archive_novelai_acceptance_prompt.add_argument(
        "--oracle-kind",
        default="legacy_oracle",
        choices=("legacy_oracle", "fixture"),
        help="Acceptance source kind; use fixture only for synthetic/static mechanism tests",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--config",
        help="Load artist nodes through this config",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--whitelist",
        action="append",
        help="Approved diff path with optional reason, for example $.parameters.sampler=alias",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--intentional-difference",
        action="append",
        help=(
            "Intentional core-vs-legacy diff path with optional reason, "
            "for example $.parameters.prompt=agent prompt wording"
        ),
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--note",
        action="append",
        help="Human note stored in the acceptance record; can be repeated",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--manifest",
        help="Suite manifest to create or update; defaults to output-dir\\suite.yaml",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--required-case",
        action="append",
        help="Required suite case id/prefix to add to the manifest; can be repeated",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not create or update a suite manifest",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing generated core artifacts and copied archive artifacts",
    )
    archive_novelai_acceptance_prompt.add_argument(
        "--format",
        default="yaml",
        choices=("json", "yaml"),
        help="Acceptance record format written inside the case directory",
    )
    archive_novelai_acceptance_prompt.set_defaults(func=cmd_archive_novelai_acceptance_prompt)

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
    verify_acceptance_suite_parser.add_argument(
        "--require-legacy-oracle",
        action="store_true",
        help="Fail unless the suite contains at least one real legacy_oracle record",
    )
    verify_acceptance_suite_parser.add_argument(
        "--require-legacy-evidence",
        action="store_true",
        help=(
            "Fail unless the suite contains legacy_oracle records and every legacy_oracle "
            "record has legacy/core image evidence, GenerationResult evidence, and "
            "PromptBundle contract evidence"
        ),
    )
    verify_acceptance_suite_parser.set_defaults(func=cmd_verify_acceptance_suite)

    verify_core = subparsers.add_parser(
        "verify-core",
        parents=[output_parent],
        help="Run the local no-network core verification gate",
    )
    verify_core.add_argument(
        "--cwd",
        default=".",
        help="Repository root to run verification commands from",
    )
    verify_core.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the verification commands without executing them",
    )
    verify_core.set_defaults(func=cmd_verify_core)

    migrate_artist_tags = subparsers.add_parser(
        "migrate-artist-tags",
        parents=[output_parent],
        help="Convert a legacy artist tags.txt into a structured artist node",
    )
    migrate_artist_tags.add_argument("source", help="Legacy artist directory or tags.txt path")
    migrate_artist_tags.add_argument("--id", help="Override generated artist node id")
    migrate_artist_tags.add_argument("--name", help="Override generated artist node name")
    migrate_artist_tags.add_argument("--output", help="Write node.yaml to this path")
    migrate_artist_tags.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    migrate_artist_tags.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output if it already exists",
    )
    migrate_artist_tags.set_defaults(func=cmd_migrate_artist_tags)

    migrate_action_tags = subparsers.add_parser(
        "migrate-action-tags",
        parents=[output_parent],
        help="Convert a legacy action tags.txt into a structured action meta node",
    )
    migrate_action_tags.add_argument("source", help="Legacy action directory or tags.txt path")
    migrate_action_tags.add_argument("--id", help="Override generated action node id")
    migrate_action_tags.add_argument("--name", help="Override generated action node name")
    migrate_action_tags.add_argument(
        "--character-scope",
        help="Override inferred action character_scope, for example foot_detail",
    )
    migrate_action_tags.add_argument("--output", help="Write meta.yaml to this path")
    migrate_action_tags.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    migrate_action_tags.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output if it already exists",
    )
    migrate_action_tags.set_defaults(func=cmd_migrate_action_tags)

    migrate_character_tags = subparsers.add_parser(
        "migrate-character-tags",
        parents=[output_parent],
        help="Convert a legacy character tags.txt into a structured character meta node",
    )
    migrate_character_tags.add_argument("source", help="Legacy character directory or tags.txt path")
    migrate_character_tags.add_argument("--id", help="Override generated character node id")
    migrate_character_tags.add_argument("--name", help="Override generated character node name")
    migrate_character_tags.add_argument("--character-id", help="Override stable character_id")
    migrate_character_tags.add_argument("--variant", help="Optional character variant label")
    migrate_character_tags.add_argument("--output", help="Write meta.yaml to this path")
    migrate_character_tags.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    migrate_character_tags.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output if it already exists",
    )
    migrate_character_tags.set_defaults(func=cmd_migrate_character_tags)

    migrate_background_tags = subparsers.add_parser(
        "migrate-background-tags",
        parents=[output_parent],
        help="Convert a legacy background tags.txt into a structured background meta node",
    )
    migrate_background_tags.add_argument("source", help="Legacy background directory or tags.txt path")
    migrate_background_tags.add_argument("--id", help="Override generated background node id")
    migrate_background_tags.add_argument("--name", help="Override generated background node name")
    migrate_background_tags.add_argument("--output", help="Write meta.yaml to this path")
    migrate_background_tags.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    migrate_background_tags.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output if it already exists",
    )
    migrate_background_tags.set_defaults(func=cmd_migrate_background_tags)

    audit_legacy_tags_parser = subparsers.add_parser(
        "audit-legacy-tags",
        parents=[output_parent],
        help="Audit legacy tags.txt files before structured node migration",
    )
    audit_legacy_tags_parser.add_argument(
        "source",
        help="Legacy tags root, node directory, or tags.txt path",
    )
    audit_legacy_tags_parser.add_argument(
        "--kind",
        required=True,
        choices=("artist", "character", "action", "background"),
        help="Legacy node kind to audit",
    )
    audit_legacy_tags_parser.add_argument("--output", help="Write audit report JSON/YAML")
    audit_legacy_tags_parser.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    audit_legacy_tags_parser.set_defaults(func=cmd_audit_legacy_tags)

    plan_legacy_tags_migration_parser = subparsers.add_parser(
        "plan-legacy-tags-migration",
        parents=[output_parent],
        help="Plan legacy tags.txt migration targets without writing node YAML",
    )
    plan_legacy_tags_migration_parser.add_argument(
        "source",
        help="Legacy tags root, node directory, or tags.txt path",
    )
    plan_legacy_tags_migration_parser.add_argument(
        "--kind",
        required=True,
        choices=("artist", "character", "action", "background"),
        help="Legacy node kind to plan",
    )
    plan_legacy_tags_migration_parser.add_argument(
        "--output-root",
        required=True,
        help="Root directory for planned migrated output, for example migrated",
    )
    plan_legacy_tags_migration_parser.add_argument("--output", help="Write migration plan JSON/YAML")
    plan_legacy_tags_migration_parser.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )
    plan_legacy_tags_migration_parser.set_defaults(func=cmd_plan_legacy_tags_migration)

    apply_legacy_tags_migration_parser = subparsers.add_parser(
        "apply-legacy-tags-migration",
        parents=[output_parent],
        help="Write ready legacy tags migration nodes without overwriting or writing old sources",
    )
    apply_legacy_tags_migration_parser.add_argument(
        "source",
        help="Legacy tags root, node directory, or tags.txt path",
    )
    apply_legacy_tags_migration_parser.add_argument(
        "--kind",
        required=True,
        choices=("artist", "character", "action", "background"),
        help="Legacy node kind to migrate",
    )
    apply_legacy_tags_migration_parser.add_argument(
        "--output-root",
        required=True,
        help="Root directory for migrated output, for example migrated",
    )
    apply_legacy_tags_migration_parser.add_argument(
        "--output",
        help="Write apply result report JSON/YAML",
    )
    apply_legacy_tags_migration_parser.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output report file format when --output is used",
    )
    apply_legacy_tags_migration_parser.set_defaults(func=cmd_apply_legacy_tags_migration)

    return parser


def _add_node_compose_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--character", help="Path to a character node")
    parser.add_argument("--action", help="Path to an action node")
    parser.add_argument("--background", help="Path to a background node")
    parser.add_argument(
        "--node",
        action="append",
        default=[],
        help="Generic node input as role:path; can be repeated",
    )
    parser.add_argument("--extra-prompt", help="Additional positive prompt text")
    parser.add_argument("--negative")
    parser.add_argument("--character-scope", help="Override character_scope for node composition")
    parser.add_argument("--body-scope", help="Compatibility alias for --character-scope")
    _add_prompt_policy_arguments(parser)


def _add_prompt_run_arguments(
    parser: argparse.ArgumentParser,
    *,
    output_options: bool,
    prompt_required: bool = True,
    agent_options: bool = False,
) -> None:
    if agent_options:
        parser.add_argument(
            "--composer",
            default="full",
            choices=("full", "agent"),
            help="Prompt composition mode; agent mode reads nodes and prompt cache",
        )
    prompt_group = parser.add_mutually_exclusive_group(required=prompt_required)
    prompt_group.add_argument("--prompt", help="Full character + action prompt / tags string")
    prompt_group.add_argument("--prompt-file", help="Read prompt from a UTF-8 text file")
    if agent_options:
        parser.add_argument("--character", help="Path to a character node when --composer agent")
        parser.add_argument("--action", help="Path to an action node when --composer agent")
        parser.add_argument("--background", help="Path to a background node when --composer agent")
        parser.add_argument("--extra-prompt", help="Additional positive prompt text for agent task")
        parser.add_argument("--character-scope", help="Override character_scope for agent composition")
        parser.add_argument("--body-scope", help="Compatibility alias for --character-scope")
        parser.add_argument(
            "--agent-instruction",
            dest="agent_instruction",
            action="append",
            help="Additional instruction for the external agent task; can be repeated",
        )
        parser.add_argument(
            "--instruction",
            action="append",
            help="Deprecated alias for --agent-instruction; can be repeated",
        )
        parser.add_argument(
            "--agent-model",
            help="External agent model/version identifier included in the prompt cache key",
        )
        parser.add_argument("--agent-result", help="Path to agent result JSON")
        parser.add_argument("--cache-dir", help="PromptBundle cache directory")
    parser.add_argument(
        "--node",
        action="append",
        default=[],
        help="Generic node input as role:path; can be repeated",
    )
    parser.add_argument("--negative")
    parser.add_argument("--nt", type=int, default=3, help="Number of images/samples")
    parser.add_argument("--artist", help="Artist preset/ref under design/画风")
    parser.add_argument("--artist-node", help="Path to a structured artist node")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--model", default="nai-diffusion-4-5-full")
    parser.add_argument("--params-json", help="Extra NovelAI renderer params as a JSON object")
    _add_prompt_policy_arguments(parser)
    if output_options:
        parser.add_argument("--output-dir", help="Override output directory")
        parser.add_argument(
            "--format",
            default="png",
            choices=("png", "jpg", "webp"),
            help="Output image format when NovelAI returns files without an extension",
        )


def _add_prompt_policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prompt-policy-profile",
        choices=("off", "normalize_only", "balanced", "strict", "legacy_compat"),
        help="Enable PromptPolicyPipeline with the selected profile",
    )
    parser.add_argument(
        "--prompt-policy-output-style",
        default="underscore",
        choices=("underscore", "preserve"),
        help="PromptPolicyPipeline output tag style when enabled",
    )
    parser.add_argument(
        "--prompt-policy-rule",
        action="append",
        default=[],
        help="Force-enable one prompt policy rule; can be repeated",
    )
    parser.add_argument(
        "--no-prompt-policy-rule",
        action="append",
        default=[],
        help="Disable one prompt policy rule; can be repeated",
    )


def _add_novelai_render_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--nt", type=int, default=3, help="Number of images/samples")
    parser.add_argument("--artist", help="Artist preset/ref under design/画风")
    parser.add_argument("--artist-node", help="Path to a structured artist node")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--model", default="nai-diffusion-4-5-full")
    parser.add_argument("--params-json", help="Extra NovelAI renderer params as a JSON object")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument(
        "--format",
        default="png",
        choices=("png", "jpg", "webp"),
        help="Output image format when NovelAI returns files without an extension",
    )

def _add_api_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("request", help="JSON request file")
    parser.add_argument("--output", help="Write API response JSON/YAML to this path")
    parser.add_argument(
        "--format",
        default="auto",
        choices=("auto", "json", "yaml"),
        help="Output file format when --output is used",
    )


def _add_agent_arguments(parser: argparse.ArgumentParser, *, result: bool) -> None:
    parser.add_argument(
        "--agent-instruction",
        dest="agent_instruction",
        action="append",
        help="Additional instruction for the external agent task; can be repeated",
    )
    parser.add_argument(
        "--instruction",
        action="append",
        help="Deprecated alias for --agent-instruction; can be repeated",
    )
    parser.add_argument(
        "--agent-model",
        help="External agent model/version identifier included in the prompt cache key",
    )
    if result:
        parser.add_argument("--agent-result", help="Path to agent result JSON")
        parser.add_argument("--cache-dir", help="PromptBundle cache directory")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(getattr(args, "log_level", None))
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    logger.trace("cli command selected command=%s", getattr(args, "command", None))
    return args.func(args)
