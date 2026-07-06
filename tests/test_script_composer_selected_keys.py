from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet


def test_selected_keys_override_character_scope_for_character_sections():
    character = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "copyright": ["puella magi madoka magica"],
            "hair": ["black hair"],
            "eyes": ["purple eyes"],
            "feet": ["black shoes"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="foot_action",
        character_scope="foot_detail",
        tags={"action": ["foot focus"]},
        composition={
            "character_selection": {
                "source": "run-prompt-prompt.md",
                "characters": [
                    {"selected_keys": ["character", "copyright", "hair"]}
                ],
            }
        },
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "puella magi madoka magica" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "purple eyes" not in bundle.prompt.positive
    assert "black shoes" not in bundle.prompt.positive
    assert "foot focus" in bundle.prompt.positive
    assert bundle.meta.composition.included_character_sections == [
        "character",
        "copyright",
        "hair",
    ]


def test_selected_keys_apply_per_character_index():
    homura = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "hair": ["black hair"],
            "feet": ["black shoes"],
        },
    )
    madoka = NodeDocument(
        kind="character",
        id="madoka",
        tags={
            "character": ["kaname madoka"],
            "hair": ["pink hair"],
            "feet": ["bare feet"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="duo_action",
        tags={"action": ["2girls, sitting"]},
        composition={
            "character_selection": {
                "source": "action_profile.yaml",
                "characters": [
                    {"selected_keys": ["character", "hair"]},
                    {"selected_keys": ["character", "feet"]},
                ],
            }
        },
    )
    nodes = ResolvedNodeSet(
        [
            ResolvedNode(role="character", ref="homura", index=0, node=homura),
            ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
            ResolvedNode(role="action", ref="duo_action", index=0, node=action),
        ]
    )

    bundle = ScriptComposer().compose_resolved_nodes(nodes)

    assert "akemi homura" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "black shoes" not in bundle.prompt.positive
    assert "kaname madoka" in bundle.prompt.positive
    assert "bare feet" in bundle.prompt.positive
    assert "pink hair" not in bundle.prompt.positive
    assert bundle.meta.extra["character_selection"]["source"] == "action_profile.yaml"
    assert bundle.meta.extra["character_materials"][0]["used_sections"] == ["character", "hair"]
    assert bundle.meta.extra["character_materials"][1]["used_sections"] == ["character", "feet"]


def test_selected_keys_always_include_identity_minimal_sections():
    character = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "role": ["magical girl"],
            "hair": ["black hair"],
            "eyes": ["purple eyes"],
            "upper_clothes": ["school uniform"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="nude_action",
        tags={"action": ["nude"]},
        composition={
            "character_selection": {
                "source": "run-prompt-prompt.md",
                "characters": [
                    {"selected_keys": ["hair", "eyes"]}
                ],
            }
        },
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "magical girl" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "purple eyes" in bundle.prompt.positive
    assert "school uniform" not in bundle.prompt.positive
    assert bundle.meta.composition.included_character_sections == [
        "character",
        "role",
        "hair",
        "eyes",
    ]


def test_selected_keys_use_character_identity_minimal_override():
    character = NodeDocument(
        kind="character",
        id="homura",
        identity_minimal=["character", "copyright"],
        tags={
            "character": ["akemi homura"],
            "copyright": ["puella magi madoka magica"],
            "role": ["magical girl"],
            "hair": ["black hair"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="nude_action",
        tags={"action": ["nude"]},
        composition={
            "character_selection": {
                "characters": [
                    {"selected_keys": ["hair"]}
                ],
            }
        },
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "puella magi madoka magica" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "magical girl" not in bundle.prompt.positive
    assert bundle.meta.composition.included_character_sections == [
        "character",
        "copyright",
        "hair",
    ]


def test_selected_keys_include_identity_minimal_prompt_fragment_roles():
    character = NodeDocument(
        kind="character",
        id="homura",
        prompt={
            "positive": [
                {"text": "akemi homura", "role": "character"},
                {"text": "magical girl", "role": "role"},
                {"text": "black hair", "role": "hair"},
                {"text": "purple eyes", "role": "eyes"},
                {"text": "school uniform", "role": "upper_clothes"},
            ],
        },
    )
    action = NodeDocument(
        kind="action",
        id="nude_action",
        tags={"action": ["nude"]},
        composition={
            "character_selection": {
                "characters": [
                    {"selected_keys": ["hair", "eyes"]}
                ],
            }
        },
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "magical girl" in bundle.prompt.positive
    assert "black hair" in bundle.prompt.positive
    assert "purple eyes" in bundle.prompt.positive
    assert "school uniform" not in bundle.prompt.positive


def test_character_scope_still_applies_without_selected_keys():
    character = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "hair": ["black hair"],
            "eyes": ["purple eyes"],
            "feet": ["black shoes"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="foot_action",
        character_scope="foot_detail",
        tags={"action": ["foot focus"]},
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert "akemi homura" in bundle.prompt.positive
    assert "black shoes" in bundle.prompt.positive
    assert "black hair" not in bundle.prompt.positive
    assert "purple eyes" not in bundle.prompt.positive


def test_default_scope_uses_identity_minimal_instead_of_all_character_tags():
    character = NodeDocument(
        kind="character",
        id="homura",
        tags={
            "character": ["akemi homura"],
            "role": ["magical girl"],
            "hair": ["black hair"],
            "eyes": ["purple eyes"],
            "feet": ["black shoes"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="standing",
        tags={"action": ["standing"]},
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert bundle.meta.composition.character_scope == "default"
    assert bundle.meta.composition.included_character_sections == ["character", "role"]
    assert "akemi homura" in bundle.prompt.positive
    assert "magical girl" in bundle.prompt.positive
    assert "standing" in bundle.prompt.positive
    assert "black hair" not in bundle.prompt.positive
    assert "purple eyes" not in bundle.prompt.positive
    assert "black shoes" not in bundle.prompt.positive


def test_character_identity_minimal_overrides_default_sections():
    character = NodeDocument(
        kind="character",
        id="homura",
        identity_minimal=["character", "copyright"],
        tags={
            "character": ["akemi homura"],
            "copyright": ["puella magi madoka magica"],
            "role": ["magical girl"],
            "hair": ["black hair"],
        },
    )
    action = NodeDocument(
        kind="action",
        id="unknown_scope_action",
        character_scope="unknown_scope",
        tags={"action": ["standing"]},
    )

    bundle = ScriptComposer().compose_nodes(character=character, action=action)

    assert bundle.meta.composition.character_scope == "unknown_scope"
    assert bundle.meta.composition.included_character_sections == ["character", "copyright"]
    assert "akemi homura" in bundle.prompt.positive
    assert "puella magi madoka magica" in bundle.prompt.positive
    assert "magical girl" not in bundle.prompt.positive
    assert "black hair" not in bundle.prompt.positive
