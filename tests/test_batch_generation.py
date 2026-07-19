import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.batch import (
    ArchiveConfig,
    ActionGroupRecord,
    ActionGroupStateStore,
    BatchArchive,
    BatchPlanner,
    BatchRunner,
    SelectorContext,
    SelectorSpec,
    expand_selector,
    load_batch_spec,
    mark_round_started,
    mark_round_finished,
    resolve_action_groups,
    select_group_actions,
)
from tags_machine_core.batch.action_groups import ResolvedActionGroup
from tags_machine_core.batch.executor import BatchExecutor
from tags_machine_core.batch.executor import BatchExecutionResult
from tags_machine_core.batch.manifest import write_initial_manifest
from tags_machine_core.batch.models import (
    BatchSpec,
    BatchTask,
    ExpandConfig,
    RenderOptions,
    RetryConfig,
    RunConfig,
)
from tags_machine_core.batch.report import write_report
from tags_machine_core.cli import main
from tags_machine_core.config import AppConfig, LegacyConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult, PromptBundle, RenderRequest
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet


def _write_node(path: Path, *, kind: str, node_id: str, prompt: str) -> None:
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(
        f"""
schema: tags-machine.{kind}/v1
kind: {kind}
id: {node_id}
tags:
  default:
    - {prompt}
""".strip(),
        encoding="utf-8",
    )


def _write_character_node(
    path: Path,
    *,
    node_id: str,
    character_id: str,
    cp: list[str] | None = None,
) -> None:
    path.mkdir(parents=True)
    relations = ""
    if cp:
        relations = "relations:\n  cp:\n" + "".join(f"    - {item}\n" for item in cp)
    (path / "meta.yaml").write_text(
        f"""
schema: tags-machine.character/v1
kind: character
id: {node_id}
character_id: {character_id}
tags:
  character:
    - {character_id}
{relations}
""".strip(),
        encoding="utf-8",
    )


class FakeExecutor:
    def __init__(self, status: str = "requires_agent"):
        self.status = status
        self.calls = 0
        self.tasks = []

    def execute(self, task, *, config, output_dir=None):
        self.calls += 1
        self.tasks.append(task)
        if self.status == "requires_agent":
            return BatchExecutionResult(
                status="requires_agent",
                agent_task={"task_id": task.id, "prompt": "fill me"},
            )
        return BatchExecutionResult(status="failed", error="fake failure")


class FlakyExecutor:
    def __init__(self):
        self.calls = 0
        self.timeouts: list[int] = []

    def execute(self, task, *, config, output_dir=None):
        self.calls += 1
        self.timeouts.append(config.novelai.timeout)
        if self.calls == 1:
            raise RuntimeError("502 bad gateway")
        return BatchExecutionResult(
            status="requires_agent",
            agent_task={"task_id": task.id, "prompt": "fill me"},
        )


