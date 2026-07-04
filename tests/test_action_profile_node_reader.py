from pathlib import Path

from tags_machine_core.nodes.reader import NodeReader


def test_reader_attaches_action_profile_from_run_prompt_prompt(tmp_path: Path):
    action_dir = tmp_path / "foot_action"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("foot focus, soles\n", encoding="utf-8")
    (action_dir / "run-prompt-prompt.md").write_text(
        """
---
characters:
  - selected_keys:
      - character
      - copyright
      - feet
---
""".strip(),
        encoding="utf-8",
    )

    node = NodeReader().read(action_dir)

    selection = node.composition["character_selection"]
    assert selection["source"] == "run-prompt-prompt.md"
    assert selection["characters"][0]["selected_keys"] == [
        "character",
        "copyright",
        "feet",
    ]
