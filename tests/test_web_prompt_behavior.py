from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.node_workspace import NodeWorkspace


class WebPromptBehaviorTest(TestCase):
    def _create_client(self, root: Path) -> tuple[TestClient, Path]:
        design = root / "design"
        character = design / "characters" / "homura"
        character.mkdir(parents=True)
        (character / "meta.yaml").write_text(
            yaml.safe_dump(
                {
                    "kind": "character",
                    "id": "homura",
                    "name": "homura",
                    "identity_minimal": ["character", "role"],
                    "tags": {
                        "character": ["akemi_homura"],
                        "role": ["magical_girl"],
                        "copyright": ["mahou_shoujo_madoka_magica"],
                        "hair": ["black_hair"],
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        config_path = root / "local.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "legacy": {
                        "tags_machine_root": str(root),
                        "design_root": str(design),
                    },
                    "runtime": {
                        "cache_dir": str(root / "cache"),
                        "output_dir": str(root / "outputs"),
                    },
                    "prompt_policy": {"require": "legacy_compat"},
                    "novelai": {"access_token": "test-token"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return (
            TestClient(
                create_app(
                    config_path=config_path,
                    node_workspace=NodeWorkspace(design_root=design),
                )
            ),
            character,
        )

    def _preview(
        self,
        client: TestClient,
        character: Path,
        compose: dict,
        render: dict | None = None,
    ) -> dict:
        response = client.post(
            "/api/compose-preview",
            json={
                "compose": {
                    "nodes": [{"role": "character", "ref": str(character)}],
                    **compose,
                },
                "render": {
                    "backend": "novelai",
                    "width": 1024,
                    "height": 1024,
                    **(render or {}),
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_compose_preview_passes_identity_minimal_sections_to_script_composer(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            body = self._preview(
                client,
                character,
                {"identity_minimal_sections": ["character"]},
            )

            self.assertEqual(
                body["prompt_bundle"]["meta"]["composition"]["included_character_sections"],
                ["character"],
            )
            self.assertIn("akemi_homura", body["prompt_bundle"]["prompt"]["positive"])
            self.assertNotIn("magical_girl", body["prompt_bundle"]["prompt"]["positive"])

    def test_compose_preview_rejects_empty_identity_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            response = client.post(
                "/api/compose-preview",
                json={
                    "compose": {
                        "nodes": [{"role": "character", "ref": str(character)}],
                        "identity_minimal_sections": [],
                    },
                    "render": {},
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                "identity_minimal_sections",
                response.json()["error"]["message"],
            )

    def test_web_policy_override_inherits_project_legacy_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            body = self._preview(
                client,
                character,
                {
                    "prompt_policy": {
                        "rules": {
                            "visibility_policy": {"enabled": False},
                        },
                    },
                },
            )

            policy = body["prompt_bundle"]["meta"]["extra"]["policy"]
            self.assertEqual(policy["template"], "off -> balanced -> legacy_compat")
            self.assertNotIn(
                "visibility_policy@v1",
                policy["effective_rule_order"],
            )

    def test_web_policy_cannot_replace_project_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            response = client.post(
                "/api/compose-preview",
                json={
                    "compose": {
                        "nodes": [{"role": "character", "ref": str(character)}],
                        "prompt_policy": {"require": "off"},
                    },
                    "render": {},
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("require", response.json()["error"]["message"])

    def test_character_prompts_auto_builds_v4_character_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            body = self._preview(
                client,
                character,
                {},
                render={
                    "model": "nai-diffusion-4-5-full",
                    "params": {
                        "character_prompts": {
                            "mode": "auto",
                            "add_male_caption": True,
                        },
                    },
                },
            )

            request = body["render_request"]
            self.assertIn("characterPrompts", request["params"])
            self.assertEqual(request["meta"]["character_prompts"]["mode"], "auto")
            self.assertGreaterEqual(request["meta"]["character_prompts"]["count"], 1)

    def test_character_prompts_off_keeps_character_tags_in_base_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, character = self._create_client(Path(tmp))

            body = self._preview(
                client,
                character,
                {},
                render={
                    "model": "nai-diffusion-4-5-full",
                    "params": {"character_prompts": {"mode": "off"}},
                },
            )

            request = body["render_request"]
            self.assertNotIn("characterPrompts", request["params"])
            self.assertNotIn("character_prompts", request["meta"])
            self.assertIn("akemi_homura", request["params"]["prompt"])