class SuccessfulExecutor:
    def __init__(self, *, png_info=None):
        self.calls = 0
        self.tasks = []
        self.png_info = png_info if png_info is not None else {"images": [{"parameters": {"seed": 1}}]}

    def execute(self, task, *, config, output_dir=None):
        self.calls += 1
        self.tasks.append(task)
        image_dir = Path(output_dir or task.output.task_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"{task.id}.png"
        image_path.write_bytes(b"png")
        return BatchExecutionResult(
            status="succeeded",
            prompt_bundle=PromptBundle.model_validate(
                {"prompt": {"positive": task.prompt or "akemi_homura", "negative": ""}}
            ),
            render_request=RenderRequest.model_validate(
                {
                    "backend": "novelai",
                    "prompt": task.prompt or "akemi_homura",
                    "params": {"n_samples": task.render.nt},
                }
            ),
            generation_result=GenerationResult(
                backend="novelai",
                images=[GeneratedImage(path=image_path, filename=image_path.name)],
                request_body={"parameters": {"n_samples": task.render.nt}},
                png_info=self.png_info,
            ),
            image_paths=[str(image_path)],
        )


class BatchGenerationTest(unittest.TestCase):
    def test_load_batch_spec_merges_required_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "base.yaml").write_text(
                """
schema: tags-machine-core.batch/v1
name: base-name
defaults:
  backend: novelai
  nt: 1
  resolution: random_standard
collections:
  characters:
    madoka_main:
      - characters
run:
  retry:
    max_attempts: 2
""".strip(),
                encoding="utf-8",
            )
            spec_path = root / "batch.yaml"
            spec_path.write_text(
                """
require:
  - project/base.yaml
name: merged-batch
defaults:
  nt: 3
collections:
  characters:
    madoka_main:
      - homura
    homura_only:
      - homura
run:
  retry:
    timeout_seconds: 1.0
""".strip(),
                encoding="utf-8",
            )

            spec = load_batch_spec(spec_path)

            self.assertEqual(spec.name, "merged-batch")
            self.assertEqual(spec.defaults.backend, "novelai")
            self.assertEqual(spec.defaults.nt, 3)
            self.assertEqual(spec.defaults.resolution, "random_standard")
            self.assertEqual(spec.collections["characters"]["madoka_main"], ["homura"])
            self.assertEqual(spec.collections["characters"]["homura_only"], ["homura"])
            self.assertEqual(spec.run.retry.max_attempts, 2)
            self.assertEqual(spec.run.retry.timeout_seconds, 1.0)

    def test_load_batch_spec_rejects_circular_require(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.yaml").write_text("require: b.yaml\nname: a\n", encoding="utf-8")
            (root / "b.yaml").write_text("require: a.yaml\nname: b\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Circular batch require"):
                load_batch_spec(root / "a.yaml")

    def test_artist_collection_returns_artist_refs(self):
        context = SelectorContext(
            base_dir=Path("."),
            collections={"artists": {"nai4_common": ["20260412", "20260412_2"]}},
        )
        spec = SelectorSpec(selector="collection", name="nai4_common")

        refs = expand_selector(role="artist", spec=spec, context=context)

        self.assertEqual(refs, ["20260412", "20260412_2"])

    def test_action_collection_supports_selectors_and_collection_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "actions" / "pn_alpha", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "actions" / "pn_beta", kind="action", node_id="b1", prompt="b1")
            _write_node(root / "actions" / "st_other", kind="action", node_id="c1", prompt="c1")
            context = SelectorContext(
                base_dir=root,
                collections={
                    "actions": {
                        "action_new": [
                            {
                                "selector": "folder",
                                "root": "actions",
                                "include": {"names": ["pn_*"]},
                            }
                        ],
                        "action_other": ["actions/st_other"],
                        "combined": [
                            {"collection": "action_new"},
                            {"collection": "action_other"},
                        ],
                    }
                },
            )

            refs = expand_selector(role="action", spec=SelectorSpec(selector="collection", name="combined"), context=context)

            self.assertEqual([Path(ref).name for ref in refs], ["pn_alpha", "pn_beta", "st_other"])

    def test_collection_reference_rejects_cycles(self):
        context = SelectorContext(
            base_dir=Path("."),
            collections={
                "actions": {
                    "a": [{"collection": "b"}],
                    "b": [{"collection": "a"}],
                }
            },
        )

        with self.assertRaisesRegex(ValueError, "Circular collection reference"):
            expand_selector(role="action", spec=SelectorSpec(selector="collection", name="a"), context=context)

    def test_batch_shorthand_plans_blackboard_rounds_from_collections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
            for action_name in ("a1", "a2"):
                _write_node(
                    root / "actions" / "st_rp" / action_name,
                    kind="action",
                    node_id=action_name,
                    prompt=action_name,
                )
            (root / "project.yaml").write_text(
                """
schema: tags-machine-core.batch/v1
name: project-defaults
defaults:
  artist: 20260412
  composer: script
collections:
  characters:
    homura_set:
      - characters
  actions:
    st_rp:
      - actions/st_rp
""".strip(),
                encoding="utf-8",
            )
            spec_path = root / "batch.yaml"
            spec_path.write_text(
                """
require: project.yaml
name: shorthand-batch
batch:
  characters: homura_set
  action_groups:
    - st_rp
  strategy: ordered
  auto_num: true
""".strip(),
                encoding="utf-8",
            )

            spec = load_batch_spec(spec_path)
            tasks = BatchPlanner(base_dir=root).plan(spec, run_dir=root / "run", run_id="testrun")

            self.assertEqual(spec.expand.mode, "blackboard_rounds")
            self.assertTrue(spec.expand.auto_num)
            self.assertEqual(spec.expand.action_group_strategy, "ordered")
            self.assertEqual(len(tasks), 2)
            self.assertEqual([task.source["action_group"] for task in tasks], ["st_rp", "st_rp"])
            self.assertEqual(tasks[0].render.artist, "20260412")

    def test_batch_resolution_accepts_nai_const_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
            _write_node(root / "actions" / "standing", kind="action", node_id="standing", prompt="standing")
            spec = BatchSpec.model_validate(
                {
                    "name": "resolution-alias",
                    "defaults": {
                        "composer": "script",
                        "artist": "20260412",
                        "resolution": "normal_landscape",
                    },
                    "select": {
                        "characters": [{"selector": "explicit", "refs": [str(root / "characters" / "homura")]}],
                        "actions": [{"selector": "explicit", "refs": [str(root / "actions" / "standing")]}],
                    },
                    "expand": {"mode": "product"},
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].render.width, 1216)
            self.assertEqual(tasks[0].render.height, 832)

    def test_prompt_list_plan_writes_two_tasks(self):
        spec = BatchSpec.model_validate(
            {
                "schema": "tags-machine-core.batch/v1",
                "name": "prompt-smoke",
                "defaults": {"artist": 20260412, "resolution": "square"},
                "select": {
                    "prompts": [
                        {
                            "selector": "prompt_list",
                            "items": [
                                {"id": "p1", "prompt": "akemi_homura, standing"},
                                {"id": "p2", "prompt": "akemi_homura, foot focus"},
                            ],
                        }
                    ]
                },
                "expand": {"mode": "prompt_list"},
            }
        )

        tasks = BatchPlanner(base_dir=Path(".")).plan(spec)

        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].composer, "full")
        self.assertEqual(tasks[0].render.artist, "20260412")
        self.assertEqual(tasks[0].render.width, 1024)
        self.assertEqual(tasks[0].render.height, 1024)

    def test_planner_writes_task_output_dir_under_outputs(self):
        spec = BatchSpec.model_validate(
            {
                "schema": "tags-machine-core.batch/v1",
                "name": "prompt-output",
                "defaults": {"artist": 20260412, "resolution": "square"},
                "select": {
                    "prompts": [
                        {
                            "selector": "prompt_list",
                            "items": [
                                {"id": "p1", "prompt": "akemi_homura, standing"},
                            ],
                        }
                    ]
                },
                "expand": {"mode": "prompt_list"},
            }
        )

        tasks = BatchPlanner(base_dir=Path(".")).plan(spec, run_dir=Path("run"), run_id="testrun")

        self.assertEqual(len(tasks), 1)
        self.assertIn("outputs", tasks[0].render.output_dir.replace("\\", "/"))
        self.assertTrue(tasks[0].render.output_dir.replace("\\", "/").endswith(tasks[0].id))
        self.assertTrue(tasks[0].output.output_dir.replace("\\", "/").endswith(tasks[0].id))

    def test_collection_action_selector_expands_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "actions" / "a1", kind="action", node_id="a1", prompt="standing")
            _write_node(root / "actions" / "a2", kind="action", node_id="a2", prompt="sitting")
            spec = BatchSpec.model_validate(
                {
                    "name": "collection-smoke",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "collections": {"actions": {"basic": [str(root / "actions")]}},
                    "select": {
                        "actions": [
                            {"selector": "collection", "name": "basic", "recursive": True}
                        ]
                    },
                    "expand": {"mode": "product"},
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 2)
            self.assertEqual([task.nodes[0].role for task in tasks], ["action", "action"])

    def test_glob_selector_expands_matching_node_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "actions" / "a1", kind="action", node_id="a1", prompt="standing")
            _write_node(root / "actions" / "a2", kind="action", node_id="a2", prompt="sitting")

            refs = expand_selector(
                role="action",
                spec=SelectorSpec(
                    selector="glob",
                    pattern=str(root / "actions" / "*" / "meta.yaml"),
                ),
                context=SelectorContext(base_dir=root, collections={}),
            )

            self.assertEqual([Path(ref).name for ref in refs], ["a1", "a2"])

    def test_folder_selector_supports_include_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "actions" / "keep", kind="action", node_id="keep", prompt="standing")
            _write_node(root / "actions" / "drop", kind="action", node_id="drop", prompt="sitting")
            spec = BatchSpec.model_validate(
                {
                    "name": "include-smoke",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "actions": [
                            {
                                "selector": "folder",
                                "root": str(root / "actions"),
                                "recursive": True,
                                "include": {"names": ["keep"]},
                            }
                        ]
                    },
                    "expand": {"mode": "product"},
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 1)
            self.assertIn("keep", tasks[0].nodes[0].ref)

    def test_prompt_file_selector_reads_effective_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_file = root / "prompts.txt"
            prompt_file.write_text(
                "\n# comment\nakemi_homura, standing\n\nakemi_homura, foot focus\n",
                encoding="utf-8",
            )

            items = expand_selector(
                role="prompt",
                spec=SelectorSpec(selector="prompt_file", path=str(prompt_file), format="lines"),
                context=SelectorContext(base_dir=root, collections={}),
            )

            self.assertEqual([item.id for item in items], ["prompts_0001", "prompts_0002"])
            self.assertEqual(items[0].prompt, "akemi_homura, standing")

    def test_prompt_file_selector_reads_jsonl_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl_path = root / "prompts.jsonl"
            jsonl_path.write_text(
                '{"id":"j1","prompt":"akemi_homura, standing"}\n',
                encoding="utf-8",
            )
            csv_path = root / "prompts.csv"
            csv_path.write_text(
                "id,prompt,negative\nc1,\"akemi_homura, sitting\",bad anatomy\n",
                encoding="utf-8",
            )

            jsonl_items = expand_selector(
                role="prompt",
                spec=SelectorSpec(selector="prompt_file", path=str(jsonl_path), format="jsonl"),
                context=SelectorContext(base_dir=root, collections={}),
            )
            csv_items = expand_selector(
                role="prompt",
                spec=SelectorSpec(selector="prompt_file", path=str(csv_path), format="csv"),
                context=SelectorContext(base_dir=root, collections={}),
            )

            self.assertEqual(jsonl_items[0].id, "j1")
            self.assertEqual(csv_items[0].id, "c1")
            self.assertEqual(csv_items[0].negative, "bad anatomy")

    def test_zip_and_manual_expand_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="akemi_homura")
            _write_node(root / "characters" / "c2", kind="character", node_id="c2", prompt="kaname_madoka")
            _write_node(root / "actions" / "a1", kind="action", node_id="a1", prompt="standing")
            spec = BatchSpec.model_validate(
                {
                    "name": "zip-smoke",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "folder",
                                "root": str(root / "characters"),
                                "recursive": True,
                            }
                        ],
                        "actions": [
                            {
                                "selector": "folder",
                                "root": str(root / "actions"),
                                "recursive": True,
                            }
                        ],
                    },
                    "expand": {"mode": "zip"},
                }
            )

            zip_tasks = BatchPlanner(base_dir=root).plan(spec)
            manual_tasks = BatchPlanner(base_dir=root).plan(
                BatchSpec.model_validate(
                    {
                        "name": "manual-smoke",
                        "defaults": {"composer": "full", "artist": "20260412"},
                        "expand": {"mode": "manual"},
                        "tasks": [
                            {
                                "id": "m1",
                                "composer": "full",
                                "prompt": "akemi_homura, standing",
                                "negative": "bad anatomy",
                            }
                        ],
                    }
                )
            )

            self.assertEqual(len(zip_tasks), 2)
            self.assertEqual(zip_tasks[0].nodes[0].role, "character")
            self.assertEqual(manual_tasks[0].id, "m1")
            self.assertEqual(manual_tasks[0].prompt, "akemi_homura, standing")

    def test_character_action_group_ordered_plans_character_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="homura")
            _write_node(root / "characters" / "c2", kind="character", node_id="c2", prompt="madoka")
            _write_node(root / "groups" / "g1" / "a1", kind="action", node_id="a1", prompt="standing")
            _write_node(root / "groups" / "g1" / "a2", kind="action", node_id="a2", prompt="sitting")
            _write_node(root / "groups" / "g2" / "b1", kind="action", node_id="b1", prompt="running")
            spec = BatchSpec.model_validate(
                {
                    "name": "character-action-group",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "c1"),
                                    str(root / "characters" / "c2"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            },
                            {
                                "name": "g2",
                                "selector": "folder",
                                "root": str(root / "groups" / "g2"),
                                "recursive": True,
                            },
                        ],
                    },
                    "expand": {
                        "mode": "character_action_group",
                        "action_group_strategy": "ordered",
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 3)
            self.assertEqual([task.source["action_group"] for task in tasks], ["g1", "g1", "g2"])
            self.assertEqual([Path(task.source["character"]).name for task in tasks], ["c1", "c1", "c2"])
            self.assertEqual([Path(task.source["action"]).name for task in tasks], ["a1", "a2", "b1"])

    def test_character_action_group_auto_adds_cp_character_for_two_girls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_character_node(
                root / "characters" / "homura",
                node_id="homura",
                character_id="akemi_homura",
                cp=["kaname_madoka"],
            )
            _write_character_node(
                root / "characters" / "madoka",
                node_id="madoka",
                character_id="kaname_madoka",
            )
            _write_node(root / "groups" / "g1" / "a1", kind="action", node_id="a1", prompt="2girls, sitting")
            spec = BatchSpec.model_validate(
                {
                    "name": "auto-cp",
                    "defaults": {"composer": "script", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "homura"),
                                    str(root / "characters" / "madoka"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            }
                        ],
                    },
                    "expand": {
                        "mode": "character_action_group",
                        "action_group_strategy": "ordered",
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 1)
            character_nodes = [node for node in tasks[0].nodes if node.role == "character"]
            self.assertEqual([Path(node.ref).name for node in character_nodes], ["homura", "madoka"])
            self.assertTrue(tasks[0].source["auto_cp"])
            self.assertEqual(tasks[0].source["required_character_count"], 2)

    def test_character_action_group_skips_multi_character_action_without_cp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_character_node(
                root / "characters" / "homura",
                node_id="homura",
                character_id="akemi_homura",
            )
            _write_node(root / "groups" / "g1" / "a1", kind="action", node_id="a1", prompt="2girls, sitting")
            spec = BatchSpec.model_validate(
                {
                    "name": "auto-cp-skip",
                    "defaults": {"composer": "script", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [str(root / "characters" / "homura")],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            }
                        ],
                    },
                    "expand": {
                        "mode": "character_action_group",
                        "action_group_strategy": "ordered",
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(tasks, [])

    def test_character_action_group_can_fill_missing_cp_from_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_character_node(
                root / "characters" / "homura",
                node_id="homura",
                character_id="akemi_homura",
                cp=["kaname_madoka"],
            )
            _write_character_node(
                root / "characters" / "madoka",
                node_id="madoka",
                character_id="kaname_madoka",
            )
            _write_character_node(
                root / "characters" / "kyoko",
                node_id="kyoko",
                character_id="sakura_kyoko",
            )
            _write_node(root / "groups" / "g1" / "a1", kind="action", node_id="a1", prompt="3girls, sitting")
            spec = BatchSpec.model_validate(
                {
                    "name": "auto-cp-fill",
                    "defaults": {"composer": "script", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "homura"),
                                    str(root / "characters" / "madoka"),
                                    str(root / "characters" / "kyoko"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            }
                        ],
                    },
                    "expand": {
                        "mode": "character_action_group",
                        "action_group_strategy": "ordered",
                        "allow_fill_missing_cp_from_candidates": True,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 1)
            character_nodes = [node for node in tasks[0].nodes if node.role == "character"]
            self.assertEqual([Path(node.ref).name for node in character_nodes], ["homura", "madoka", "kyoko"])
            self.assertTrue(tasks[0].source["auto_cp"])
            self.assertTrue(tasks[0].source["cp_fallback_from_candidates"])
            self.assertEqual(tasks[0].source["cp_fallback_count"], 1)
            self.assertEqual(tasks[0].source["required_character_count"], 3)

    def test_folder_selector_uses_natural_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "actions" / "10_late", kind="action", node_id="a10", prompt="late")
            _write_node(root / "actions" / "2_middle", kind="action", node_id="a2", prompt="middle")
            _write_node(root / "actions" / "1_first", kind="action", node_id="a1", prompt="first")
            values = expand_selector(
                role="action",
                spec=SelectorSpec(selector="folder", root=str(root / "actions"), recursive=True),
                context=SelectorContext(base_dir=root, collections={}),
            )

            self.assertEqual([Path(value).name for value in values], ["1_first", "2_middle", "10_late"])

    def test_blackboard_rounds_runs_selected_group_actions_before_next_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="homura")
            _write_node(root / "characters" / "c2", kind="character", node_id="c2", prompt="madoka")
            _write_node(root / "groups" / "g1" / "1_a", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "groups" / "g1" / "2_a", kind="action", node_id="a2", prompt="a2")
            _write_node(root / "groups" / "g2" / "1_b", kind="action", node_id="b1", prompt="b1")
            _write_node(root / "groups" / "g2" / "2_b", kind="action", node_id="b2", prompt="b2")
            spec = BatchSpec.model_validate(
                {
                    "name": "blackboard-rounds",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "c1"),
                                    str(root / "characters" / "c2"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            },
                            {
                                "name": "g2",
                                "selector": "folder",
                                "root": str(root / "groups" / "g2"),
                                "recursive": True,
                            },
                        ],
                    },
                    "expand": {
                        "mode": "blackboard_rounds",
                        "action_group_strategy": "ordered",
                        "max_tasks": 3,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 3)
            self.assertEqual([Path(task.source["character"]).name for task in tasks], ["c1", "c1", "c2"])
            self.assertEqual([task.source["action_group"] for task in tasks], ["g1", "g1", "g2"])
            self.assertEqual([Path(task.source["action"]).name for task in tasks], ["1_a", "2_a", "1_b"])

    def test_blackboard_rounds_auto_num_runs_one_selected_group_per_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="homura")
            _write_node(root / "characters" / "c2", kind="character", node_id="c2", prompt="madoka")
            _write_node(root / "groups" / "g1" / "1_a", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "groups" / "g1" / "2_a", kind="action", node_id="a2", prompt="a2")
            _write_node(root / "groups" / "g2" / "1_b", kind="action", node_id="b1", prompt="b1")
            spec = BatchSpec.model_validate(
                {
                    "name": "blackboard-rounds-auto",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "c1"),
                                    str(root / "characters" / "c2"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            },
                            {
                                "name": "g2",
                                "selector": "folder",
                                "root": str(root / "groups" / "g2"),
                                "recursive": True,
                            },
                        ],
                    },
                    "expand": {
                        "mode": "blackboard_rounds",
                        "action_group_strategy": "ordered",
                        "auto_num": True,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 3)
            self.assertEqual([Path(task.source["character"]).name for task in tasks], ["c1", "c1", "c2"])
            self.assertEqual([task.source["action_group"] for task in tasks], ["g1", "g1", "g2"])
            self.assertEqual([Path(task.source["action"]).name for task in tasks], ["1_a", "2_a", "1_b"])
            self.assertTrue(all(task.source["auto_num"] for task in tasks))

    def test_blackboard_rounds_auto_num_respects_max_tasks_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="homura")
            _write_node(root / "characters" / "c2", kind="character", node_id="c2", prompt="madoka")
            _write_node(root / "groups" / "g1" / "1_a", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "groups" / "g1" / "2_a", kind="action", node_id="a2", prompt="a2")
            _write_node(root / "groups" / "g2" / "1_b", kind="action", node_id="b1", prompt="b1")
            spec = BatchSpec.model_validate(
                {
                    "name": "blackboard-rounds-auto-cap",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "explicit",
                                "refs": [
                                    str(root / "characters" / "c1"),
                                    str(root / "characters" / "c2"),
                                ],
                            }
                        ],
                        "action_groups": [
                            {
                                "name": "g1",
                                "selector": "folder",
                                "root": str(root / "groups" / "g1"),
                                "recursive": True,
                            },
                            {
                                "name": "g2",
                                "selector": "folder",
                                "root": str(root / "groups" / "g2"),
                                "recursive": True,
                            },
                        ],
                    },
                    "expand": {
                        "mode": "blackboard_rounds",
                        "action_group_strategy": "ordered",
                        "auto_num": True,
                        "max_tasks": 1,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(Path(tasks[0].source["character"]).name, "c1")
            self.assertEqual(tasks[0].source["action_group"], "g1")
            self.assertEqual(Path(tasks[0].source["action"]).name, "1_a")

    def test_blackboard_rounds_requires_max_tasks_or_auto_num(self):
        spec = BatchSpec.model_validate(
            {
                "name": "blackboard-rounds-invalid",
                "defaults": {"composer": "agent", "artist": "20260412"},
                "select": {
                    "characters": [{"selector": "explicit", "refs": ["character"]}],
                    "action_groups": [{"name": "g1", "selector": "explicit", "refs": ["action"]}],
                },
                "expand": {"mode": "blackboard_rounds"},
            }
        )

        with self.assertRaisesRegex(ValueError, "max_tasks or expand.auto_num"):
            BatchPlanner(base_dir=Path(".")).plan(spec)

    def test_character_action_group_random_seed_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("c1", "c2", "c3"):
                _write_node(root / "characters" / name, kind="character", node_id=name, prompt=name)
            for group_name in ("g1", "g2"):
                _write_node(
                    root / "groups" / group_name / "a1",
                    kind="action",
                    node_id=f"{group_name}_a1",
                    prompt="standing",
                )
            raw_spec = {
                "name": "character-action-random",
                "defaults": {"composer": "agent", "artist": "20260412"},
                "select": {
                    "characters": [
                        {
                            "selector": "folder",
                            "root": str(root / "characters"),
                            "recursive": True,
                        }
                    ],
                    "action_groups": [
                        {
                            "name": "g1",
                            "selector": "folder",
                            "root": str(root / "groups" / "g1"),
                            "recursive": True,
                        },
                        {
                            "name": "g2",
                            "selector": "folder",
                            "root": str(root / "groups" / "g2"),
                            "recursive": True,
                        },
                    ],
                },
                "expand": {
                    "mode": "character_action_group",
                    "action_group_strategy": "random",
                    "seed": 1234,
                },
            }

            first = BatchPlanner(base_dir=root).plan(BatchSpec.model_validate(raw_spec))
            second = BatchPlanner(base_dir=root).plan(BatchSpec.model_validate(raw_spec))

            self.assertEqual(
                [task.source["action_group"] for task in first],
                [task.source["action_group"] for task in second],
            )

    def test_character_action_group_balanced_random_updates_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_path = root / "cache" / "action_group_record.json"
            record_path.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.action-group-record/v1",
                        "groups": {
                            "g1": {"selected_count": 2},
                            "g2": {"selected_count": 0},
                            "g3": {"selected_count": 0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            for name in ("c1", "c2"):
                _write_node(root / "characters" / name, kind="character", node_id=name, prompt=name)
            for group_name in ("g1", "g2", "g3"):
                _write_node(
                    root / "groups" / group_name / "a1",
                    kind="action",
                    node_id=f"{group_name}_a1",
                    prompt="standing",
                )
            spec = BatchSpec.model_validate(
                {
                    "name": "character-action-balanced",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "folder",
                                "root": str(root / "characters"),
                                "recursive": True,
                            }
                        ],
                        "action_groups": [
                            {
                                "name": group_name,
                                "selector": "folder",
                                "root": str(root / "groups" / group_name),
                                "recursive": True,
                            }
                            for group_name in ("g1", "g2", "g3")
                        ],
                    },
                    "expand": {
                        "mode": "character_action_group",
                        "action_group_strategy": "balanced_random",
                        "action_group_record": str(record_path),
                        "seed": 7,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec)
            record = json.loads(record_path.read_text(encoding="utf-8"))

            self.assertEqual(sorted(task.source["action_group"] for task in tasks), ["g2", "g3"])
            self.assertEqual(record["groups"]["g1"]["selected_count"], 2)
            self.assertEqual(record["groups"]["g2"]["selected_count"], 0)
            self.assertEqual(record["groups"]["g3"]["selected_count"], 0)

    def test_character_action_group_rejects_select_actions(self):
        spec = BatchSpec.model_validate(
            {
                "name": "bad-mixed-actions",
                "defaults": {"composer": "agent", "artist": "20260412"},
                "select": {
                    "characters": [{"selector": "explicit", "refs": ["character"]}],
                    "actions": [{"selector": "explicit", "refs": ["action"]}],
                    "action_groups": [
                        {"name": "group", "selector": "explicit", "refs": ["action"]}
                    ],
                },
                "expand": {"mode": "character_action_group"},
            }
        )

        with self.assertRaisesRegex(ValueError, "does not allow select.actions"):
            BatchPlanner(base_dir=Path(".")).plan(spec)

    def test_non_character_action_group_rejects_action_groups(self):
        spec = BatchSpec.model_validate(
            {
                "name": "bad-action-groups",
                "defaults": {"composer": "agent", "artist": "20260412"},
                "select": {
                    "action_groups": [
                        {"name": "group", "selector": "explicit", "refs": ["action"]}
                    ]
                },
                "expand": {"mode": "product"},
            }
        )

        with self.assertRaisesRegex(ValueError, "only supported"):
            BatchPlanner(base_dir=Path(".")).plan(spec)

    def test_cli_plan_batch_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "batch.yaml"
            output_dir = (root / "custom_outputs").as_posix()
            spec_path.write_text(
                f"""
schema: tags-machine-core.batch/v1
name: cli-plan
output_dir: {output_dir}
defaults:
  artist: 20260412
select:
  prompts:
    - selector: prompt_list
      items:
        - id: p1
          prompt: akemi_homura, standing
expand:
  mode: prompt_list
""".strip(),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["plan-batch", str(spec_path), "--full"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["task_count"], 1)
            self.assertEqual(len(data["run_id"]), 8)
            self.assertEqual(data["selector_summary"]["prompts"], 1)
            self.assertTrue(Path(data["manifest_path"]).exists())
            self.assertEqual(Path(data["run_dir"]), root / "cli-plan")
            self.assertEqual(Path(data["output_dir"]).resolve(), (root / "custom_outputs").resolve())
            source = json.loads((Path(data["run_dir"]) / "batch_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["run_id"], data["run_id"])
            self.assertEqual(Path(source["output_dir"]).resolve(), (root / "custom_outputs").resolve())

    def test_cli_plan_batch_does_not_delete_run_dir_when_spec_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "batch.yaml"
            run_dir = root / "preview-fresh"
            stale = run_dir / "keep.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("keep", encoding="utf-8")
            spec_path.write_text(
                """
schema: tags-machine-core.batch/v1
name: preview-fresh
select:
  prompts:
    - selector: prompt_list
      items:
        - id: p1
          prompt: akemi_homura, standing
expand:
  mode: prompt_list
run:
  fresh: true
""".strip(),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                exit_code = main(["plan-batch", str(spec_path), "--full"])

            self.assertEqual(exit_code, 0)
            self.assertTrue(stale.exists())

    def test_cli_run_batch_fresh_preserves_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "batch.yaml"
            run_dir = root / "run-fresh"
            stale = run_dir / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("remove", encoding="utf-8")
            spec_path.write_text(
                """
schema: tags-machine-core.batch/v1
name: run-fresh
defaults:
  composer: full
select:
  prompts:
    - selector: prompt_list
      items:
        - id: p1
          prompt: akemi_homura, standing
expand:
  mode: prompt_list
""".strip(),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    ["run-batch", str(spec_path), "--mock-client", "--fresh", "--limit", "1"]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(stale.exists())
            self.assertTrue((run_dir / "batch_source.json").exists())
            self.assertTrue((run_dir / "batch.yaml").exists())

    def test_planner_accepts_separate_work_and_output_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = BatchSpec.model_validate(
                {
                    "name": "split-dirs",
                    "output_dir": str(root / "images"),
                    "defaults": {"artist": "20260412", "resolution": "square"},
                    "select": {
                        "prompts": [
                            {
                                "selector": "prompt_list",
                                "items": [{"id": "p1", "prompt": "akemi_homura"}],
                            }
                        ]
                    },
                    "expand": {"mode": "prompt_list"},
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec, run_dir=root / "work")

            self.assertEqual(Path(tasks[0].output.task_dir).parent.parent, root / "work")
            self.assertEqual(Path(tasks[0].output.output_dir).parent.resolve(), (root / "images").resolve())
            self.assertEqual(tasks[0].render.output_dir, tasks[0].output.output_dir)

    def test_api_plan_batch_accepts_inline_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "spec": {
                            "schema": "tags-machine-core.batch/v1",
                            "name": "api-plan",
                            "output_root": str(root / "outputs"),
                            "defaults": {"artist": "20260412"},
                            "select": {
                                "prompts": [
                                    {
                                        "selector": "prompt_list",
                                        "items": [
                                            {
                                                "id": "p1",
                                                "prompt": "akemi_homura, standing",
                                            }
                                        ],
                                    }
                                ]
                            },
                            "expand": {"mode": "prompt_list"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["api-plan-batch", str(request_path), "--full"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["schema"], "tags-machine-core.api-plan-batch-result/v1")
            self.assertEqual(data["task_count"], 1)
            self.assertEqual(data["selector_summary"]["artists"], {"20260412": 1})
            self.assertTrue(Path(data["manifest_path"]).exists())

    def test_runner_fresh_clears_existing_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            stale = run_dir / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")
            task = BatchTask(
                id="fresh_task",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(run_dir / "tasks" / "fresh_task"),
                    "output_dir": str(run_dir / "outputs" / "fresh_task"),
                },
            )

            result = BatchRunner(executor=SuccessfulExecutor()).run_tasks(
                run_dir=run_dir,
                tasks=[task],
                config=_config(root),
                run_config=RunConfig(fresh=True),
            )

            self.assertEqual(result["counts"], {"succeeded": 1})
            self.assertFalse(stale.exists())
            self.assertTrue((run_dir / "tasks" / "fresh_task" / "task.json").exists())
            self.assertTrue((run_dir / "outputs" / "fresh_task").exists())

    def test_runner_records_requires_agent_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="agent_task",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "agent_task"),
                    "output_dir": str(root / "run" / "outputs" / "agent_task"),
                },
            )
            runner = BatchRunner(executor=FakeExecutor())

            result = runner.run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
                limit=1,
            )

            self.assertEqual(result["counts"], {"requires_agent": 1})
            self.assertEqual(runner.executor.calls, 1)
            self.assertTrue((root / "run" / "agent_tasks" / "agent_task.json").exists())

    def test_runner_clamps_task_nt_to_remaining_image_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="budget_task",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412", nt=3),
                output={
                    "task_dir": str(root / "run" / "tasks" / "budget_task"),
                    "output_dir": str(root / "run" / "outputs" / "budget_task"),
                },
            )
            executor = FakeExecutor()

            BatchRunner(executor=executor).run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
                run_config=RunConfig(max_images=1),
            )

            self.assertEqual(executor.tasks[0].render.nt, 1)

    def test_runner_resume_uses_existing_task_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planned = BatchTask(
                id="resume_task",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412", width=1024, height=1024),
                output={
                    "task_dir": str(root / "run" / "tasks" / "resume_task"),
                    "output_dir": str(root / "run" / "outputs" / "resume_task"),
                },
            )
            archived = planned.model_copy(
                deep=True,
                update={"render": planned.render.model_copy(update={"width": 832, "height": 1216})},
            )
            BatchArchive().write_task(archived)
            executor = FakeExecutor()

            BatchRunner(executor=executor).run_tasks(
                run_dir=root / "run",
                tasks=[planned],
                config=_config(root),
                run_config=RunConfig(resume=True),
            )

            self.assertEqual(executor.tasks[0].render.width, 832)
            self.assertEqual(executor.tasks[0].render.height, 1216)

    def test_runner_fails_success_without_png_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="no_png_info",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "no_png_info"),
                    "output_dir": str(root / "run" / "outputs" / "no_png_info"),
                },
            )

            result = BatchRunner(executor=SuccessfulExecutor(png_info={})).run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
            )

            self.assertEqual(result["counts"], {"failed": 1})
            self.assertIn("PNG parameter", result["entries"][0]["error"])

    def test_runner_stop_on_error_stops_after_first_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = [
                BatchTask(
                    id=f"failed_{index}",
                    index=index,
                    composer="agent",
                    nodes=[],
                    render=RenderOptions(artist="20260412"),
                    output={
                        "task_dir": str(root / "run" / "tasks" / f"failed_{index}"),
                        "output_dir": str(root / "run" / "outputs" / f"failed_{index}"),
                    },
                )
                for index in range(2)
            ]
            executor = FakeExecutor(status="failed")

            result = BatchRunner(executor=executor).run_tasks(
                run_dir=root / "run",
                tasks=tasks,
                config=_config(root),
                run_config=RunConfig(stop_on_error=True),
            )

            self.assertEqual(result["counts"], {"failed": 1})
            self.assertEqual(executor.calls, 1)

    def test_runner_resume_skip_does_not_overwrite_succeeded_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="done",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "done"),
                    "output_dir": str(root / "run" / "outputs" / "done"),
                },
            )
            write_initial_manifest(root / "run", [task])
            status_path = Path(task.output.task_dir) / "status.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps({"status": "succeeded", "attempt": 1}),
                encoding="utf-8",
            )
            fake = FakeExecutor(status="failed")

            result = BatchRunner(executor=fake).run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
            )

            self.assertEqual(result["counts"], {"skipped": 1})
            self.assertEqual(fake.calls, 0)
            self.assertEqual(json.loads(status_path.read_text(encoding="utf-8"))["status"], "succeeded")

    def test_cli_inspect_batch_reconciles_status_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="done",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "done"),
                    "output_dir": str(root / "run" / "outputs" / "done"),
                },
            )
            write_initial_manifest(root / "run", [task])
            status_path = Path(task.output.task_dir) / "status.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps({"status": "succeeded", "attempt": 1, "image_paths": ["image.png"]}),
                encoding="utf-8",
            )
            output_dir = root / "run" / "outputs" / "done"
            output_dir.mkdir(parents=True)
            generation_result_path = output_dir / "generation_result.json"
            generation_result_path.write_text(
                json.dumps({"schema": "tags-machine-core.generation-result/v1"}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["inspect-batch", str(root / "run"), "--full"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["counts"], {"succeeded": 1})
            self.assertEqual(data["tasks"][0]["image_paths"], ["image.png"])
            self.assertEqual(
                data["tasks"][0]["generation_result_path"].replace("\\", "/"),
                "outputs/done/generation_result.json",
            )

    def test_status_json_records_render_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="status_render",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412", width=832, height=1216, nt=1),
                output={
                    "task_dir": str(root / "run" / "tasks" / "status_render"),
                    "output_dir": str(root / "run" / "outputs" / "status_render"),
                },
            )

            BatchArchive().write_status(task, status="running", attempt=1)

            data = json.loads((Path(task.output.task_dir) / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(data["render"]["width"], 832)
            self.assertEqual(data["render"]["height"], 1216)

    def test_copy_images_archives_images_inside_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"png")
            task = BatchTask(
                id="copy_task",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "copy_task"),
                    "output_dir": str(root / "run" / "outputs" / "copy_task"),
                },
            )
            result = GenerationResult(
                backend="novelai",
                images=[GeneratedImage(path=source, filename="source.png")],
                png_info={"images": [{"parameters": {"seed": 1}}]},
            )

            archived = BatchArchive(ArchiveConfig(copy_images=True)).archive_success(
                task=task,
                prompt_bundle={"prompt": {"positive": "akemi_homura", "negative": ""}},
                render_request={"backend": "novelai", "prompt": "akemi_homura"},
                generation_result=result,
            )

            self.assertEqual(archived.images[0].path.parent.name, "copy_task")
            self.assertEqual(archived.images[0].filename, "source.png")
            self.assertEqual(archived.images[0].path.read_bytes(), b"png")

    def test_archive_creates_parameter_details_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"png")
            task = BatchTask(
                id="param_img_task",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "param_img_task"),
                    "output_dir": str(root / "run" / "outputs" / "param_img_task"),
                },
            )
            result = GenerationResult(
                backend="novelai",
                images=[GeneratedImage(path=source, filename="source.png")],
                png_info={"images": [{"parameters": {"seed": 1, "steps": 28}}]},
                request_body={"parameters": {"n_samples": task.render.nt, "seed": 1}},
            )

            BatchArchive(ArchiveConfig(save_parameter_image=True)).archive_success(
                task=task,
                prompt_bundle={"prompt": {"positive": "akemi_homura", "negative": ""}},
                render_request={"backend": "novelai", "prompt": "akemi_homura"},
                generation_result=result,
            )

            image_path = Path(task.output.output_dir) / f"zz_{task.id}_parameter_details.png"
            self.assertTrue(image_path.exists())
            self.assertTrue(image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            from PIL import Image

            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1400, 1500))

    def test_archive_parameter_details_image_keeps_fixed_size_for_long_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"png")
            long_prompt = ", ".join([f"tag_{index}" for index in range(800)])
            task = BatchTask(
                id="long_param_img_task",
                index=0,
                composer="full",
                prompt=long_prompt,
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "long_param_img_task"),
                    "output_dir": str(root / "run" / "outputs" / "long_param_img_task"),
                },
            )
            result = GenerationResult(
                backend="novelai",
                images=[GeneratedImage(path=source, filename="source.png")],
                png_info={"images": [{"parameters": {"seed": 1, "prompt": long_prompt}}]},
                request_body={"parameters": {"n_samples": task.render.nt, "seed": 1, "prompt": long_prompt}},
            )

            BatchArchive(ArchiveConfig(save_parameter_image=True)).archive_success(
                task=task,
                prompt_bundle={"prompt": {"positive": long_prompt, "negative": ""}},
                render_request={"backend": "novelai", "prompt": long_prompt},
                generation_result=result,
            )

            image_path = Path(task.output.output_dir) / f"zz_{task.id}_parameter_details.png"
            from PIL import Image

            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1400, 1500))

    def test_parameter_details_uses_actual_png_parameters_for_split_generation(self):
        from tags_machine_core.batch.parameter_image import (
            _display_parameters,
            _parameter_lines,
            _prompt_negative,
            _prompt_positive,
        )

        bundle = {"prompt": {"positive": "bundle prompt", "negative": "bundle negative"}}
        request = {
            "prompt": "request prompt",
            "negative_prompt": "request negative",
            "params": {"seed": 999, "n_samples": 3},
        }
        result = {
            "request_body": {"parameters": {"seed": 999, "n_samples": 3}},
            "png_info": {
                "images": [
                    {
                        "parameters": {
                            "seed": 101,
                            "n_samples": 1,
                            "prompt": "actual prompt",
                            "uc": "actual negative",
                            "width": 1216,
                            "height": 832,
                        }
                    },
                    {
                        "parameters": {
                            "seed": 102,
                            "n_samples": 1,
                            "prompt": "actual prompt",
                            "uc": "actual negative",
                            "width": 1216,
                            "height": 832,
                        }
                    },
                ]
            },
        }

        params = _display_parameters(request=request, result=result)

        self.assertEqual(params["seed"], [101, 102])
        self.assertEqual(params["n_samples"], 1)
        self.assertEqual(params["_actual_image_count"], 2)
        self.assertEqual(_prompt_positive(bundle=bundle, request=request, params=params), "actual prompt")
        self.assertEqual(_prompt_negative(bundle=bundle, request=request, params=params), "actual negative")

        params["characterPrompts"] = [
            {"prompt": "girl, akemi_homura, black_hair", "uc": "red_glasses"},
            {"prompt": "boy, ", "uc": ""},
        ]
        lines = _parameter_lines(params=params, request=request)

        self.assertEqual(lines[0], "characterPrompts: 2")
        self.assertIn("1. prompt: girl, akemi_homura, black_hair", lines)
        self.assertIn("   uc: red_glasses", lines)
        self.assertIn("2. prompt: boy, ", lines)
        self.assertFalse(any(line.startswith("seed:") for line in lines))
        self.assertFalse(any(line.startswith("steps:") for line in lines))

    def test_parameter_details_extracts_v4_character_prompts(self):
        from tags_machine_core.batch.parameter_image import _parameter_lines

        params = {
            "seed": 101,
            "steps": 28,
            "v4_prompt": {
                "caption": {
                    "char_captions": [
                        {"char_caption": "girl, akemi_homura"},
                        {"char_caption": "boy, "},
                    ]
                }
            },
            "v4_negative_prompt": {
                "caption": {
                    "char_captions": [
                        {"char_caption": "red_glasses"},
                        {"char_caption": ""},
                    ]
                }
            },
        }

        lines = _parameter_lines(params=params, request={})

        self.assertEqual(lines[0], "characterPrompts: 2")
        self.assertIn("1. prompt: girl, akemi_homura", lines)
        self.assertIn("   uc: red_glasses", lines)
        self.assertIn("2. prompt: boy, ", lines)
        self.assertFalse(any(line.startswith("seed:") for line in lines))

    def test_archive_parameter_details_image_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"png")
            task = BatchTask(
                id="param_img_disabled_task",
                index=0,
                composer="full",
                prompt="akemi_homura",
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "param_img_disabled_task"),
                    "output_dir": str(root / "run" / "outputs" / "param_img_disabled_task"),
                },
            )
            result = GenerationResult(
                backend="novelai",
                images=[GeneratedImage(path=source, filename="source.png")],
                png_info={"images": [{"parameters": {"seed": 1}}]},
            )

            BatchArchive(ArchiveConfig()).archive_success(
                task=task,
                prompt_bundle={"prompt": {"positive": "akemi_homura", "negative": ""}},
                render_request={"backend": "novelai", "prompt": "akemi_homura"},
                generation_result=result,
            )

            image_path = Path(task.output.output_dir) / f"zz_{task.id}_parameter_details.png"
            self.assertFalse(image_path.exists())

    def test_report_includes_retry_records_without_prompt_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_report(
                root,
                [
                    {
                        "task_id": "retry_task",
                        "status": "failed",
                        "image_paths": [],
                        "error": "502 bad gateway",
                        "retry_records": [
                            {
                                "attempt": 1,
                                "error": "502 bad gateway",
                                "retryable": False,
                            }
                        ],
                    }
                ],
            )

            self.assertIn("retry:", (root / "report.md").read_text(encoding="utf-8"))

    def test_report_includes_action_group_source_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_report(
                root,
                [
                    {
                        "task_id": "group_task",
                        "status": "succeeded",
                        "image_paths": ["image.png"],
                        "source": {
                            "character": str(root / "characters" / "c1"),
                            "action_group": "st_rp",
                            "action": str(root / "actions" / "a1"),
                            "artist": "20260412",
                        },
                    }
                ],
            )

            report_md = (root / "report.md").read_text(encoding="utf-8")
            report_json = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertIn("action_group=st_rp", report_md)
            self.assertEqual(report_json["entries"][0]["source"]["action_group"], "st_rp")

    def test_report_respects_prompt_png_and_visual_template_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_report(
                root,
                [
                    {
                        "task_id": "done",
                        "status": "succeeded",
                        "image_paths": ["image.png"],
                        "prompt_preview": "akemi_homura",
                        "png_params_summary": {"has_png_info": True},
                    }
                ],
                include_prompt_preview=False,
                include_png_params_summary=False,
                visual_check_template=False,
            )

            report_md = (root / "report.md").read_text(encoding="utf-8")
            report_json = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertNotIn("akemi_homura", report_md)
            self.assertNotIn("Visual Result", report_md)
            self.assertNotIn("prompt_preview", report_json["entries"][0])
            self.assertNotIn("png_params_summary", report_json["entries"][0])

    def test_executor_reads_agent_result_file_for_agent_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character = NodeDocument(kind="character", id="homura", tags={"default": ["akemi homura"]})
            action = NodeDocument(kind="action", id="standing", tags={"default": ["standing"]})
            resolved = ResolvedNodeSet(
                [
                    ResolvedNode(role="character", ref="homura", index=0, node=character),
                    ResolvedNode(role="action", ref="standing", index=0, node=action),
                ]
            )
            task = BatchTask(
                id="agent_ready",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412"),
                output={
                    "task_dir": str(root / "run" / "tasks" / "agent_ready"),
                    "output_dir": str(root / "run" / "outputs" / "agent_ready"),
                },
            )
            result_dir = root / "run" / "agent_results"
            result_dir.mkdir(parents=True)
            (result_dir / "agent_ready.json").write_text(
                json.dumps({"positive": "akemi homura, standing", "negative": "bad anatomy"}),
                encoding="utf-8",
            )

            bundle = BatchExecutor()._compose(task, resolved)

            self.assertEqual(bundle.prompt.positive, "akemi homura, standing")
            self.assertEqual(bundle.prompt.negative, "bad anatomy")

    def test_executor_uses_agent_cache_hit_after_result_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character = NodeDocument(kind="character", id="homura", tags={"default": ["akemi homura"]})
            action = NodeDocument(kind="action", id="standing", tags={"default": ["standing"]})
            resolved = ResolvedNodeSet(
                [
                    ResolvedNode(role="character", ref="homura", index=0, node=character),
                    ResolvedNode(role="action", ref="standing", index=0, node=action),
                ]
            )
            task = BatchTask(
                id="agent_cached",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412"),
                agent={"cache_dir": str(root / "cache")},
                output={
                    "task_dir": str(root / "run" / "tasks" / "agent_cached"),
                    "output_dir": str(root / "run" / "outputs" / "agent_cached"),
                },
            )
            result_dir = root / "run" / "agent_results"
            result_dir.mkdir(parents=True)
            result_path = result_dir / "agent_cached.json"
            result_path.write_text(
                json.dumps({"positive": "akemi homura, standing", "negative": "bad anatomy"}),
                encoding="utf-8",
            )
            executor = BatchExecutor()

            first = executor._compose(task, resolved)
            result_path.unlink()
            second = executor._compose(task, resolved)

            self.assertFalse(first.cache.cache_hit)
            self.assertTrue(second.cache.cache_hit)
            self.assertEqual(second.prompt.positive, "akemi homura, standing")

    def test_runner_retries_retryable_errors_and_applies_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="retry_task",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412"),
                output={"task_dir": str(root / "run" / "tasks" / "retry_task")},
            )
            executor = FlakyExecutor()

            result = BatchRunner(executor=executor).run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
                run_config=RunConfig(
                    retry=RetryConfig(
                        max_attempts=2,
                        timeout_seconds=1,
                        retry_on=["502"],
                        backoff_seconds=[0],
                    )
                ),
            )

            self.assertEqual(result["counts"], {"requires_agent": 1})
            self.assertEqual(executor.calls, 2)
            self.assertEqual(executor.timeouts, [1, 1])
            self.assertEqual(result["entries"][0]["retry_records"][0]["attempt"], 1)


