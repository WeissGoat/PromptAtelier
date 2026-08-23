from publishing_workspace.identity import NodeIdentityNormalizer
from publishing_workspace.models import (
    AssetFingerprint,
    AssetImageInfo,
    AssetRecord,
    ImageNodeInfo,
    ImageNodeRef,
)


def test_character_shortcut_and_numbered_danbooru_names_share_identity():
    info = ImageNodeInfo(
        nodes=[
            ImageNodeRef(
                role="character",
                id="1adanbooru_akemi_homura_暁美ほむら _魔法少女 - 快捷方式",
                ref="F:/design/角色/特殊_next_select/shortcut",
            ),
            ImageNodeRef(
                role="character",
                id="danbooru_akemi_homura_暁美ほむら _魔法少女",
                ref="F:/design/角色/danbooru_mahou_shoujo_madoka_magica/real",
            ),
        ]
    )

    assert info.values_for("character") == [
        "danbooru_akemi_homura_暁美ほむら _魔法少女"
    ]
    # Reader/Catalog 中的原始节点仍然保留，归一化只影响投影结果。
    assert info.nodes[0].id.startswith("1adanbooru_")


def test_identity_normalizer_only_changes_character_nodes():
    normalizer = NodeIdentityNormalizer(
        aliases={("artist", "old_artist"): "new_artist"}
    )

    assert (
        normalizer.normalize("character", "2adanbooru_homura - 快捷方式")
        == "danbooru_homura"
    )
    assert normalizer.normalize("artist", "old_artist") == "old_artist"


def test_projection_uses_canonical_character_identity():
    asset = AssetRecord(
        asset_id="sha256:test",
        path="F:/image.png",
        fingerprint=AssetFingerprint(size=1, modified_ns=1, sha256="test"),
        image=AssetImageInfo(width=1, height=1, format="PNG"),
        node_info=ImageNodeInfo(
            nodes=[
                ImageNodeRef(
                    role="character",
                    id="1adanbooru_homura - 快捷方式",
                )
            ]
        ),
    )

    projection = asset.node_projection(["character"])
    assert projection.values == {"character": ["danbooru_homura"]}
