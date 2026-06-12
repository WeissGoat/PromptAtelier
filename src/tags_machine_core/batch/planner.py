from __future__ import annotations

import hashlib
import itertools
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


STANDARD_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1216, 832),
    "portrait": (832, 1216),
}


@dataclass(frozen=True)
class SelectionSet:
    artists: list[str]
    characters: list[str]
    actions: list[str]
    backgrounds: list[str]
    prompts: list[PromptItem]


class BatchPlanner:
    def __init__(self, *, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def plan(self, spec: BatchSpec, *, run_dir: str | Path | None = None) -> list[BatchTask]:
        resolved_run_dir = Path(run_dir or Path(spec.output_root) / spec.name)
        selections = self._resolve_selections(spec)
        if spec.expand.mode == "prompt_list":
            tasks = self._plan_prompt_list(spec, selections, run_dir=resolved_run_dir)
        elif spec.expand.mode == "product":
            tasks = self._plan_product(spec, selections, run_dir=resolved_run_dir)
        elif spec.expand.mode == "zip":
            tasks = self._plan_zip(spec, selections, run_dir=resolved_run_dir)
        elif spec.expand.mode == "manual":
            tasks = self._plan_manual(spec, run_dir=resolved_run_dir)
        else:
            raise ValueError(f"Unsupported expand mode: {spec.expand.mode}")

        if spec.expand.shuffle:
            random.shuffle(tasks)
        if spec.expand.max_tasks is not None:
            tasks = tasks[: spec.expand.max_tasks]
        return [
            task.model_copy(
                update={
                    "index": index,
                    "output": TaskOutput(task_dir=str(resolved_run_dir / "tasks" / task.id)),
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
                )
            )
        return tasks

    def _plan_product(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
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
            task_id = _task_id(character, action, artist, background, spec.defaults.composer)
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
                    },
                    run_dir=run_dir,
                )
            )
        return tasks

    def _plan_zip(
        self,
        spec: BatchSpec,
        selections: SelectionSet,
        *,
        run_dir: Path,
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
                    task_id=_task_id(index, character, action, artist, background),
                    index=index,
                    composer=spec.defaults.composer,
                    nodes=nodes,
                    artist=artist,
                    source={"zip_index": index},
                    run_dir=run_dir,
                )
            )
        return tasks

    def _plan_manual(self, spec: BatchSpec, *, run_dir: Path) -> list[BatchTask]:
        tasks: list[BatchTask] = []
        for index, raw in enumerate(spec.tasks):
            nodes = [NodeRef.model_validate(item) for item in raw.get("nodes", [])]
            for role in ("character", "action", "artist", "background"):
                value = raw.get(role)
                if value:
                    nodes.append(NodeRef(role=role, ref=str(value), index=_role_index(nodes, role)))
            artist = raw.get("artist") or spec.defaults.artist
            task_id = str(raw.get("id") or _task_id(index, artist, raw.get("prompt"), raw.get("action")))
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
                    source={"manual": True},
                    run_dir=run_dir,
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
            model=spec.defaults.model,
            image_format=spec.defaults.image_format,
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
            policy=_policy_config(spec.defaults.prompt_policy_profile, composer=composer),
            output={"task_dir": str(run_dir / "tasks" / task_id)},
            source=source or {},
        )


def _node_refs(
    *,
    character: str | None,
    action: str | None,
    artist: str | None,
    background: str | None,
) -> list[NodeRef]:
    nodes: list[NodeRef] = []
    for role, value in (
        ("character", character),
        ("action", action),
        ("artist", artist),
        ("background", background),
    ):
        if value:
            nodes.append(NodeRef(role=role, ref=value, index=_role_index(nodes, role)))
    return nodes


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


def _policy_config(profile: str | None, *, composer: str) -> dict[str, Any]:
    if not profile or profile == "off":
        return {}
    return {
        "enabled": True,
        "profile": profile,
        "apply_to": {
            "script": composer == "script",
            "agent": False,
            "full_prompt": composer == "full",
        },
    }


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
