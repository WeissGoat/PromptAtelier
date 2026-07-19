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
    include_prompt_preview: bool = True,
    include_png_params_summary: bool = True,
    visual_check_template: bool = True,
    action_group_summary: dict[str, Any] | None = None,
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
    if action_group_summary and action_group_summary.get("rounds"):
        data["action_groups"] = action_group_summary
    if json_report:
        (root / "report.json").write_text(
            json.dumps(
                _filtered_report_data(
                    data,
                    include_prompt_preview=include_prompt_preview,
                    include_png_params_summary=include_png_params_summary,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if markdown:
        (root / "report.md").write_text(
            _markdown_report(
                data,
                include_prompt_preview=include_prompt_preview,
                include_png_params_summary=include_png_params_summary,
                visual_check_template=visual_check_template,
            ),
            encoding="utf-8",
        )
    return data


def _markdown_report(
    data: dict[str, Any],
    *,
    include_prompt_preview: bool,
    include_png_params_summary: bool,
    visual_check_template: bool,
) -> str:
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
    action_groups = data.get("action_groups") or {}
    if action_groups:
        lines.extend(["", "## Action Groups", "", f"- rounds: {action_groups.get('rounds', 0)}"])
        for character, count in sorted((action_groups.get("characters") or {}).items()):
            lines.append(f"- character `{character}`: {count} rounds")
        lines.extend(["", "| Group | Selected | Completed | Failed |", "| --- | ---: | ---: | ---: |"])
        for group, counts in sorted((action_groups.get("groups") or {}).items()):
            lines.append(
                f"| `{group}` | {counts.get('selected', 0)} | "
                f"{counts.get('completed', 0)} | {counts.get('failed', 0)} |"
            )
    lines.extend(
        [
            "",
            "## Tasks",
            "",
            (
                "| Task | Status | Images | Error | Visual Result |"
                if visual_check_template
                else "| Task | Status | Images | Error |"
            ),
            (
                "| --- | --- | --- | --- | --- |"
                if visual_check_template
                else "| --- | --- | --- | --- |"
            ),
        ]
    )
    for entry in data["entries"]:
        images = "<br>".join(str(path) for path in entry.get("image_paths") or [])
        error = str(entry.get("error") or "")
        prompt = str(entry.get("prompt_preview") or "") if include_prompt_preview else ""
        png_summary = (
            entry.get("png_params_summary") or {}
            if include_png_params_summary
            else {}
        )
        detail = []
        if prompt:
            detail.append(f"prompt: `{_escape_table(prompt)}`")
        if png_summary:
            detail.append(f"png: `{json.dumps(png_summary, ensure_ascii=False)}`")
        if entry.get("retry_records"):
            detail.append(f"retry: `{json.dumps(entry['retry_records'], ensure_ascii=False)}`")
        source_detail = _source_detail(entry.get("source") or {})
        if source_detail:
            detail.append(f"source: `{_escape_table(source_detail)}`")
        if detail:
            error = "<br>".join([item for item in [error, *detail] if item])
        if visual_check_template:
            lines.append(
                f"| `{entry.get('task_id')}` | {entry.get('status')} | {images} | {error} | pending |"
            )
        else:
            lines.append(f"| `{entry.get('task_id')}` | {entry.get('status')} | {images} | {error} |")
    lines.append("")
    return "\n".join(lines)


def _filtered_report_data(
    data: dict[str, Any],
    *,
    include_prompt_preview: bool,
    include_png_params_summary: bool,
) -> dict[str, Any]:
    entries = []
    for entry in data["entries"]:
        item = dict(entry)
        if not include_prompt_preview:
            item.pop("prompt_preview", None)
        if not include_png_params_summary:
            item.pop("png_params_summary", None)
        entries.append(item)
    return {**data, "entries": entries}


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")[:300]


def _source_detail(source: dict[str, Any]) -> str:
    if not source:
        return ""
    parts = []
    for key in ("character", "action_group", "action", "artist"):
        value = source.get(key)
        if value is None:
            continue
        text = Path(str(value)).name if key in {"character", "action"} else str(value)
        parts.append(f"{key}={text}")
    return ", ".join(parts)
