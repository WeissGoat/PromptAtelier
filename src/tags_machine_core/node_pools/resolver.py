from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Callable

from .classify import MissingClassifyError, load_classify_tags
from .models import (
    CLASSIFY_FIELDS,
    CandidateNode,
    NodePoolSampleResult,
    NodePoolScanResult,
    NodePoolSpec,
    NodePoolStats,
    SampledNode,
)
from .selectors import NodePoolSelectorContext, expand_node_pool_source


NodeLoader = Callable[[str, str], dict[str, Any]]


class NodePoolResolver:
    def __init__(
        self,
        *,
        design_root: str | Path,
        collections: dict[str, dict[str, list[Any]]],
        node_loader: NodeLoader,
    ):
        self.design_root = Path(design_root).resolve()
        self.collections = collections
        self.node_loader = node_loader

    def scan(self, role: str, spec: NodePoolSpec) -> NodePoolScanResult:
        if spec.filters.classify.enabled() and role != "action":
            raise ValueError("classify.yaml filters are only supported for action random nodes")
        refs = expand_node_pool_source(
            role=role,
            source=spec.source,
            context=NodePoolSelectorContext(
                base_dir=self.design_root,
                collections=self.collections,
            ),
        )
        stats = NodePoolStats(raw_total=len(refs))
        warnings: list[str] = []
        candidates: list[CandidateNode] = []
        facets: dict[str, set[str]] = {field: set() for field in CLASSIFY_FIELDS}
        for raw_ref in refs:
            try:
                ref = self._resolve_ref(role, raw_ref)
                path = Path(ref)
                if not path.is_dir():
                    raise ValueError("node candidate is not a directory")
            except Exception as exc:
                stats.invalid_node += 1
                if len(warnings) < 50:
                    warnings.append(f"{raw_ref}: {exc}")
                continue

            if spec.filters.classify.enabled():
                try:
                    classify = load_classify_tags(Path(ref))
                except MissingClassifyError:
                    stats.missing_classify += 1
                    continue
                except Exception as exc:
                    stats.invalid_classify += 1
                    if len(warnings) < 50:
                        warnings.append(f"{ref}: {exc}")
                    continue
                for field, values in classify.items():
                    facets[field].update(values)
                if not _matches_classify(classify, spec):
                    stats.classify_mismatch += 1
                    continue

            candidates.append(CandidateNode(
                role=role,
                ref=ref,
                name=path.name,
                relative=self._relative(path),
            ))
        stats.total = len(candidates)
        return NodePoolScanResult(
            candidates=candidates,
            stats=stats,
            facets={field: sorted(values) for field, values in facets.items() if values},
            warnings=warnings,
        )

    def sample(
        self,
        role: str,
        spec: NodePoolSpec,
        count: int,
        *,
        rng: random.Random | None = None,
    ) -> NodePoolSampleResult:
        if count < 1:
            raise ValueError("sample count must be >= 1")
        scan = self.scan(role, spec)
        if not scan.candidates:
            raise ValueError("random node pool is empty")
        generator = rng or random.SystemRandom()
        result: list[SampledNode] = []
        cycle = 0
        previous_ref: str | None = None
        while len(result) < count:
            cycle += 1
            deck = list(scan.candidates)
            generator.shuffle(deck)
            if previous_ref and len(deck) > 1 and deck[0].ref == previous_ref:
                deck[0], deck[1] = deck[1], deck[0]
            added_this_cycle = 0
            for candidate in deck:
                if len(result) >= count:
                    break
                try:
                    response = self.node_loader(role, candidate.ref)
                    node = response.get("node") if isinstance(response, dict) else None
                    if not isinstance(node, dict):
                        raise ValueError("node loader returned no node document")
                    node_kind = str(node.get("kind") or "").strip()
                    if node_kind and node_kind not in {role, "unknown"}:
                        raise ValueError(f"node kind {node_kind!r} does not match role {role!r}")
                except Exception:
                    scan.stats.invalid_node += 1
                    continue
                result.append(SampledNode(
                    candidate=candidate,
                    node=node,
                    draw_index=len(result),
                    deck_cycle=cycle,
                ))
                previous_ref = candidate.ref
                added_this_cycle += 1
            if added_this_cycle == 0:
                raise ValueError("random node pool has no readable nodes")
        return NodePoolSampleResult(items=result, stats=scan.stats)

    def _resolve_ref(self, role: str, raw_ref: str) -> str:
        path = Path(raw_ref)
        if not path.is_absolute():
            if role == "artist":
                roots = ("画风", "artist", "artists")
                matches = [self.design_root / root / path for root in roots]
                path = next((item for item in matches if item.exists()), matches[0])
            else:
                path = self.design_root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.design_root)
        except ValueError as exc:
            raise ValueError("node pool candidate must be inside design_root") from exc
        return str(resolved)

    def _relative(self, path: Path) -> str | None:
        try:
            return path.resolve().relative_to(self.design_root).as_posix()
        except ValueError:
            return None


def _matches_classify(classify: dict[str, set[str]], spec: NodePoolSpec) -> bool:
    requested = spec.filters.classify
    for field in CLASSIFY_FIELDS:
        values = set(getattr(requested, field))
        if values and not (classify.get(field, set()) & values):
            return False
    return True
