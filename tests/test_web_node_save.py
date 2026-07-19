import tempfile
from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.node_workspace import NodeWorkspace


class WebNodeSaveTest(TestCase):
    def test_artist_preview_does_not_write_and_commit_updates_tags_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            artist = design / "画风" / "manga"
            artist.mkdir(parents=True)
            tags = artist / "tags.txt"
            original = (
                "prefix_a,\nprefix_b,\nsuffix_c,\ntype, keep_flag\n=\n"
                "origin_uc, bad anatomy\n"
                "gen_param, 'model': 'nai-diffusion-4-5-full', 'steps': 23\n"
                'gen_json, {"model":"nai-diffusion-4-5-full","steps":23}\n'
                "custom_extension, preserve_me\n"
            )
            tags.write_text(original, encoding="utf-8")
            client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=design)))

            loaded = client.get("/api/nodes/read", params={"ref": str(artist), "role": "artist"}).json()
            values = loaded["editor"]["values"]
            self.assertNotIn("renderers", values)
            values["prompt_prefix"][0] = "prefix_changed"

            preview = client.post(
                "/api/nodes/save-preview",
                json={"ref": str(artist), "role": "artist", "values": values},
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(tags.read_text(encoding="utf-8"), original)
            self.assertIn("prefix_changed", preview.json()["files"][0]["diff"])

            committed = client.put(
                "/api/nodes/save-commit",
                json={"preview_id": preview.json()["preview_id"]},
            )
            self.assertEqual(committed.status_code, 200, committed.text)
            saved = tags.read_text(encoding="utf-8")
            self.assertIn("prefix_changed", saved)
            self.assertIn("prefix_b,\n", saved)
            self.assertIn("suffix_c,\n", saved)
            self.assertIn("gen_param, 'model': 'nai-diffusion-4-5-full', 'steps': 23\n", saved)
            self.assertIn('gen_json, {"model":"nai-diffusion-4-5-full","steps":23}\n', saved)
            self.assertIn("custom_extension, preserve_me", saved)
            self.assertFalse((artist / "meta.yaml").exists())

    def test_commit_rejects_source_changed_after_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            artist = design / "画风" / "manga"
            artist.mkdir(parents=True)
            tags = artist / "tags.txt"
            tags.write_text("prefix\n=\n", encoding="utf-8")
            client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=design)))
            loaded = client.get("/api/nodes/read", params={"ref": str(artist), "role": "artist"}).json()
            values = loaded["editor"]["values"]
            values["prompt_prefix"] = ["changed"]
            preview = client.post(
                "/api/nodes/save-preview",
                json={"ref": str(artist), "role": "artist", "values": values},
            ).json()

            tags.write_text("external change\n", encoding="utf-8")
            response = client.put("/api/nodes/save-commit", json={"preview_id": preview["preview_id"]})

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "source_changed")
            self.assertEqual(tags.read_text(encoding="utf-8"), "external change\n")

    def test_action_preview_updates_prompt_meta_and_selected_keys_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            action = design / "动作改2" / "new" / "action-a"
            action.mkdir(parents=True)
            (action / "tags.txt").write_text("standing, smile\n", encoding="utf-8")
            (action / "meta.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": "tags-machine.action/v1",
                        "kind": "action",
                        "id": "action-a",
                        "name": "action-a",
                        "tags": {"action": ["standing", "smile"]},
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            profile = "---\nschema_version: 1\ncharacters:\n- selected_keys:\n  - character\n---\n\nbody\n"
            (action / "run-prompt-prompt.md").write_text(profile, encoding="utf-8")
            classify = "schema_version: 1\ndomain: [body]\n"
            (action / "classify.yaml").write_text(classify, encoding="utf-8")
            client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=design)))

            loaded = client.get("/api/nodes/read", params={"ref": str(action), "role": "action"}).json()
            values = loaded["editor"]["values"]
            values["prompt_lines"] = ["sitting, smile"]
            values["selected_keys"] = [["character", "hair"]]
            response = client.post(
                "/api/nodes/save-preview",
                json={"ref": str(action), "role": "action", "values": values},
            )

            self.assertEqual(response.status_code, 200, response.text)
            changed = {item["relative"] for item in response.json()["files"] if item["changed"]}
            self.assertEqual(changed, {"tags.txt", "meta.yaml", "run-prompt-prompt.md"})
            self.assertEqual((action / "classify.yaml").read_text(encoding="utf-8"), classify)

    def test_character_save_writes_source_fields_without_runtime_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            character = design / "角色" / "homura"
            character.mkdir(parents=True)
            (character / "meta.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema": "tags-machine.character/v1",
                        "kind": "character",
                        "id": "homura",
                        "tags": {"character": ["akemi_homura"]},
                        "agent": {"note": "preserve"},
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=design)))
            loaded = client.get("/api/nodes/read", params={"ref": str(character), "role": "character"}).json()
            values = loaded["editor"]["values"]
            values["tags"]["hair"] = ["black_hair"]
            preview = client.post(
                "/api/nodes/save-preview",
                json={"ref": str(character), "role": "character", "values": values},
            ).json()
            committed = client.put("/api/nodes/save-commit", json={"preview_id": preview["preview_id"]})

            self.assertEqual(committed.status_code, 200, committed.text)
            raw = yaml.safe_load((character / "meta.yaml").read_text(encoding="utf-8"))
            self.assertEqual(raw["tags"]["hair"], ["black_hair"])
            self.assertEqual(raw["agent"], {"note": "preserve"})
            for key in ("path", "renderers", "generation", "legacy"):
                self.assertNotIn(key, raw)
