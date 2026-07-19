from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .index import ActionNodeIndex, normalize_relative_path, strip_phase_prefix
from .models import ActionEvidence, ResolvedAction
from .readers import read_image_evidence, read_task_evidence
from .scanner import GeneratedActionInputScanner


class GeneratedActionResolver:
    def __init__(self, index: ActionNodeIndex) -> None:
        self.index = index

    def resolve(self, evidence: ActionEvidence) -> ResolvedAction:
        if evidence.error:
            return ResolvedAction(evidence, "read_error", reason=evidence.error)
        if not evidence.action and not evidence.ref:
            return ResolvedAction(evidence, "missing_action", reason="输入中没有 Action 元数据")

        direct = self._resolve_direct_new_ref(evidence)
        if direct is not None:
            return direct

        category_relative = self._category_relative_from_ref(evidence.ref)
        if category_relative:
            manifest = self.index.manifest_by_dest(category_relative)
            resolved = self._resolve_candidates(
                evidence,
                manifest,
                reason="通过分类 ref 和 manifest.dest 映射到原始节点",
            )
            if resolved is not None:
                return resolved

        if evidence.topic and evidence.action:
            manifest = self.index.manifest_by_root_view(evidence.topic, evidence.action)
            resolved = self._resolve_candidates(
                evidence,
                manifest,
                reason="通过 topic/action 和 manifest 映射到原始节点",
            )
            if resolved is not None:
                return resolved

        manifest = self.index.manifest_by_view_or_name(evidence.action)
        resolved = self._resolve_candidates(
            evidence,
            manifest,
            reason="通过唯一 Action 名称和 manifest 映射到原始节点",
        )
        if resolved is not None:
            return resolved

        stripped = strip_phase_prefix(evidence.action)
        new_candidates = self.index.new_name_candidates(stripped)
        resolved = self._resolve_candidates(
            evidence,
            new_candidates,
            reason="去除阶段前缀后匹配到原始节点",
        )
        if resolved is not None:
            return resolved

        category_candidates = self._category_candidates(evidence, category_relative)
        if len(category_candidates) == 1:
            path = next(iter(category_candidates))
            return self._result(
                evidence,
                "category_fallback",
                path,
                "无法映射到 new 原始节点，返回实际分类目录",
            )
        if len(category_candidates) > 1:
            return ResolvedAction(
                evidence,
                "ambiguous",
                reason=f"找到多个分类目录候选：{_candidate_text(category_candidates)}",
            )
        return ResolvedAction(evidence, "unresolved", reason="没有找到原始节点或分类目录")

    def _resolve_direct_new_ref(self, evidence: ActionEvidence) -> ResolvedAction | None:
        if not evidence.ref:
            return None
        ref_path = Path(evidence.ref)
        if not ref_path.is_absolute():
            normalized = normalize_relative_path(evidence.ref)
            design_marker = "动作改2/new/"
            if normalized.startswith(design_marker):
                ref_path = self.index.design_root / Path(normalized)
            elif normalized.startswith("new/"):
                ref_path = self.index.action_root / Path(normalized)
            else:
                return None
        try:
            resolved = ref_path.resolve()
            resolved.relative_to(self.index.new_root)
        except (OSError, ValueError):
            return None
        if not resolved.is_dir():
            return None
        return self._result(evidence, "resolved_new", resolved, "Action ref 已指向原始节点")

    def _category_relative_from_ref(self, ref: str | None) -> str:
        if not ref:
            return ""
        ref_path = Path(ref)
        if ref_path.is_absolute():
            relative = self.index.relative_to_action_root(ref_path)
            return relative or ""
        normalized = normalize_relative_path(ref)
        marker = "动作改2/"
        if marker in normalized:
            return normalized.split(marker, 1)[1]
        return normalized

    def _category_candidates(
        self,
        evidence: ActionEvidence,
        category_relative: str,
    ) -> set[Path]:
        candidates: set[Path] = set()
        if category_relative:
            category_path = self.index.category_path(category_relative)
            if category_path is not None:
                candidates.add(category_path)
        candidates.update(self.index.category_candidates(evidence.topic, evidence.action))
        return candidates

    def _resolve_candidates(
        self,
        evidence: ActionEvidence,
        candidates: set[Path],
        *,
        reason: str,
    ) -> ResolvedAction | None:
        if len(candidates) == 1:
            return self._result(evidence, "resolved_new", next(iter(candidates)), reason)
        if len(candidates) > 1:
            return ResolvedAction(
                evidence,
                "ambiguous",
                reason=f"找到多个原始节点候选：{_candidate_text(candidates)}",
            )
        return None

    def _result(
        self,
        evidence: ActionEvidence,
        status: str,
        path: Path,
        reason: str,
    ) -> ResolvedAction:
        return ResolvedAction(
            evidence=evidence,
            status=status,
            relative_path=self.index.relative_to_design_root(path),
            absolute_path=path,
            reason=reason,
        )


def resolve_generated_actions(
    inputs: Sequence[str | Path],
    *,
    design_root: str | Path,
) -> list[ResolvedAction]:
    scan = GeneratedActionInputScanner().scan(inputs)
    resolver = GeneratedActionResolver(ActionNodeIndex(design_root))
    evidence: list[ActionEvidence] = []
    for source in scan.sources:
        if source.kind == "task":
            evidence.extend(read_task_evidence(source.path))
        else:
            evidence.append(read_image_evidence(source.path))
    for issue in scan.issues:
        evidence.append(
            ActionEvidence(
                input_path=issue.input_path,
                source_kind="input",
                source_detail="scanner",
                error=issue.error,
            )
        )
    return [resolver.resolve(item) for item in evidence]


def deduplicate_resolved_actions(results: Iterable[ResolvedAction]) -> list[ResolvedAction]:
    deduplicated: list[ResolvedAction] = []
    seen: set[tuple[str, str, str, str]] = set()
    for result in results:
        key = (
            result.status,
            result.relative_path,
            result.evidence.action,
            result.evidence.topic,
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(result)
    return deduplicated


def _candidate_text(candidates: set[Path]) -> str:
    return ", ".join(str(path) for path in sorted(candidates, key=lambda item: str(item)))