class ActionGroupRoundSelectionTests(unittest.TestCase):
    def test_expand_config_rejects_non_positive_actions_per_group(self):
        with self.assertRaisesRegex(ValueError, "actions_per_group must be >= 1"):
            ExpandConfig(actions_per_group=0)

    def test_random_preserve_order_samples_then_restores_source_order(self):
        group = ResolvedActionGroup(name="g1", actions=["a1", "a2", "a3", "a4"])

        selected = select_group_actions(
            group,
            strategy="random_preserve_order",
            limit=2,
            rng=random.Random(7),
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual(selected, sorted(selected, key=group.actions.index))

    def test_all_selection_respects_limit_without_shuffle(self):
        group = ResolvedActionGroup(name="g1", actions=["a1", "a2", "a3"])

        selected = select_group_actions(
            group,
            strategy="all",
            limit=2,
            rng=random.Random(1),
        )

        self.assertEqual(selected, ["a1", "a2"])

    def test_action_group_collection_preserves_matched_folder_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "actions"
            _write_node(root / "pn_a" / "01", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "pn_a" / "02", kind="action", node_id="a2", prompt="a2")
            _write_node(root / "pn_b" / "01", kind="action", node_id="b1", prompt="b1")
            context = SelectorContext(
                base_dir=Path(tmp),
                collections={
                    "actions": {
                        "action_new": [
                            {
                                "selector": "folder",
                                "root": str(root),
                                "include": {"names": ["pn_*"]},
                            }
                        ]
                    }
                },
            )

            groups = resolve_action_groups(
                [SelectorSpec(selector="collection", name="action_new")],
                context=context,
            )

            self.assertEqual([group.name for group in groups], ["pn_a", "pn_b"])
            self.assertEqual([len(group.actions) for group in groups], [2, 1])

    def test_ordinary_action_collection_remains_flat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "actions"
            _write_node(root / "pn_a" / "01", kind="action", node_id="a1", prompt="a1")
            _write_node(root / "pn_a" / "02", kind="action", node_id="a2", prompt="a2")
            _write_node(root / "pn_b" / "01", kind="action", node_id="b1", prompt="b1")
            context = SelectorContext(
                base_dir=Path(tmp),
                collections={
                    "actions": {
                        "action_new": [
                            {
                                "selector": "folder",
                                "root": str(root),
                                "include": {"names": ["pn_*"]},
                            }
                        ]
                    }
                },
            )

            actions = expand_selector(
                role="action",
                spec=SelectorSpec(selector="collection", name="action_new"),
                context=context,
            )

            self.assertEqual(len(actions), 3)

    def test_action_group_state_defaults_under_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ActionGroupStateStore.for_run_dir(Path(tmp) / "run")

            self.assertEqual(
                store.path,
                Path(tmp) / "run" / "state" / "action_groups.json",
            )

    def test_mark_round_started_is_idempotent(self):
        record = ActionGroupRecord()

        self.assertTrue(mark_round_started(record, round_id="r1", group_name="g1"))
        self.assertFalse(mark_round_started(record, round_id="r1", group_name="g1"))
        self.assertEqual(record.groups["g1"].selected_count, 1)

    def test_planning_baseline_rolls_back_rounds_from_current_run(self):
        record = ActionGroupRecord()
        mark_round_started(record, round_id="r1", group_name="g1")

        baseline = record.planning_baseline()

        self.assertEqual(baseline.groups["g1"].selected_count, 0)
        self.assertEqual(baseline.recorded_rounds, {})
        self.assertEqual(record.groups["g1"].selected_count, 1)

    def test_failed_round_can_recover_to_completed(self):
        record = ActionGroupRecord()
        mark_round_started(record, round_id="r1", group_name="g1")
        mark_round_finished(record, round_id="r1", status="failed")

        self.assertTrue(mark_round_finished(record, round_id="r1", status="completed"))

        self.assertEqual(record.recorded_rounds["r1"].status, "completed")
        self.assertEqual(record.groups["g1"].failed_count, 0)
        self.assertEqual(record.groups["g1"].completed_count, 1)

    def test_state_store_round_trip_preserves_recorded_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ActionGroupStateStore.for_run_dir(Path(tmp) / "run")
            record = ActionGroupRecord()
            mark_round_started(record, round_id="r1", group_name="g1")

            store.save(record)
            loaded = store.load()

            self.assertEqual(loaded.recorded_rounds["r1"].group, "g1")
            self.assertEqual(loaded.groups["g1"].selected_count, 1)

    def test_blackboard_rounds_samples_three_actions_then_switches_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for character in ("c1", "c2"):
                _write_node(
                    root / "characters" / character,
                    kind="character",
                    node_id=character,
                    prompt=character,
                )
            for group in ("g1", "g2"):
                for index in range(5):
                    _write_node(
                        root / "groups" / group / f"a{index}",
                        kind="action",
                        node_id=f"{group}_a{index}",
                        prompt="standing",
                    )
            spec = BatchSpec.model_validate(
                {
                    "name": "sampled-rounds",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {
                                "selector": "folder",
                                "root": str(root / "characters"),
                                "recursive": True,
                            }
                        ],
                        "action_groups": [
                            {
                                "name": group,
                                "selector": "folder",
                                "root": str(root / "groups" / group),
                                "recursive": True,
                            }
                            for group in ("g1", "g2")
                        ],
                    },
                    "expand": {
                        "mode": "blackboard_rounds",
                        "max_tasks": 6,
                        "action_group_strategy": "ordered",
                        "actions_per_group": 3,
                        "action_selection": "random_preserve_order",
                        "seed": 7,
                    },
                }
            )

            tasks = BatchPlanner(base_dir=root).plan(spec, run_dir=root / "run", run_id="sample")

            self.assertEqual(len(tasks), 6)
            self.assertEqual(len({task.source["round_id"] for task in tasks[:3]}), 1)
            self.assertEqual(len({task.source["round_id"] for task in tasks[3:]}), 1)
            self.assertEqual({Path(task.source["character"]).name for task in tasks[:3]}, {"c1"})
            self.assertEqual({Path(task.source["character"]).name for task in tasks[3:]}, {"c2"})
            self.assertEqual([task.source["action_group"] for task in tasks], ["g1"] * 3 + ["g2"] * 3)
            self.assertEqual([task.source["action_index_in_group"] for task in tasks], [0, 1, 2, 0, 1, 2])

    def test_blackboard_resume_rebuilds_same_plan_from_run_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            _write_node(root / "characters" / "c1", kind="character", node_id="c1", prompt="c1")
            for group in ("g1", "g2"):
                _write_node(
                    root / "groups" / group / "a1",
                    kind="action",
                    node_id=f"{group}_a1",
                    prompt="standing",
                )
            spec = BatchSpec.model_validate(
                {
                    "name": "resume-rounds",
                    "defaults": {"composer": "agent", "artist": "20260412"},
                    "select": {
                        "characters": [
                            {"selector": "folder", "root": str(root / "characters"), "recursive": True}
                        ],
                        "action_groups": [
                            {
                                "name": group,
                                "selector": "folder",
                                "root": str(root / "groups" / group),
                                "recursive": True,
                            }
                            for group in ("g1", "g2")
                        ],
                    },
                    "expand": {
                        "mode": "blackboard_rounds",
                        "max_tasks": 1,
                        "action_group_strategy": "balanced_random",
                    },
                }
            )
            planner = BatchPlanner(base_dir=root)
            first = planner.plan(spec, run_dir=run_dir, run_id="stable-run")
            state = ActionGroupRecord()
            mark_round_started(
                state,
                round_id=first[0].source["round_id"],
                group_name=first[0].source["action_group"],
            )
            ActionGroupStateStore.for_run_dir(run_dir).save(state)

            resumed = planner.plan(spec, run_dir=run_dir, run_id="stable-run")

            self.assertEqual([task.id for task in resumed], [task.id for task in first])
            self.assertEqual(
                [task.source["action_group"] for task in resumed],
                [task.source["action_group"] for task in first],
            )

    def test_runner_records_one_completed_round_for_three_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            tasks = [
                BatchTask(
                    id=f"round_task_{index}",
                    index=index,
                    composer="full",
                    prompt="akemi_homura",
                    render=RenderOptions(artist="20260412"),
                    output={
                        "task_dir": str(run_dir / "tasks" / f"round_task_{index}"),
                        "output_dir": str(run_dir / "outputs" / f"round_task_{index}"),
                    },
                    source={
                        "round_id": "r1",
                        "action_group": "g1",
                        "character": "homura",
                    },
                )
                for index in range(3)
            ]

            BatchRunner(executor=SuccessfulExecutor()).run_tasks(
                run_dir=run_dir,
                tasks=tasks,
                config=_config(root),
                run_config=RunConfig(fresh=True),
            )
            state = ActionGroupStateStore.for_run_dir(run_dir).load()

            self.assertEqual(state.groups["g1"].selected_count, 1)
            self.assertEqual(state.groups["g1"].completed_count, 1)
            self.assertEqual(state.recorded_rounds["r1"].status, "completed")
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["action_groups"]["rounds"], 1)

            BatchRunner(executor=SuccessfulExecutor()).run_tasks(
                run_dir=run_dir,
                tasks=tasks,
                config=_config(root),
                run_config=RunConfig(resume=True),
            )
            resumed = ActionGroupStateStore.for_run_dir(run_dir).load()
            self.assertEqual(resumed.groups["g1"].selected_count, 1)
            self.assertEqual(resumed.groups["g1"].completed_count, 1)


def _config(root: Path) -> AppConfig:
    legacy = root / "legacy"
    design = legacy / "design"
    design.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        legacy=LegacyConfig(tags_machine_root=legacy, design_root=design),
    )


if __name__ == "__main__":
    unittest.main()
