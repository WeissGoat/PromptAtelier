from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
CLAUDE_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


def _skill_dirs(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        entry.name: entry
        for entry in sorted(root.iterdir(), key=lambda p: p.name)
        if entry.is_dir() and not entry.name.startswith(".")
    }


def _parse_skill_md(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", f"Missing YAML frontmatter start in {path}"
    end_idx = next(
        (idx for idx in range(1, len(lines)) if lines[idx].strip() == "---"),
        None,
    )
    assert end_idx is not None, f"Missing YAML frontmatter end in {path}"
    frontmatter = yaml.safe_load("\n".join(lines[1:end_idx]))
    assert isinstance(frontmatter, dict), f"Frontmatter must be a mapping in {path}"
    body = "\n".join(lines[end_idx + 1 :]).strip()
    return frontmatter, body


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def test_project_skills_stay_synced_with_claude_pointers() -> None:
    agents_skills = _skill_dirs(AGENTS_SKILLS_DIR)
    claude_skills = _skill_dirs(CLAUDE_SKILLS_DIR)

    assert agents_skills, "Expected at least one project skill under .agents/skills"
    assert set(claude_skills) == set(agents_skills), (
        f".claude/skills mismatch: only_in_claude={sorted(set(claude_skills) - set(agents_skills))}, "
        f"only_in_agents={sorted(set(agents_skills) - set(claude_skills))}"
    )

    for name, agents_dir in agents_skills.items():
        claude_dir = claude_skills[name]
        agents_md = agents_dir / "SKILL.md"
        claude_md = claude_dir / "SKILL.md"

        assert agents_md.is_file(), f"Missing {agents_md}"
        assert claude_md.is_file(), f"Missing {claude_md}"

        claude_entries = [entry.name for entry in claude_dir.iterdir()]
        assert claude_entries == ["SKILL.md"], (
            f"{claude_dir} must only contain pointer SKILL.md, found: {claude_entries}"
        )

        agents_fm, _ = _parse_skill_md(agents_md)
        claude_fm, claude_body = _parse_skill_md(claude_md)

        assert agents_fm.get("name") == name
        assert claude_fm.get("name") == name
        assert _normalize_text(claude_fm.get("description")) == _normalize_text(
            agents_fm.get("description")
        ), f"Description drift between .agents and .claude for skill {name!r}"

        expected_target = f".agents/skills/{name}/SKILL.md"
        assert expected_target in claude_body, (
            f"{claude_md} must point to {expected_target!r}"
        )
