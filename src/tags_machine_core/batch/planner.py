from __future__ import annotations

import hashlib
import itertools
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.reader import NodeReader
from tags_machine_core.policies import PromptPolicyProvider

from .action_groups import (
    ActionGroupRecord,
    choose_action_group,
    resolve_action_groups,
    resolve_record_path,
)
from .character_relations import detect_required_girl_count, resolve_cp_character_refs
from .models import (
    AgentOptions,
    BatchSpec,
    BatchTask,
    NodeRef,
    PromptItem,
    RenderOptions,
    TaskOutput,
)
from .selectors import SelectorContext, expand_selector


logger = get_logger(__name__)

STANDARD_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1216, 832),
    "portrait": (832, 1216),
    "normal_square": (1024, 1024),
    "normal_landscape": (1216, 832),
    "normal_portrait": (832, 1216),
}


@dataclass(frozen=True)
class SelectionSet:
    artists: list[str]
    characters: list[str]
    actions: list[str]
    backgrounds: list[str]
    prompts: list[PromptItem]


class BatchPlanner:
    def __init__(
        self,
        *,
        base_dir: str | Path,
        node_reader: NodeReader | None = None,
        policy_provider: PromptPolicyProvider | None = None,
    ):
        self.base_dir = Path(base_dir)
        self.node_reader = _CachedNodeReader(node_reader or NodeReader())
        self.policy_provider = policy_provider or PromptPolicyProvider.with_builtin_defaults()

    def plan(
        self,
        spec: BatchSpec,
        *,
        run_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        run_id: str | None = None,
    ) -> list[BatchTask]:
        resolved_run_dir = Path(run_dir or self.base_dir / spec.name)
        resolved_output_dir = self._resolve_output_dir(
            output_dir or spec.output_dir,
            fallback=resolved_run_dir / "outputs",
        )
        resolved_run_id = run_id or uuid4().hex[:8]
        self._validate_expand_select_contract(spec)
        selections = self._resolve_selections(spec)
        if spec.expand.mode == "prompt_list":
            tasks = self._plan_prompt_list(
                spec,
                selections,
                run_dir=resolved_run_dir,
                output_dir=resolved_output_dir,
                run_id=resolved_run_id,
            )
        elif spec.expand.mode == "product":
            tasks = self._plan_product(spec, selections, run_dir=resolved_run_dir, output_dir=resolved_output_dir, run_id=resolved_run_id)
        elif spec.expand.mode == "zip":
            tasks = self._plan_zip(spec, selections, run_dir=resolved_run_dir, output_dir=resolved_output_dir, run_id=resolved_run_id)
        elif spec.expand.mode == "character_action_group":
            tasks = self._plan_character_action_group(
                spec,
                selections,
                run_dir=resolved_run_dir,
                output_dir=resolved_output_dir,
                run_id=resolved_run_id,
            )
        elif spec.expand.mode == "blackboard_rounds":
            tasks = self._plan_blackboard_rounds(
                spec,
                selections,
                run_dir=resolved_run_dir,
                output_dir=resolved_output_dir,
                run_id=resolved_run_id,
            )
        elif spec.expand.mode == "manual":
            tasks = self._plan_manual(spec, run_dir=resolved_run_dir, output_dir=resolved_output_dir, run_id=resolved_run_id)
        else:
            raise ValueError(f"Unsupported expand mode: {spec.expand.mode}")

        if spec.expand.shuffle:
            random.shuffle(tasks)
        if spec.expand.max_tasks is not None and spec.expand.mode != "blackboard_rounds":
            tasks = tasks[: spec.expand.max_tasks]
        return [
            task.model_copy(
                update={
                    "index": index,
                    "output": TaskOutput(
                        task_dir=str(resolved_run_dir / "tasks" / task.id),
                        output_dir=str(resolved_output_dir / task.id),
                    ),
                }
            )
            for index, task in enumerate(tasks)
        ]

    def _resolve_selections(self, spec: BatchSpec) -> SelectionSet:
        context = SelectorContext(base_dir=self.base_dir, collections=spec.collections)
        artists = self._expand_refs("artist", spec.select.artists, context=context)
        if not artists and spec.defaults.artist:
            artists = [spec.defaults.artist]
        characters = self._expand_refs("character", spec.select.characters, context=context)
        actions = self._expand_refs("action", spec.select.actions, context=context)
        backgrounds = self._expand_refs("background", spec.select.backgrounds, context=context)
        prompts: list[PromptItem] = []
        for selector in spec.select.prompts:
            values = expand_selector(role="prompt", spec=selector, context=context)
            prompts.extend(PromptItem.model_validate(item) for item in values)
        return SelectionSet(
            artists=artists,
            characters=characters,
            actions=actions,
            backgrounds=backgrounds,
            prompts=prompts,
        )

    def _resolve_output_dir(self, value: str | Path | None, *, fallback: Path) -> Path:
        if value is None:
            return fallback
        path = Path(value)
        return path if path.is_absolute() else self.base_dir / path

    def _validate_expand_select_contract(self, spec: BatchSpec) -> None:
        if spec.expand.mode in {"character_action_group", "blackboard_rounds"}:
            if not spec.select.characters:
                raise ValueError(f"{spec.expand.mode} expand mode requires select.characters")
            if not spec.select.action_groups:
                raise ValueError(f"{spec.expand.mode} expand mode requires select.action_groups")
            if spec.select.actions:
                raise ValueError(
                    f"{spec.expand.mode} expand mode uses select.action_groups and "
                    "does not allow select.actions"
                )
            if (
                spec.expand.mode == "blackboard_rounds"
                and not spec.expand.max_tasks
                and not spec.expand.auto_num
            ):
                raise ValueError("blackboard_rounds expand mode requires expand.max_tasks or expand.auto_num")
            return
        if spec.select.action_groups:
            raise ValueError(
                "select.action_groups is only supported with expand.mode: character_action_group"
            )

    def _expand_refs(
        self,
        role: str,
        selectors: list[Any],
        *,
        context: SelectorContext | None = None,
    ) -> list[str]:
        context = context or SelectorContext(base_dir=self.base_dir, collections={})
        refs: list[str] = []
        for selector in selectors:
            refs.extend(str(item) for item in expand_selector(role=role, spec=selector, context=context))
        return list(dict.fromkeys(refs))

    def _plan_prompt_list(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> list[BatchTask]:
        if not selections.prompts:
            raise ValueError("prompt_list expand mode requires select.prompts")
        artists = selections.artists or ([spec.defaults.artist] if spec.defaults.artist else [None])
        tasks: list[BatchTask] = []
        for prompt_item, artist in itertools.product(selections.prompts, artists):
            nodes = list(prompt_item.nodes)
            if artist:
                nodes.append(NodeRef(role="artist", ref=artist, index=0))
            task_id = _task_id(
                run_id,
                len(tasks),
                prompt_item.id,
                artist or "no_artist",
                spec.defaults.composer,
                prompt_item.prompt,
            )
            tasks.append(
                self._task(
                    spec,
                    task_id=task_id,
                    index=len(tasks),
                    composer="full",
                    nodes=nodes,
                    prompt=prompt_item.prompt,
                    negative=prompt_item.negative,
                    artist=artist,
                    source={"prompt_id": prompt_item.id, "prompt_meta": prompt_item.meta},
                    run_dir=run_dir,
                    output_dir=output_dir,
                    run_id=run_id,
                )
            )
        return tasks

    def _plan_product(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> list[BatchTask]:
        artists = selections.artists or ([spec.defaults.artist] if spec.defaults.artist else [None])
        characters = selections.characters or [None]
        actions = selections.actions or [None]
        backgrounds = selections.backgrounds or [None]
        tasks: list[BatchTask] = []
        for character, action, artist, background in itertools.product(
            characters,
            actions,
            artists,
            backgrounds,
        ):
            nodes = _node_refs(
                character=character,
                action=action,
                artist=artist,
                background=background,
            )
            task_id = _task_id(run_id, len(tasks), character, action, artist, background, spec.defaults.composer)
            tasks.append(
                self._task(
                    spec,
                    task_id=task_id,
                    index=len(tasks),
                    composer=spec.defaults.composer,
                    nodes=nodes,
                    artist=artist,
                    source={
                        "character": character,
                        "action": action,
                        "artist": artist,
                        "background": background,
                        "run_id": run_id,
                    },
                    run_dir=run_dir,
                    output_dir=output_dir,
                    run_id=run_id,
                )
            )
        return tasks

    def _plan_zip(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> list[BatchTask]:
        artists = selections.artists or ([spec.defaults.artist] if spec.defaults.artist else [None])
        max_len = max(len(selections.characters), len(selections.actions), len(artists))
        if max_len == 0:
            raise ValueError("zip expand mode requires at least one selected node")
        tasks: list[BatchTask] = []
        for index in range(max_len):
            character = _zip_item(selections.characters, index)
            action = _zip_item(selections.actions, index)
            artist = _zip_item(artists, index)
            background = _zip_item(selections.backgrounds, index)
            nodes = _node_refs(
                character=character,
                action=action,
                artist=artist,
                background=background,
            )
            tasks.append(
                self._task(
                    spec,
                    task_id=_task_id(run_id, index, character, action, artist, background),
                    index=index,
                    composer=spec.defaults.composer,
                    nodes=nodes,
                    artist=artist,
                    source={"zip_index": index, "run_id": run_id},
                    run_dir=run_dir,
                    output_dir=output_dir,
                    run_id=run_id,
                )
            )
        return tasks

    def _plan_character_action_group(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> list[BatchTask]:
        artists = selections.artists or ([spec.defaults.artist] if spec.defaults.artist else [None])
        backgrounds = selections.backgrounds or [None]
        context = SelectorContext(base_dir=self.base_dir, collections=spec.collections)
        groups = resolve_action_groups(spec.select.action_groups, context=context)
        group_indices = {group.name: index for index, group in enumerate(groups)}
        record_path = resolve_record_path(spec.expand.action_group_record, base_dir=self.base_dir)
        record = ActionGroupRecord.load(record_path)
        rng = random.Random(spec.expand.seed)
        tasks: list[BatchTask] = []

        logger.info(
            "batch plan action_groups resolved groups=%s characters=%s strategy=%s",
            len(groups),
            len(selections.characters),
            spec.expand.action_group_strategy,
        )
        for character_index, character in enumerate(selections.characters):
            group, selected_count = choose_action_group(
                groups,
                strategy=spec.expand.action_group_strategy,
                character_index=character_index,
                rng=rng,
                record=record,
            )
            if spec.expand.action_group_strategy == "balanced_random":
                record.save(record_path)
            logger.info(
                "action group selected character=%s group=%s strategy=%s action_count=%s selected_count=%s",
                Path(character).name,
                group.name,
                spec.expand.action_group_strategy,
                len(group.actions),
                selected_count,
            )
            for action_index, action in enumerate(group.actions):
                character_refs, character_source = self._character_refs_for_action(
                    spec,
                    character=character,
                    action=action,
                    candidate_characters=selections.characters,
                )
                if character_refs is None:
                    continue
                for artist, background in itertools.product(artists, backgrounds):
                    nodes = _node_refs(
                        characters=character_refs,
                        action=action,
                        artist=artist,
                        background=background,
                    )
                    task_id = _task_id(
                        run_id,
                        len(tasks),
                        character,
                        group.name,
                        action,
                        artist,
                        background,
                        spec.defaults.composer,
                    )
                    tasks.append(
                        self._task(
                            spec,
                            task_id=task_id,
                            index=len(tasks),
                            composer=spec.defaults.composer,
                            nodes=nodes,
                            artist=artist,
                            source={
                                "character": character,
                                "action": action,
                                "artist": artist,
                                "background": background,
                                **character_source,
                                "run_id": run_id,
                                "action_group": group.name,
                                "action_group_strategy": spec.expand.action_group_strategy,
                                "action_group_record": str(record_path) if record_path else None,
                                "action_group_index": group_indices[group.name],
                                "action_index_in_group": action_index,
                                "action_count_in_group": len(group.actions),
                                "action_group_selected_count": selected_count,
                            },
                            run_dir=run_dir,
                            output_dir=output_dir,
                            run_id=run_id,
                        )
                    )
        return tasks

    def _plan_blackboard_rounds(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> list[BatchTask]:
        artists = selections.artists or ([spec.defaults.artist] if spec.defaults.artist else [None])
        backgrounds = selections.backgrounds or [None]
        context = SelectorContext(base_dir=self.base_dir, collections=spec.collections)
        groups = resolve_action_groups(spec.select.action_groups, context=context)
        group_indices = {group.name: index for index, group in enumerate(groups)}
        record_path = resolve_record_path(spec.expand.action_group_record, base_dir=self.base_dir)
        record = ActionGroupRecord.load(record_path)
        rng = random.Random(spec.expand.seed)
        task_target = spec.expand.max_tasks or 0
        tasks: list[BatchTask] = []
        max_planning_rounds = max(
            task_target * max(len(selections.characters), 1) * max(len(groups), 1),
            max(len(selections.characters), 1) * max(len(groups), 1) * 2,
        )

        logger.info(
            "batch plan blackboard_rounds groups=%s characters=%s strategy=%s max_tasks=%s auto_num=%s",
            len(groups),
            len(selections.characters),
            spec.expand.action_group_strategy,
            task_target,
            spec.expand.auto_num,
        )
        if spec.expand.auto_num:
            auto_tasks = self._plan_blackboard_auto_rounds(
                spec,
                selections,
                groups=groups,
                group_indices=group_indices,
                record=record,
                record_path=record_path,
                rng=rng,
                artists=artists,
                backgrounds=backgrounds,
                run_dir=run_dir,
                output_dir=output_dir,
                run_id=run_id,
                task_target=task_target,
            )
            logger.info(
                "batch plan blackboard_rounds auto_num planned task_count=%s max_tasks=%s",
                len(auto_tasks),
                task_target or "auto",
            )
            return auto_tasks
        round_index = 0
        while len(tasks) < task_target:
            if round_index >= max_planning_rounds:
                raise ValueError(
                    "blackboard_rounds could not reach expand.max_tasks; "
                    f"created={len(tasks)} target={task_target} rounds={round_index}. "
                    "Check action filters and character relations.cp for multi-character actions."
                )
            character = selections.characters[round_index % len(selections.characters)]
            group, selected_count = choose_action_group(
                groups,
                strategy=spec.expand.action_group_strategy,
                character_index=round_index,
                rng=rng,
                record=record,
            )
            if spec.expand.action_group_strategy == "balanced_random":
                record.save(record_path)
            logger.info(
                "blackboard round selected round=%s character=%s group=%s action_count=%s selected_count=%s",
                round_index,
                Path(character).name,
                group.name,
                len(group.actions),
                selected_count,
            )
            for action_index, action in enumerate(group.actions):
                character_refs, character_source = self._character_refs_for_action(
                    spec,
                    character=character,
                    action=action,
                    candidate_characters=selections.characters,
                )
                if character_refs is None:
                    continue
                for artist, background in itertools.product(artists, backgrounds):
                    nodes = _node_refs(
                        characters=character_refs,
                        action=action,
                        artist=artist,
                        background=background,
                    )
                    task_id = _task_id(
                        run_id,
                        len(tasks),
                        round_index,
                        action_index,
                        character,
                        group.name,
                        action,
                        artist,
                        background,
                        spec.defaults.composer,
                    )
                    tasks.append(
                        self._task(
                            spec,
                            task_id=task_id,
                            index=len(tasks),
                            composer=spec.defaults.composer,
                            nodes=nodes,
                            artist=artist,
                            source={
                                "character": character,
                                "action": action,
                                "artist": artist,
                                "background": background,
                                **character_source,
                                "run_id": run_id,
                                "round_index": round_index,
                                "action_group": group.name,
                                "action_group_strategy": spec.expand.action_group_strategy,
                                "action_group_record": str(record_path) if record_path else None,
                                "action_group_index": group_indices[group.name],
                                "action_index_in_group": action_index,
                                "action_count_in_group": len(group.actions),
                                "action_group_selected_count": selected_count,
                            },
                            run_dir=run_dir,
                            output_dir=output_dir,
                            run_id=run_id,
                        )
                    )
                    if len(tasks) >= task_target:
                        logger.info(
                            "blackboard round reached max_tasks task_count=%s target=%s",
                            len(tasks),
                            task_target,
                        )
                        return tasks
            round_index += 1
        return tasks

    def _plan_blackboard_auto_rounds(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        groups,
        group_indices: dict[str, int],
        record: ActionGroupRecord,
        record_path: Path | None,
        rng: random.Random,
        artists: list[str | None],
        backgrounds: list[str | None],
        run_dir: Path,
        output_dir: Path,
        run_id: str,
        task_target: int = 0,
    ) -> list[BatchTask]:
        tasks: list[BatchTask] = []
        for round_index, character in enumerate(selections.characters):
            group, selected_count = choose_action_group(
                groups,
                strategy=spec.expand.action_group_strategy,
                character_index=round_index,
                rng=rng,
                record=record,
            )
            if spec.expand.action_group_strategy == "balanced_random":
                record.save(record_path)
            logger.info(
                "blackboard auto_num round selected round=%s character=%s group=%s action_count=%s selected_count=%s",
                round_index,
                Path(character).name,
                group.name,
                len(group.actions),
                selected_count,
            )
            for action_index, action in enumerate(group.actions):
                character_refs, character_source = self._character_refs_for_action(
                    spec,
                    character=character,
                    action=action,
                    candidate_characters=selections.characters,
                )
                if character_refs is None:
                    continue
                for artist, background in itertools.product(artists, backgrounds):
                    nodes = _node_refs(
                        characters=character_refs,
                        action=action,
                        artist=artist,
                        background=background,
                    )
                    task_id = _task_id(
                        run_id,
                        len(tasks),
                        round_index,
                        action_index,
                        character,
                        group.name,
                        action,
                        artist,
                        background,
                        spec.defaults.composer,
                    )
                    tasks.append(
                        self._task(
                            spec,
                            task_id=task_id,
                            index=len(tasks),
                            composer=spec.defaults.composer,
                            nodes=nodes,
                            artist=artist,
                            source={
                                "character": character,
                                "action": action,
                                "artist": artist,
                                "background": background,
                                **character_source,
                                "run_id": run_id,
                                "round_index": round_index,
                                "auto_num": True,
                                "action_group": group.name,
                                "action_group_strategy": spec.expand.action_group_strategy,
                                "action_group_record": str(record_path) if record_path else None,
                                "action_group_index": group_indices[group.name],
                                "action_index_in_group": action_index,
                                "action_count_in_group": len(group.actions),
                                "action_group_selected_count": selected_count,
                            },
                            run_dir=run_dir,
                            output_dir=output_dir,
                            run_id=run_id,
                        )
                    )
                    if task_target and len(tasks) >= task_target:
                        logger.info(
                            "blackboard auto_num reached max_tasks task_count=%s target=%s",
                            len(tasks),
                            task_target,
                        )
                        return tasks
        return tasks

    def _plan_manual(self, spec: BatchSpec, *, run_dir: Path, output_dir: Path, run_id: str) -> list[BatchTask]:
        tasks: list[BatchTask] = []
        for index, raw in enumerate(spec.tasks):
            nodes = [NodeRef.model_validate(item) for item in raw.get("nodes", [])]
            for role in ("character", "action", "artist", "background"):
                value = raw.get(role)
                if value:
                    nodes.append(NodeRef(role=role, ref=str(value), index=_role_index(nodes, role)))
            artist = raw.get("artist") or spec.defaults.artist
            task_id = str(raw.get("id") or _task_id(run_id, index, artist, raw.get("prompt"), raw.get("action")))
            tasks.append(
                self._task(
                    spec,
                    task_id=task_id,
                    index=index,
                    composer=raw.get("composer") or spec.defaults.composer,
                    nodes=nodes,
                    prompt=raw.get("prompt"),
                    negative=raw.get("negative"),
                    artist=artist,
                    source={"manual": True, "run_id": run_id},
                    run_dir=run_dir,
                    output_dir=output_dir,
                    run_id=run_id,
                )
            )
        return tasks

    def _task(
        self,
        spec: BatchSpec,
        *,
        task_id: str,
        index: int,
        composer: str,
        nodes: list[NodeRef],
        artist: str | None = None,
        prompt: str | None = None,
        negative: str | None = None,
        source: dict[str, Any] | None = None,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
    ) -> BatchTask:
        render_params = dict(spec.defaults.params)
        if spec.defaults.character_prompts == "auto":
            render_params.setdefault(
                "character_prompts",
                {
                    "mode": "auto",
                    "add_male_caption": spec.defaults.add_male_caption,
                },
            )
        width, height = _resolve_dimensions(
            resolution=spec.defaults.resolution,
            width=spec.defaults.width,
            height=spec.defaults.height,
        )
        render = RenderOptions(
            backend=spec.defaults.backend,
            artist=artist or spec.defaults.artist,
            nt=spec.defaults.nt,
            resolution=spec.defaults.resolution,
            width=width,
            height=height,
            seed=spec.defaults.seed,
            model=spec.defaults.model if spec.defaults.backend == "novelai" else None,
            image_format=spec.defaults.image_format,
            output_dir=str(output_dir / task_id),
            params=render_params,
        )
        return BatchTask(
            id=task_id,
            index=index,
            composer=composer,
            nodes=_reindex_nodes(nodes),
            prompt=prompt,
            negative=negative,
            render=render,
            agent=AgentOptions(
                agent_model=spec.defaults.agent_model,
                cache_dir=spec.defaults.cache_dir,
            ),
            policy=self.policy_provider.resolve(
                spec.defaults.prompt_policy,
                relative_to=self.base_dir,
            ),
            artist_input_filter=spec.defaults.artist_input_filter,
            output={
                "task_dir": str(run_dir / "tasks" / task_id),
                "output_dir": str(output_dir / task_id),
            },
            source=source or {},
        )

    def _character_refs_for_action(
        self,
        spec: BatchSpec,
        *,
        character: str,
        action: str,
        candidate_characters: list[str],
    ) -> tuple[list[str] | None, dict[str, Any]]:
        action_node = self.node_reader.read(action)
        required_count = detect_required_girl_count(action_node)
        if required_count <= 1:
            return [character], {}

        main_character = self.node_reader.read(character)
        character_refs = resolve_cp_character_refs(
            main_ref=character,
            main_character=main_character,
            candidate_refs=candidate_characters,
            reader=self.node_reader,
            required_count=required_count,
            allow_fill_missing_from_candidates=spec.expand.allow_fill_missing_cp_from_candidates,
        )
        if character_refs is None:
            logger.warning(
                "skip multi-character task character=%s action=%s required=%s reason=missing_cp",
                Path(character).name,
                Path(action).name,
                required_count,
            )
            return None, {
                "auto_cp": False,
                "required_character_count": required_count,
                "skip_reason": "missing_cp",
            }
        resolved_refs, relation_source = character_refs
        return resolved_refs, {
            "characters": resolved_refs,
            "auto_cp": True,
            "required_character_count": required_count,
            **relation_source,
        }


def _node_refs(
    *,
    character: str | None = None,
    characters: list[str] | None = None,
    action: str | None = None,
    artist: str | None = None,
    background: str | None = None,
) -> list[NodeRef]:
    nodes: list[NodeRef] = []
    for value in characters or ([character] if character else []):
        if value:
            nodes.append(NodeRef(role="character", ref=value, index=_role_index(nodes, "character")))
    for role, value in (
        ("action", action),
        ("artist", artist),
        ("background", background),
    ):
        if value:
            nodes.append(NodeRef(role=role, ref=value, index=_role_index(nodes, role)))
    return nodes


class _CachedNodeReader:
    def __init__(self, reader: NodeReader):
        self.reader = reader
        self.cache: dict[str, Any] = {}

    def read(self, path: str | Path):
        key = str(Path(path))
        node = self.cache.get(key)
        if node is None:
            node = self.reader.read(path)
            self.cache[key] = node
        return node


def _reindex_nodes(nodes: list[NodeRef]) -> list[NodeRef]:
    counts: dict[str, int] = {}
    result: list[NodeRef] = []
    for node in nodes:
        index = counts.get(node.role, 0)
        counts[node.role] = index + 1
        result.append(node.model_copy(update={"index": index}))
    return result


def _role_index(nodes: list[NodeRef], role: str) -> int:
    return len([node for node in nodes if node.role == role])


def _zip_item(values: list[str | None], index: int) -> str | None:
    if not values:
        return None
    return values[index % len(values)]


def _resolve_dimensions(
    *,
    resolution: str,
    width: int | None,
    height: int | None,
) -> tuple[int | None, int | None]:
    if width and height:
        return width, height
    if resolution == "random_standard":
        return random.choice(list(STANDARD_RESOLUTIONS.values()))
    if resolution in STANDARD_RESOLUTIONS:
        return STANDARD_RESOLUTIONS[resolution]
    return width, height


def _task_id(*parts: Any) -> str:
    clean = [_slug(part) for part in parts if part is not None and str(part).strip()]
    prefix = "_".join(clean[:4])[:80].strip("_") or "task"
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def _slug(value: Any) -> str:
    text = Path(str(value)).name if isinstance(value, (str, Path)) else str(value)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "item"
