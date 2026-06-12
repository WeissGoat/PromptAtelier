import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.batch import (
    ArchiveConfig,
    BatchArchive,
    BatchPlanner,
    BatchRunner,
    SelectorContext,
    SelectorSpec,
    expand_selector,
    load_batch_spec,
)
from tags_machine_core.batch.executor import BatchExecutor
from tags_machine_core.batch.executor import BatchExecutionResult
from tags_machine_core.batch.manifest import write_initial_manifest
from tags_machine_core.batch.models import BatchSpec, BatchTask, RenderOptions, RetryConfig, RunConfig
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

    def test_cli_plan_batch_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "batch.yaml"
            output_root = (root / "outputs").as_posix()
            spec_path.write_text(
                f"""
schema: tags-machine-core.batch/v1
name: cli-plan
output_root: {output_root}
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
            self.assertEqual(data["run_id"], "cli-plan")
            self.assertEqual(data["selector_summary"]["prompts"], 1)
            self.assertTrue(Path(data["manifest_path"]).exists())

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

    def test_runner_records_requires_agent_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="agent_task",
                index=0,
                composer="agent",
                nodes=[],
                render=RenderOptions(artist="20260412"),
                output={"task_dir": str(root / "run" / "tasks" / "agent_task")},
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
                output={"task_dir": str(root / "run" / "tasks" / "budget_task")},
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
                output={"task_dir": str(root / "run" / "tasks" / "resume_task")},
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
                output={"task_dir": str(root / "run" / "tasks" / "no_png_info")},
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
                    output={"task_dir": str(root / "run" / "tasks" / f"failed_{index}")},
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
                output={"task_dir": str(root / "run" / "tasks" / "done")},
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
                output={"task_dir": str(root / "run" / "tasks" / "done")},
            )
            write_initial_manifest(root / "run", [task])
            status_path = Path(task.output.task_dir) / "status.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps({"status": "succeeded", "attempt": 1, "image_paths": ["image.png"]}),
                encoding="utf-8",
            )
            generation_result_path = status_path.parent / "generation_result.json"
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
                "tasks/done/generation_result.json",
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
                output={"task_dir": str(root / "run" / "tasks" / "status_render")},
            )

            BatchArchive().write_status(task, status="running", attempt=1)

            data = json.loads((Path(task.output.task_dir) / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(data["render"]["width"], 832)
            self.assertEqual(data["render"]["height"], 1216)

    def test_copy_images_archives_images_inside_task_dir(self):
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
                output={"task_dir": str(root / "run" / "tasks" / "copy_task")},
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

            self.assertEqual(archived.images[0].path.parent.name, "images")
            self.assertEqual(archived.images[0].filename, "source.png")
            self.assertEqual(archived.images[0].path.read_bytes(), b"png")

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
                output={"task_dir": str(root / "run" / "tasks" / "agent_ready")},
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


def _config(root: Path) -> AppConfig:
    legacy = root / "legacy"
    design = legacy / "design"
    design.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        legacy=LegacyConfig(tags_machine_root=legacy, design_root=design),
    )


if __name__ == "__main__":
    unittest.main()
