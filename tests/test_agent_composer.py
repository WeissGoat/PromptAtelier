import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import AgentComposer, AgentCompositionRequired
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet


def _stable_bundle_json(bundle) -> str:
    data = bundle.model_dump(mode="json", by_alias=True)
    data["cache"]["cache_hit"] = False
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _character(path: str | None = None) -> NodeDocument:
    return NodeDocument.model_validate(
        {
            "schema": "tags-machine.character/v1",
            "kind": "character",
            "id": "homura",
            "path": path,
            "tags": {
                "character": ["akemi homura"],
                "eyes": ["purple eyes"],
                "feet": ["bare soles"],
            },
            "negative_prompt": ["extra toes"],
        }
    )


def _action(path: str | None = None) -> NodeDocument:
    return NodeDocument.model_validate(
        {
            "schema": "tags-machine.action/v1",
            "kind": "action",
            "id": "foot_closeup",
            "path": path,
            "tags": {"action": ["foot focus"]},
            "character_scope": "foot_detail",
        }
    )


def _second_character(path: str | None = None) -> NodeDocument:
    return NodeDocument.model_validate(
        {
            "schema": "tags-machine.character/v1",
            "kind": "character",
            "id": "madoka",
            "path": path,
            "tags": {
                "character": ["kaname madoka"],
                "hair": ["pink hair"],
            },
        }
    )


