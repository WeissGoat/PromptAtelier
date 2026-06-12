import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.batch import BatchPlanner, BatchRunner, load_batch_spec
from tags_machine_core.batch.executor import BatchExecutor
from tags_machine_core.batch.executor import BatchExecutionResult
from tags_machine_core.batch.manifest import write_initial_manifest
from tags_machine_core.batch.models import BatchSpec, BatchTask, RenderOptions, RetryConfig, RunConfig
from tags_machine_core.cli import main
from tags_machine_core.config import AppConfig, LegacyConfig
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

    def execute(self, task, *, config, output_dir=None):
        self.calls += 1
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


def _config(root: Path) -> AppConfig:
    legacy = root / "legacy"
    design = legacy / "design"
    design.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        legacy=LegacyConfig(tags_machine_root=legacy, design_root=design),
    )


if __name__ == "__main__":
    unittest.main()
