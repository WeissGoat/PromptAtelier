from pathlib import Path

from tags_machine_core.nodes.action_profile import load_action_profile


def test_load_action_profile_yaml_selected_keys(tmp_path: Path):
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    (action_dir / "action_profile.yaml").write_text(
        """
schema: tags-machine.action-profile/v1
character_selection:
  source: action_profile.yaml
  default_selected_keys:
    - character
    - copyright
  characters:
    - selected_keys:
        - character
        - hair
    - selected_keys:
        - character
        - feet
""".strip(),
        encoding="utf-8",
    )

    profile = load_action_profile(action_dir)

    assert profile is not None
    assert profile.character_selection.source == "action_profile.yaml"
    assert profile.character_selection.default_selected_keys == ["character", "copyright"]
    assert profile.character_selection.characters[0].selected_keys == ["character", "hair"]
    assert profile.character_selection.characters[1].selected_keys == ["character", "feet"]


def test_load_action_profile_from_run_prompt_prompt_front_matter(tmp_path: Path):
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    (action_dir / "run-prompt-prompt.md").write_text(
        """
---
schema_version: 1
characters:
  - selected_keys:
      - character
      - copyright
      - hair
  - selected_keys:
      - character
      - copyright
      - feet
---

正文不参与解析。
""".strip(),
        encoding="utf-8",
    )

    profile = load_action_profile(action_dir)

    assert profile is not None
    assert profile.character_selection.source == "run-prompt-prompt.md"
    assert profile.character_selection.characters[0].selected_keys == [
        "character",
        "copyright",
        "hair",
    ]
    assert profile.character_selection.characters[1].selected_keys == [
        "character",
        "copyright",
        "feet",
    ]


def test_load_action_profile_returns_none_when_missing(tmp_path: Path):
    assert load_action_profile(tmp_path) is None
