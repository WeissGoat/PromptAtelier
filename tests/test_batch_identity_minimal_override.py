import unittest
from pathlib import Path

from tags_machine_core.batch import BatchPlanner, BatchSpec
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.services.generation_service import GenerationService


class BatchIdentityMinimalOverrideTest(unittest.TestCase):
    def test_generation_service_override_has_priority_over_character_meta(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            character_id="akemi_homura",
            identity_minimal=["character", "copyright"],
            tags={
                "character": ["akemi_homura"],
                "copyright": ["mahou_shoujo_madoka_magica"],
                "role": ["magical_girl"],
                "hair": ["black_hair"],
            },
        )
        action = NodeDocument(kind="action", id="stand", tags={"action": ["standing"]})
        nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="stand", index=0, node=action),
            ]
        )

        bundle = GenerationService().compose_resolved_nodes(
            nodes,
            identity_minimal_sections=["character", "hair"],
        )

        self.assertIn("2.0::akemi_homura::", bundle.prompt.positive)
        self.assertIn("black_hair", bundle.prompt.positive)
        self.assertNotIn("mahou_shoujo_madoka_magica", bundle.prompt.positive)
        self.assertNotIn("magical_girl", bundle.prompt.positive)

    def test_batch_planner_copies_identity_minimal_sections_to_task(self):
        spec = BatchSpec.model_validate(
            {
                "name": "identity-minimal",
                "defaults": {
                    "composer": "script",
                    "identity_minimal_sections": ["character", "copyright", "hair"],
                },
                "expand": {"mode": "manual"},
                "tasks": [
                    {
                        "id": "one",
                        "nodes": [
                            {"role": "character", "ref": "character-node"},
                            {"role": "action", "ref": "action-node"},
                        ],
                    }
                ],
            }
        )

        task = BatchPlanner(base_dir=Path(".")).plan(spec)[0]

        self.assertEqual(
            task.composition.identity_minimal_sections,
            ["character", "copyright", "hair"],
        )


if __name__ == "__main__":
    unittest.main()
