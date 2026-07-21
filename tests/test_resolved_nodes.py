import unittest

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import NodeInput, ResolvedNode, ResolvedNodeSet


class ResolvedNodesTest(unittest.TestCase):
    def test_node_input_parses_role_ref_text(self):
        item = NodeInput.parse("character:homura")

        self.assertEqual(item.role, "character")
        self.assertEqual(item.ref, "homura")

    def test_resolved_node_set_groups_multiple_characters(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        madoka = NodeDocument(
            kind="character",
            id="madoka",
            tags={"character": ["kaname madoka"]},
        )
        artist = NodeDocument(kind="artist", id="20260412_2")
        nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=homura),
                ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
                ResolvedNode(role="artist", ref="20260412_2", index=0, node=artist),
            ]
        )

        self.assertEqual(
            [item.node.id for item in nodes.characters()],
            ["homura", "madoka"],
        )
        self.assertEqual(nodes.first("artist").node.id, "20260412_2")
        self.assertEqual(
            nodes.refs(),
            [
                {"role": "character", "ref": "homura", "id": "homura", "index": 0},
                {"role": "character", "ref": "madoka", "id": "madoka", "index": 1},
                {"role": "artist", "ref": "20260412_2", "id": "20260412_2", "index": 0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
