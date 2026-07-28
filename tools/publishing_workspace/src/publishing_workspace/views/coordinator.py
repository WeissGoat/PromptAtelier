from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..catalog.repository import CatalogRepository
from ..logging import get_logger
from ..models import ExportPlan, ExporterResult, ExportSummary
from .exporters import ViewExporter


logger = get_logger(__name__)


class ViewExportCoordinator:
    def __init__(self, catalog: CatalogRepository):
        self.catalog = catalog

    def export(
        self,
        plan: ExportPlan,
        jobs: list[tuple[ViewExporter, Path]],
    ) -> ExportSummary:
        results = [self._export_one(plan, exporter, root) for exporter, root in jobs]
        return ExportSummary(plan_views=len(plan.views), results=results)

    def _export_one(
        self,
        plan: ExportPlan,
        exporter: ViewExporter,
        target_root: Path,
    ) -> ExporterResult:
        root = target_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        state_key = _state_key(exporter, root)
        previous = self.catalog.read_export_states(state_key)
        current: dict[str, dict[str, Any]] = {}
        written = 0
        skipped = 0
        removed = 0

        seen_outputs: dict[str, str] = {}
        for view in plan.views:
            view_key = view.key
            content_hash = _view_hash(view.model_dump(mode="json"), exporter)
            expected = [str(path.resolve()) for path in exporter.output_paths(view, root)]
            _assert_outputs_in_root(expected, root)
            for output in expected:
                other = seen_outputs.setdefault(output.casefold(), view_key)
                if other != view_key:
                    raise ValueError(
                        f"分类名称清理后发生输出路径冲突：{other} 与 {view_key} -> {output}"
                    )
            previous_state = previous.get(view_key)
            if (
                previous_state
                and previous_state["content_hash"] == content_hash
                and all(Path(path).exists() for path in expected)
            ):
                outputs = expected
                skipped += 1
            else:
                outputs = [str(path.resolve()) for path in exporter.export_view(view, root)]
                written += 1
                logger.info("Publishing 视图已导出 exporter=%s view=%s", exporter.type, view_key)
            current[view_key] = {"content_hash": content_hash, "outputs": outputs}

        current_outputs = {
            path.casefold()
            for state in current.values()
            for path in state.get("outputs", [])
        }
        for state in previous.values():
            for output_value in state.get("outputs", []):
                output = Path(output_value)
                if str(output).casefold() in current_outputs or not output.exists():
                    continue
                _assert_path_in_root(output, root)
                if output.is_file() or output.is_symlink():
                    output.unlink()
                    removed += 1
                    _remove_empty_parents(output.parent, root)

        self.catalog.replace_export_states(state_key, current)
        return ExporterResult(
            exporter=exporter.type,
            written=written,
            skipped=skipped,
            removed=removed,
            output_root=str(root),
        )


def _view_hash(data: dict[str, Any], exporter: ViewExporter) -> str:
    payload = {
        "exporter": exporter.type,
        "version": exporter.version,
        "view": data,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state_key(exporter: ViewExporter, root: Path) -> str:
    root_hash = hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()[:16]
    return f"{exporter.type}:{root_hash}"


def _assert_outputs_in_root(outputs: list[str], root: Path) -> None:
    for output in outputs:
        _assert_path_in_root(Path(output), root)


def _assert_path_in_root(path: Path, root: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Exporter 输出越过目标目录：{resolved}") from exc


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
