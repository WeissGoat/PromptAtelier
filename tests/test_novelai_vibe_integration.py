from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.batch import BatchRunner
from tags_machine_core.batch.models import BatchTask, RenderOptions, RunConfig
from tags_machine_core.config import AppConfig, LegacyConfig
from tags_machine_core.contracts import PromptBundle, PromptMeta, PromptText, RenderRequest
from tags_machine_core.execution import build_core_png_text
from tags_machine_core.policies import PromptPolicyProvider
from tags_machine_core.services import GenerationService


def _image_policy(path: Path):
    return PromptPolicyProvider().resolve(
        {
            "enabled": True,
            "apply_to": {"full_prompt": True},
            "rules": {
                "novelai_vibe": {
                    "enabled": True,
                    "options": {
                        "source": {"type": "image", "path": str(path)},
                        "strength": 0.35,
                        "information_extracted": 0.85,
                    },
                }
            },
        }
    )


class NovelAIVibeIntegrationTest(unittest.TestCase):
    def test_generation_service_builds_final_request_with_vibe_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "vibe.png"
            image.write_bytes(b"integration-vibe")
            policy = _image_policy(image)
            service = GenerationService(policy_relative_to=root)

            bundle = service.compose_full_prompt("1girl, standing")
            request = service.build_novelai_request(
                bundle,
                seed=123,
                params={"n_samples": 1},
                prompt_policy=policy,
                policy_target="full_prompt",
            )

            self.assertEqual(request.params["reference_strength_multiple"], [0.35])
            self.assertEqual(request.params["reference_information_extracted_multiple"], [0.85])
            self.assertEqual(request.meta["novelai_render_policy"]["source_type"], "image")
            self.assertNotIn("integration-vibe", json.dumps(request.meta))

    def test_agent_render_target_remains_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "vibe.png"
            image.write_bytes(b"agent-vibe")
            policy = _image_policy(image)
            bundle = PromptBundle(
                prompt=PromptText(positive="agent prompt"),
                meta=PromptMeta(composer_type="agent"),
            )
            request = GenerationService(policy_relative_to=root).build_novelai_request(
                bundle,
                seed=123,
                prompt_policy=policy,
                policy_target="agent",
            )

            self.assertNotIn("novelai_render_policy", request.meta)
            self.assertEqual(request.params["reference_image_multiple"], [])

    def test_batch_mock_uses_the_same_final_request_and_png_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "vibe.png"
            image.write_bytes(b"batch-vibe")
            legacy = root / "legacy"
            design = legacy / "design"
            design.mkdir(parents=True)
            policy = _image_policy(image)
            task = BatchTask(
                id="vibe_policy",
                index=0,
                composer="full",
                prompt="1girl, standing",
                policy=policy,
                render=RenderOptions(
                    backend="novelai",
                    nt=1,
                    width=832,
                    height=1216,
                    seed=456,
                ),
                output={
                    "task_dir": str(root / "run" / "tasks" / "vibe_policy"),
                    "output_dir": str(root / "run" / "outputs" / "vibe_policy"),
                },
            )
            config = AppConfig(
                legacy=LegacyConfig(tags_machine_root=legacy, design_root=design),
            )

            result = BatchRunner().run_tasks(
                run_dir=root / "run",
                tasks=[task],
                config=config,
                run_config=RunConfig(execution_mode="mock", fresh=True),
                policy_relative_to=root,
            )

            self.assertEqual(result["counts"], {"succeeded": 1})
            artifact_dir = root / "run" / "outputs" / "vibe_policy"
            render_request = json.loads(
                (artifact_dir / "render_request.json").read_text(encoding="utf-8")
            )
            generation = json.loads(
                (artifact_dir / "generation_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                render_request["params"]["reference_strength_multiple"], [0.35]
            )
            self.assertEqual(
                generation["request_body"]["parameters"]["reference_information_extracted_multiple"],
                [0.85],
            )
            saved_png_text = generation["png_info"]["images"][0]["png_text"]
            self.assertIn("novelai_render_policy", saved_png_text["tags_machine_core"])
            self.assertNotIn("batch-vibe", saved_png_text["tags_machine_core"])
            png_text = build_core_png_text(
                RenderRequest.model_validate(render_request)
            )
            self.assertIn("novelai_render_policy", png_text["tags_machine_core"])
            self.assertNotIn("batch-vibe", png_text["tags_machine_core"])


if __name__ == "__main__":
    unittest.main()
