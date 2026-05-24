import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import AgentComposer, AgentCompositionRequired
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.nodes.models import NodeDocument


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


class AgentComposerTest(unittest.TestCase):
    def test_build_task_contains_agent_readable_node_snapshots(self):
        task = AgentComposer().build_task(
            character=_character("characters/homura"),
            action=_action("actions/foot_closeup"),
            style_ref="20260412_2",
            character_scope="foot_detail",
            instructions=["避免把眼睛和上衣放进脚部特写"],
        )

        self.assertEqual(task.schema_id, "tags-machine-core.agent-composition-task/v1")
        self.assertTrue(task.cache_key.startswith("sha256:"))
        self.assertEqual(task.nodes["character"].id, "homura")
        self.assertEqual(task.nodes["action"].node["character_scope"], "foot_detail")
        self.assertEqual(task.instructions, ["避免把眼睛和上衣放进脚部特写"])

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
                    changed_version.cache_key,
                }
            ),
            6,
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
                result=result,
                cache=cache,
            )
            second = composer.compose_nodes(
                character=_character(),
                action=_action(),
                character_scope="foot_detail",
                cache=cache,
            )

        self.assertFalse(first.cache.cache_hit)
        self.assertTrue(second.cache.cache_hit)
        self.assertEqual(_stable_bundle_json(first), _stable_bundle_json(second))
        self.assertEqual(second.prompt.positive, "akemi homura, bare soles, foot focus")
        self.assertEqual(second.meta.composer_type, "agent")
        self.assertEqual(second.meta.composition.character_scope, "foot_detail")
        self.assertEqual(second.meta.extra["agent"]["notes"], ["agent 合并了角色和动作"])

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
