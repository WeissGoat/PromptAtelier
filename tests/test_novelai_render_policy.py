from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.contracts import RenderRequest, RenderSize
from tags_machine_core.policies import PromptPolicyProvider
from tags_machine_core.policies.rendering.novelai import NovelAIRenderPolicyPipeline


def _request() -> RenderRequest:
    return RenderRequest(
        backend="novelai",
        prompt="artist prompt, 1girl, standing",
        negative_prompt="bad anatomy",
        model="nai-diffusion-4-5-full",
        seed=123,
        size=RenderSize(width=832, height=1216),
        params={
            "prompt": "artist prompt, 1girl, standing",
            "negative_prompt": "bad anatomy",
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "scale": 5.0,
            "seed": 123,
            "reference_image_multiple": ["old-vibe"],
            "reference_strength_multiple": [0.1],
            "reference_information_extracted_multiple": [],
        },
        artist_payload={"artist_ref": "base-artist"},
        meta={"composer_type": "script"},
    )


def _policy(options: dict) -> object:
    return PromptPolicyProvider().resolve(
        {
            "enabled": True,
            "apply_to": {"script": True},
            "rules": {
                "novelai_vibe": {
                    "enabled": True,
                    "options": options,
                }
            },
        }
    )


class NovelAIRenderPolicyTest(unittest.TestCase):
    def test_image_source_replaces_only_vibe_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "vibe.png"
            image_bytes = b"fake-png-bytes"
            image_path.write_bytes(image_bytes)
            policy = _policy(
                {
                    "source": {"type": "image", "path": str(image_path)},
                    "strength": [0.2],
                    "information_extracted": [1.0],
                }
            )

            result = NovelAIRenderPolicyPipeline().apply(
                _request(),
                bundle=ScriptComposer().compose_full_prompt("1girl, standing"),
                resolved_nodes=None,
                policy=policy,
                target="script",
            )

        self.assertEqual(result.prompt, "artist prompt, 1girl, standing")
        self.assertEqual(result.negative_prompt, "bad anatomy")
        self.assertEqual(result.model, "nai-diffusion-4-5-full")
        self.assertEqual(result.seed, 123)
        self.assertEqual(result.params["sampler"], "k_euler_ancestral")
        self.assertEqual(
            result.params["reference_image_multiple"],
            [base64.b64encode(image_bytes).decode("ascii")],
        )
        self.assertEqual(result.params["reference_strength_multiple"], [0.2])
        self.assertEqual(result.params["reference_information_extracted_multiple"], [1.0])
        metadata = result.meta["novelai_render_policy"]
        self.assertEqual(metadata["source_type"], "image")
        self.assertNotIn(base64.b64encode(image_bytes).decode("ascii"), json.dumps(metadata))

    def test_artist_source_reads_only_reference_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_dir = design_root / "画风" / "vibe_artist"
            artist_dir.mkdir(parents=True)
            (artist_dir / "tags.txt").write_text(
                "artist source prompt\n"
                "=\n"
                'gen_json, {"model":"nai-diffusion-3","reference_image_multiple":["new-a","new-b"],'
                '"reference_strength_multiple":[0.13,0.14],'
                '"reference_information_extracted_multiple":[0.8,0.7]}\n',
                encoding="utf-8",
            )
            policy = _policy(
                {
                    "source": {"type": "artist", "ref": "vibe_artist"},
                    "strength": [0.2],
                }
            )

            result = NovelAIRenderPolicyPipeline().apply(
                _request(),
                bundle=ScriptComposer().compose_full_prompt("1girl, standing"),
                resolved_nodes=None,
                policy=policy,
                target="script",
                design_root=design_root,
            )

        self.assertEqual(result.params["reference_image_multiple"], ["new-a", "new-b"])
        self.assertEqual(result.params["reference_strength_multiple"], [0.2, 0.2])
        self.assertEqual(result.params["reference_information_extracted_multiple"], [0.8, 0.7])
        self.assertEqual(result.model, "nai-diffusion-4-5-full")
        self.assertEqual(result.params["sampler"], "k_euler_ancestral")
        self.assertEqual(result.artist_payload["artist_ref"], "base-artist")

    def test_disabled_target_does_not_change_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vibe.png"
            path.write_bytes(b"bytes")
            policy = PromptPolicyProvider().resolve(
                {
                    "enabled": True,
                    "apply_to": {"script": False},
                    "rules": {
                        "novelai_vibe": {
                            "enabled": True,
                            "options": {
                                "source": {"type": "image", "path": str(path)},
                                "strength": [0.2],
                                "information_extracted": [1.0],
                            },
                        }
                    },
                }
            )
            request = _request()
            result = NovelAIRenderPolicyPipeline().apply(
                request,
                bundle=ScriptComposer().compose_full_prompt("1girl"),
                resolved_nodes=None,
                policy=policy,
                target="script",
            )

        self.assertIs(result, request)
        self.assertNotIn("novelai_render_policy", result.meta)

    def test_invalid_image_arrays_fail_before_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vibe.png"
            path.write_bytes(b"bytes")
            policy = _policy(
                {
                    "source": {"type": "image", "path": str(path)},
                    "strength": [0.2, 0.3],
                    "information_extracted": [1.0],
                }
            )
            with self.assertRaises(ValueError):
                NovelAIRenderPolicyPipeline().apply(
                    _request(),
                    bundle=ScriptComposer().compose_full_prompt("1girl"),
                    resolved_nodes=None,
                    policy=policy,
                    target="script",
                )

    def test_novelai_vibe_artist_alias_maps_to_novelai_vibe(self):
        policy = PromptPolicyProvider().resolve(
            {
                "enabled": True,
                "apply_to": {"script": True},
                "rules": {
                    "novelai_vibe_artist": {
                        "enabled": True,
                        "options": {
                            "artist_ref": "artists/test_artist",
                            "strength": 0.4,
                        },
                    }
                },
            }
        )
        self.assertNotIn("novelai_vibe_artist", policy.rules)
        self.assertIn("novelai_vibe", policy.rules)
        self.assertEqual(
            policy.rules["novelai_vibe"].options["source"]["ref"],
            "artists/test_artist",
        )
        self.assertEqual(
            policy.rules["novelai_vibe"].options["source"]["type"],
            "artist",
        )
        self.assertEqual(policy.rules["novelai_vibe"].options["strength"], 0.4)


if __name__ == "__main__":
    unittest.main()
