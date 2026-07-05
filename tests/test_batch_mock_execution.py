import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.batch import BatchRunner
from tags_machine_core.batch.models import BatchTask, RenderOptions, RunConfig
from tags_machine_core.config import AppConfig, LegacyConfig


class BatchMockExecutionTest(unittest.TestCase):
    def test_runner_mock_execution_archives_final_payload_without_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = BatchTask(
                id="mock_payload",
                index=0,
                composer="full",
                prompt="akemi homura, standing",
                render=RenderOptions(
                    backend="novelai",
                    width=832,
                    height=1216,
                    nt=2,
                    seed=12345,
                    params={"sampler": "k_euler_ancestral", "steps": 28, "scale": 5.0},
                ),
                output={
                    "task_dir": str(root / "run" / "tasks" / "mock_payload"),
                    "output_dir": str(root / "run" / "outputs" / "mock_payload"),
                },
            )

            result = BatchRunner().run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=_config(root),
                run_config=RunConfig(execution_mode="mock", fresh=True),
            )

            self.assertEqual(result["counts"], {"succeeded": 1})
            artifact_dir = root / "run" / "outputs" / "mock_payload"
            generation = json.loads((artifact_dir / "generation_result.json").read_text(encoding="utf-8"))
            render_request = json.loads((artifact_dir / "render_request.json").read_text(encoding="utf-8"))
            png_params = json.loads((artifact_dir / "png_params.json").read_text(encoding="utf-8"))
            image_path = Path(generation["images"][0]["path"])

            self.assertTrue(image_path.exists())
            self.assertTrue(image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertTrue(generation["request_body"]["split_batch"])
            first_request = generation["request_body"]["requests"][0]
            second_request = generation["request_body"]["requests"][1]
            self.assertEqual(first_request["input"], render_request["prompt"])
            self.assertEqual(first_request["parameters"]["seed"], 12345)
            self.assertEqual(second_request["parameters"]["seed"], 12346)
            self.assertEqual(first_request["parameters"]["n_samples"], 1)
            self.assertEqual(first_request["parameters"]["width"], 832)
            self.assertEqual(first_request["parameters"]["height"], 1216)
            self.assertTrue(png_params["mock"]["enabled"])
            self.assertEqual(png_params["images"][0]["parameters"]["seed"], 12345)
            self.assertEqual(png_params["images"][1]["parameters"]["seed"], 12346)


def _config(root: Path) -> AppConfig:
    legacy = root / "legacy"
    design = legacy / "design"
    design.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        legacy=LegacyConfig(tags_machine_root=legacy, design_root=design),
    )


if __name__ == "__main__":
    unittest.main()
