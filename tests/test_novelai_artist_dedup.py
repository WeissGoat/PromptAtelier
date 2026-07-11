import unittest
from pathlib import Path

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtist
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.renderers.novelai import NovelAIRenderAdapter


class NovelAIArtistDedupTest(unittest.TestCase):
    def test_explicit_legacy_artist_is_not_duplicated_when_also_resolved(self):
        artist = NovelAIArtist(
            artist_ref="legacy-sample",
            path=Path("design/artists/legacy-sample"),
            prompt_prefix=["unique artist prefix"],
            prompt_suffix=["unique artist suffix"],
        )
        artist_node = NodeDocument.model_validate(
            {
                "kind": "artist",
                "id": "legacy-sample",
                "renderers": {
                    "novelai": {
                        "legacy_compat": True,
                        "prompt_prefix": artist.prompt_prefix,
                        "prompt_suffix": artist.prompt_suffix,
                    }
                },
            }
        )
        character_node = NodeDocument.model_validate(
            {
                "kind": "character",
                "id": "subject",
                "prompt": {"positive": ["1girl"]},
            }
        )
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="artist", ref="legacy-sample", index=0, node=artist_node),
                ResolvedNode(role="character", ref="subject", index=0, node=character_node),
            ]
        )

        bundle = ScriptComposer().compose_resolved_nodes(resolved)
        request = NovelAIRenderAdapter().build_request(
            bundle,
            artist=artist,
            resolved_nodes=resolved,
            seed=123,
        )

        self.assertEqual(request.prompt.count("unique artist prefix"), 1)
        self.assertEqual(request.prompt.count("unique artist suffix"), 1)


if __name__ == "__main__":
    unittest.main()
