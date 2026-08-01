from __future__ import annotations

from pathlib import Path

from PIL import Image

from publishing_workspace.catalog import CatalogRepository
from publishing_workspace.catalog.repository import normalize_path_key
from publishing_workspace.importing import ImportRunRepository
from publishing_workspace.importing.planner import ImportPlanner
from publishing_workspace.models import ImportedItem, SelectionSet, utc_now_iso
from publishing_workspace.problems import ProblemRepository


def _prepare(tmp_path: Path, path: Path | None):
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    run = runs.create_run(
        source_type="directory",
        source_ref=str(tmp_path),
        mode="import",
        strict=False,
    )
    source = path or (tmp_path / "missing.png")
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(tmp_path),
            items=[
                ImportedItem(
                    source_path=str(source),
                    resolved_path=str(path) if path else None,
                    source_type="directory",
                    source_ref=str(tmp_path),
                    source_order=0,
                    display_name=source.name,
                )
            ],
        ),
    )
    return catalog, runs, problems, run.import_id


def test_planner_marks_missing_and_empty(tmp_path: Path):
    missing_catalog, missing_runs, missing_problems, missing_run = _prepare(
        tmp_path / "missing", None
    )
    empty = tmp_path / "empty" / "empty.png"
    empty.parent.mkdir(parents=True)
    empty.touch()
    empty_catalog, empty_runs, empty_problems, empty_run = _prepare(
        tmp_path / "empty-case", empty
    )

    ImportPlanner(
        missing_catalog,
        missing_runs,
        missing_problems,
    ).plan(missing_run)
    ImportPlanner(empty_catalog, empty_runs, empty_problems).plan(empty_run)

    assert missing_runs.get_item(missing_run, 0).decision == "missing_path"
    assert missing_runs.get_item(missing_run, 0).problem_id
    assert empty_runs.get_item(empty_run, 0).decision == "empty_file"
    assert empty_problems.list(status="open")[0].error_code == "empty_file"


def test_planner_uses_path_cache_without_parsing(tmp_path: Path):
    path = tmp_path / "cached.png"
    Image.new("RGB", (1, 1), "white").save(path)
    catalog, runs, problems, run_id = _prepare(tmp_path / "cached-case", path)
    stat = path.stat()
    with catalog.connection() as connection:
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sha256:cached",
                "cached",
                stat.st_size,
                1,
                1,
                "PNG",
                "unknown",
                "unknown",
                "[]",
                utc_now_iso(),
                utc_now_iso(),
            ),
        )
        connection.execute(
            "INSERT INTO asset_paths VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                normalize_path_key(path),
                str(path.resolve()),
                "sha256:cached",
                stat.st_size,
                stat.st_mtime_ns,
                utc_now_iso(),
            ),
        )

    ImportPlanner(catalog, runs, problems).plan(run_id)
    assert runs.get_item(run_id, 0).decision == "reuse_path"
    assert runs.get_item(run_id, 0).problem_id is None


def test_same_problem_is_held_unless_retry_is_forced(tmp_path: Path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not-an-image")
    catalog, runs, problems, run_id = _prepare(tmp_path / "problem-case", path)
    item = runs.get_item(run_id, 0)
    stat = path.stat()
    with catalog.connection() as connection:
        problem = problems.record(
            connection,
            run_id=run_id,
            item=item,
            path_key=normalize_path_key(path),
            error_code="unreadable_image",
            message="cannot identify image",
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
    ImportPlanner(catalog, runs, problems).plan(run_id)
    held = runs.get_item(run_id, 0)
    assert held.decision == "hold_problem"
    assert held.problem_id == problem.problem_id

    retry_catalog, retry_runs, retry_problems, retry_run = _prepare(
        tmp_path / "retry-case", path
    )
    retry_item = retry_runs.get_item(retry_run, 0)
    with retry_catalog.connection() as connection:
        retry_problems.record(
            connection,
            run_id=retry_run,
            item=retry_item,
            path_key=normalize_path_key(path),
            error_code="unreadable_image",
            message="cannot identify image",
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
    ImportPlanner(retry_catalog, retry_runs, retry_problems).plan(
        retry_run, retry_failed=True
    )
    assert retry_runs.get_item(retry_run, 0).decision == "parse"
