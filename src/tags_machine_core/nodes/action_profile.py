from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class CharacterSelectionEntry(BaseModel):
    selected_keys: list[str] = Field(default_factory=list)

    @field_validator("selected_keys", mode="before")
    @classmethod
    def normalize_selected_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


class CharacterSelectionProfile(BaseModel):
    source: str | None = None
    default_selected_keys: list[str] = Field(default_factory=list)
    characters: list[CharacterSelectionEntry] = Field(default_factory=list)

    @field_validator("default_selected_keys", mode="before")
    @classmethod
    def normalize_default_selected_keys(cls, value: Any) -> list[str]:
        return CharacterSelectionEntry.normalize_selected_keys(value)


class ActionProfile(BaseModel):
    schema_id: str = "tags-machine.action-profile/v1"
    character_selection: CharacterSelectionProfile = Field(
        default_factory=CharacterSelectionProfile
    )
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_node_composition(self) -> dict[str, Any]:
        return {
            "character_selection": self.character_selection.model_dump(
                mode="json",
                exclude_none=True,
            )
        }


def load_action_profile(node_dir: str | Path) -> ActionProfile | None:
    node_dir = Path(node_dir)
    profile_yaml = node_dir / "action_profile.yaml"
    if profile_yaml.exists():
        data = _read_yaml_mapping(profile_yaml)
        selection_data = data.get("character_selection") or {}
        if not isinstance(selection_data, dict):
            selection_data = {}
        selection_data = {
            **selection_data,
            "source": selection_data.get("source") or profile_yaml.name,
        }
        return ActionProfile(
            schema_id=str(
                data.get("schema") or data.get("schema_id") or "tags-machine.action-profile/v1"
            ),
            character_selection=CharacterSelectionProfile.model_validate(selection_data),
            raw=data,
        )

    prompt_md = node_dir / "run-prompt-prompt.md"
    if prompt_md.exists():
        data = _read_markdown_front_matter(prompt_md)
        if data is None:
            return None
        characters = data.get("characters") or []
        if not isinstance(characters, list):
            characters = []
        return ActionProfile(
            character_selection=CharacterSelectionProfile(
                source=prompt_md.name,
                characters=[
                    CharacterSelectionEntry.model_validate(item)
                    for item in characters
                    if isinstance(item, dict)
                ],
            ),
            raw=data,
        )

    return None


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return data


def _read_markdown_front_matter(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None
    yaml_text = "\n".join(lines[1:end_index])
    data = yaml.safe_load(yaml_text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML front matter mapping: {path}")
    return data
