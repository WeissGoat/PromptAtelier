import unittest
from pathlib import Path

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.services.generation_service import GenerationService


class TagInferencePolicyTest(unittest.TestCase):
    def test_barefoot_infers_bare_legs_globally(self):
        service = GenerationService()

        # 1. 任意角色（即使 meta 和 extension 均无 barefoot 规则）
        character = NodeDocument(
            kind="character",
            id="test_char",
            tags={"character": ["test_girl"]},
        )
        action = NodeDocument(
            kind="action",
            id="barefoot_action",
            tags={"action": ["1girl, barefoot, smile"]},
        )
        nodes = ResolvedNodeSet([
            ResolvedNode(role="character", ref="test_char", index=0, node=character),
            ResolvedNode(role="action", ref="barefoot_action", index=0, node=action),
        ])

        bundle = service.compose_resolved_nodes(nodes)

        # 验证 barefoot 后面由全局 tag_inference 规则插入了 bare_legs
        self.assertIn("barefoot", bundle.prompt.positive)
        self.assertIn("bare_legs", bundle.prompt.positive)

        # 验证位置在 barefoot 之后
        tokens = bundle.prompt.positive.split(", ")
        bf_idx = tokens.index("barefoot")
        bl_idx = tokens.index("bare_legs")
        self.assertEqual(bl_idx, bf_idx + 1)

    def test_existing_bare_legs_not_duplicated(self):
        service = GenerationService()
        bundle = service.compose_full_prompt(
            "1girl, barefoot, bare_legs, smile",
            prompt_policy={
                "enabled": True,
                "profile": "balanced",
                "apply_to": {"full_prompt": True},
            },
        )
        tokens = bundle.prompt.positive.split(", ")
        self.assertEqual(tokens.count("bare_legs"), 1)


if __name__ == "__main__":
    unittest.main()