class AgentComposerTest(unittest.TestCase):
    def test_build_task_contains_agent_readable_node_snapshots(self):
        task = AgentComposer().build_task(
            character=_character("characters/homura"),
            action=_action("actions/foot_closeup"),
            style_ref="20260412_2",
            character_scope="foot_detail",
            instructions=["避免把眼睛和上衣放进脚部特写"],
            agent_model="agent-model-v1",
        )

        self.assertEqual(task.schema_id, "tags-machine-core.agent-composition-task/v1")
        self.assertTrue(task.cache_key.startswith("sha256:"))
        self.assertEqual(task.nodes["character"].id, "homura")
        self.assertEqual(task.nodes["action"].node["character_scope"], "foot_detail")
        self.assertEqual(task.instructions, ["避免把眼睛和上衣放进脚部特写"])
        self.assertEqual(task.agent_model, "agent-model-v1")

    def test_build_task_defaults_character_scope_from_action(self):
        task = AgentComposer().build_task(
            character=_character("characters/homura"),
            action=_action("actions/foot_closeup"),
            style_ref="20260412_2",
        )

        self.assertEqual(task.character_scope, "foot_detail")

    def test_explicit_character_scope_overrides_action_scope(self):
        task = AgentComposer().build_task(
            character=_character("characters/homura"),
            action=_action("actions/foot_closeup"),
            character_scope="upper_body",
        )

        self.assertEqual(task.character_scope, "upper_body")

    def test_task_cache_key_ignores_source_paths(self):
        composer = AgentComposer()

        left = composer.build_task(
            character=_character("tmp/a/homura"),
            action=_action("tmp/a/foot_closeup"),
            character_scope="foot_detail",
        )
        right = composer.build_task(
            character=_character("tmp/b/homura"),
            action=_action("tmp/b/foot_closeup"),
            character_scope="foot_detail",
        )

        self.assertEqual(left.cache_key, right.cache_key)
        self.assertNotEqual(left.nodes["character"].ref, right.nodes["character"].ref)

    def test_task_cache_key_changes_for_content_version_and_explicit_inputs(self):
        composer = AgentComposer()
        base = composer.build_task(
            character=_character(),
            action=_action(),
            character_scope="foot_detail",
            instructions=["避免无关细节"],
        )
        changed_character = _character().model_copy(
            update={
                "tags": {
                    "character": ["akemi homura"],
                    "eyes": ["purple eyes"],
                    "feet": ["bare feet"],
                }
            }
        )
        changed_content = composer.build_task(
            character=changed_character,
            action=_action(),
            character_scope="foot_detail",
            instructions=["避免无关细节"],
        )
        changed_scope = composer.build_task(
            character=_character(),
            action=_action(),
            character_scope="upper_body",
            instructions=["避免无关细节"],
        )
        changed_extra_prompt = composer.build_task(
            character=_character(),
            action=_action(),
            extra_prompt="low angle",
            character_scope="foot_detail",
            instructions=["避免无关细节"],
        )
        changed_instruction = composer.build_task(
            character=_character(),
            action=_action(),
            character_scope="foot_detail",
            instructions=["保留角色辨识度"],
        )
        changed_agent_model = composer.build_task(
            character=_character(),
            action=_action(),
            character_scope="foot_detail",
            instructions=["避免无关细节"],
            agent_model="agent-model-v2",
        )
        changed_version_composer = AgentComposer()
        changed_version_composer.composer_version = "v2"
        changed_version = changed_version_composer.build_task(
            character=_character(),
            action=_action(),
            character_scope="foot_detail",
            instructions=["避免无关细节"],
        )

        self.assertNotEqual(
            base.nodes["character"].content_hash,
            changed_content.nodes["character"].content_hash,
        )
        self.assertEqual(
            len(
                {
                    base.cache_key,
                    changed_content.cache_key,
                    changed_scope.cache_key,
                    changed_extra_prompt.cache_key,
                    changed_instruction.cache_key,
                    changed_agent_model.cache_key,
                    changed_version.cache_key,
                }
            ),
            7,
        )

    def test_compose_nodes_writes_and_reuses_cache(self):
        composer = AgentComposer()
        result = {
            "positive": "akemi homura, bare soles, foot focus",
            "negative": "extra toes, face focus",
            "character_scope": "foot_detail",
            "included_character_sections": ["character", "feet"],
            "suppressed_character_sections": ["eyes", "upper_clothes"],
            "notes": ["agent 合并了角色和动作"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            cache = PromptCache(Path(tmp) / "prompt")
            first = composer.compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
                agent_model="agent-model-v1",
                result=result,
                cache=cache,
            )
            second = composer.compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
                agent_model="agent-model-v1",
                cache=cache,
            )

        self.assertFalse(first.cache.cache_hit)
        self.assertTrue(second.cache.cache_hit)
        self.assertEqual(_stable_bundle_json(first), _stable_bundle_json(second))
        self.assertEqual(second.prompt.positive, "akemi homura, bare soles, foot focus")
        self.assertEqual(second.meta.composer_type, "agent")
        self.assertEqual(second.meta.composition.character_scope, "foot_detail")
        self.assertEqual(second.meta.extra["agent"]["agent_model"], "agent-model-v1")
        self.assertEqual(second.meta.extra["agent"]["notes"], ["agent 合并了角色和动作"])

    def test_compose_nodes_does_not_reuse_cache_for_different_agent_model(self):
        composer = AgentComposer()
        result = {
            "positive": "akemi homura, bare soles, foot focus",
            "negative": "extra toes, face focus",
            "character_scope": "foot_detail",
            "included_character_sections": ["character", "feet"],
            "suppressed_character_sections": ["eyes", "upper_clothes"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            cache = PromptCache(Path(tmp) / "prompt")
            first = composer.compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
                agent_model="agent-model-v1",
                result=result,
                cache=cache,
            )
            with self.assertRaises(AgentCompositionRequired) as raised:
                composer.compose_nodes(
                    character=_character(),
                    action=_action(),
                    character_scope="foot_detail",
                    agent_model="agent-model-v2",
                    cache=cache,
                )

        self.assertNotEqual(first.cache.cache_key, raised.exception.task.cache_key)
        self.assertEqual(raised.exception.task.agent_model, "agent-model-v2")

    def test_compose_resolved_nodes_supports_multiple_characters(self):
        composer = AgentComposer()
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(
                    role="character",
                    ref="characters/homura",
                    index=0,
                    node=_character("characters/homura"),
                ),
                ResolvedNode(
                    role="character",
                    ref="characters/madoka",
                    index=1,
                    node=_second_character("characters/madoka"),
                ),
                ResolvedNode(
                    role="action",
                    ref="actions/foot_closeup",
                    index=0,
                    node=_action("actions/foot_closeup"),
                ),
            ]
        )
        result = {
            "positive": "akemi homura, kaname madoka, bare soles, foot focus",
            "negative": "extra toes",
            "character_scope": "foot_detail",
        }

        bundle = composer.compose_resolved_nodes(
            resolved,
            style_ref="20260412_2",
            result=result,
        )

        self.assertIsNone(bundle.meta.character_ref)
        self.assertEqual(bundle.meta.action_ref, "foot_closeup")
        self.assertEqual(bundle.meta.extra["node_refs"][1]["id"], "madoka")
        self.assertEqual(
            bundle.meta.extra["character_materials"][0]["positive_tags"],
            ["akemi homura", "bare soles"],
        )
        self.assertEqual(
            bundle.meta.extra["character_materials"][0]["suppressed_sections"],
            ["eyes"],
        )
        self.assertEqual(
            bundle.meta.extra["character_materials"][1]["positive_tags"],
            ["kaname madoka"],
        )
        self.assertEqual(
            bundle.meta.extra["character_materials"][1]["suppressed_sections"],
            ["hair"],
        )

    def test_prompt_cache_rejects_file_with_mismatched_internal_cache_key(self):
        composer = AgentComposer()
        result = {
            "positive": "akemi homura, bare soles, foot focus",
            "negative": "extra toes, face focus",
            "character_scope": "foot_detail",
            "included_character_sections": ["character", "feet"],
            "suppressed_character_sections": ["eyes", "upper_clothes"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            cache = PromptCache(Path(tmp) / "prompt")
            bundle = composer.compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
                agent_model="agent-model-v1",
                result=result,
            )
            mismatched_key = "sha256:" + "b" * 64
            cache._path_for(mismatched_key).write_text(
                bundle.model_dump_json(indent=2, by_alias=True),
                encoding="utf-8",
            )

            self.assertIsNone(cache.get(mismatched_key))
            self.assertIsNone(cache.get("  " + mismatched_key + "  "))

    def test_prompt_cache_keeps_standard_sha256_filename_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = PromptCache(Path(tmp) / "prompt")
            path = cache._path_for("sha256:" + "a" * 64)

        self.assertEqual(path.name, "sha256_" + "a" * 64 + ".json")

    def test_prompt_cache_sanitizes_external_cache_keys_into_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = PromptCache(Path(tmp) / "prompt")
            path = cache._path_for("../agent/task:脚部特写?*")

        self.assertEqual(path.parent.name, "prompt")
        self.assertEqual(path.suffix, ".json")
        self.assertNotIn("..", path.name)
        self.assertNotIn("/", path.name)
        self.assertNotIn("\\", path.name)
        self.assertLessEqual(len(path.stem), 120)

    def test_compose_nodes_requires_result_on_cache_miss(self):
        with self.assertRaises(AgentCompositionRequired) as raised:
            AgentComposer().compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
            )

        self.assertTrue(raised.exception.task.cache_key.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
