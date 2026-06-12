from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def write_report(
    run_dir: str | Path,
    entries: list[dict[str, Any]],
    *,
    markdown: bool = True,
    json_report: bool = True,
) -> dict[str, Any]:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    counts = Counter(str(entry.get("status") or "unknown") for entry in entries)
    data = {
        "schema": "tags-machine-core.batch-report/v1",
        "run_dir": str(root),
        "counts": dict(counts),
        "entries": entries,
    }
    if json_report:
        (root / "report.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if markdown:
        (root / "report.md").write_text(_markdown_report(data), encoding="utf-8")
    return data


def _markdown_report(data: dict[str, Any]) -> str:
    lines = [
        "# Batch Generation Report",
        "",
        f"- run_dir: `{data['run_dir']}`",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(data["counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Tasks",
            "",
            "| Task | Status | Images | Error | Visual Result |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for entry in data["entries"]:
        images = "<br>".join(str(path) for path in entry.get("image_paths") or [])
        error = str(entry.get("error") or "")
        lines.append(
            f"| `{entry.get('task_id')}` | {entry.get('status')} | {images} | {error} | pending |"
        )
    lines.append("")
    return "\n".join(lines)
