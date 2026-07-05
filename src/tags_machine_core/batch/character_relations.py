from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.reader import NodeReader


@dataclass(frozen=True)
class CharacterCandidate:
    ref: str
    node: NodeDocument


def detect_required_girl_count(action: NodeDocument | None) -> int:
    if action is None:
        return 1
    text = ", ".join(_positive_texts(action)).lower()
    counts = [int(match.group(1)) for match in re.finditer(r"\b(\d+)\s*girls?\b", text)]
    if counts:
        return max(counts)
    if re.search(r"\bmultiple\s+girls?\b", text):
        return 2
    return 1


def resolve_cp_character_refs(
    *,
    main_ref: str,
    main_character: NodeDocument,
    candidate_refs: list[str],
    reader: NodeReader | None = None,
    required_count: int,
    allow_fill_missing_from_candidates: bool = False,
) -> tuple[list[str], dict[str, int | bool]] | None:
    if required_count <= 1:
        return [main_ref], {"cp_fallback_from_candidates": False, "cp_fallback_count": 0}
    cp_values = main_character.relations.get("cp") or []

    reader = reader or NodeReader()
    candidates = [
        CharacterCandidate(ref=ref, node=reader.read(ref))
        for ref in candidate_refs
        if str(ref) != str(main_ref)
    ]
    resolved: list[str] = [main_ref]
    selected_keys = _candidate_keys(CharacterCandidate(ref=main_ref, node=main_character))
    for cp_value in cp_values:
        candidate = _match_candidate(cp_value, candidates)
        if candidate is None or _has_selected_key(candidate, selected_keys):
            continue
        resolved.append(candidate.ref)
        selected_keys.update(_candidate_keys(candidate))
        if len(resolved) >= required_count:
            return resolved, {"cp_fallback_from_candidates": False, "cp_fallback_count": 0}

    fallback_count = 0
    if allow_fill_missing_from_candidates and cp_values:
        for candidate in candidates:
            if _has_selected_key(candidate, selected_keys):
                continue
            resolved.append(candidate.ref)
            selected_keys.update(_candidate_keys(candidate))
            fallback_count += 1
            if len(resolved) >= required_count:
                return resolved, {
                    "cp_fallback_from_candidates": fallback_count > 0,
                    "cp_fallback_count": fallback_count,
                }
    return None


def _positive_texts(node: NodeDocument) -> list[str]:
    if node.prompt.positive:
        return node.positive_texts()
    return node.all_tags()


def _match_candidate(
    cp_value: str,
    candidates: list[CharacterCandidate],
) -> CharacterCandidate | None:
    normalized = _normalize_key(cp_value)
    if not normalized:
        return None
    for candidate in candidates:
        if normalized == _normalize_key(candidate.ref):
            return candidate
        if normalized == _normalize_key(Path(candidate.ref).name):
            return candidate
        if normalized == _normalize_key(candidate.node.id):
            return candidate
        if normalized == _normalize_key(candidate.node.character_id or ""):
            return candidate
        for tag in candidate.node.tags.get("character", []):
            if normalized == _normalize_key(tag):
                return candidate
    return None


def _normalize_key(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _candidate_keys(candidate: CharacterCandidate) -> set[str]:
    values = {
        candidate.ref,
        Path(candidate.ref).name,
        candidate.node.id,
        candidate.node.character_id or "",
        *candidate.node.tags.get("character", []),
    }
    return {normalized for value in values if (normalized := _normalize_key(value))}


def _has_selected_key(candidate: CharacterCandidate, selected_keys: set[str]) -> bool:
    return bool(_candidate_keys(candidate) & selected_keys)
