from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from tags_machine_core import cli
from tags_machine_core.batch.models import BatchSpec
from tags_machine_core.batch.paths import resolve_batch_output_path
from tags_machine_core.web.services.batch_workspace import BatchWorkspace


def test_resolve_batch_output_path_expands_date() -> None:
    now = datetime(2026, 7, 12, 23, 59, 59)

    result = resolve_batch_output_path("G:/ai_auto/{date}", now=now)

    assert result == Path("G:/ai_auto/20260712")


def test_resolve_batch_output_path_keeps_plain_path() -> None:
    assert resolve_batch_output_path("G:/ai_auto/fixed") == Path("G:/ai_auto/fixed")


def test_cli_batch_output_dir_expands_spec_date(tmp_path: Path) -> None:
    spec = BatchSpec(name="daily", output_dir=str(tmp_path / "{date}"))

    result = cli._batch_output_dir(
        spec,
        spec_path=tmp_path / "batch.yaml",
        run_dir=tmp_path / "work",
    )

    assert result.parent == tmp_path
    assert re.fullmatch(r"\d{8}", result.name)


def test_cli_batch_output_dir_expands_override_date(tmp_path: Path) -> None:
    spec = BatchSpec(name="daily", output_dir=str(tmp_path / "ignored"))

    result = cli._batch_output_dir(
        spec,
        spec_path=tmp_path / "batch.yaml",
        run_dir=tmp_path / "work",
        override=str(tmp_path / "override" / "{date}"),
    )

    assert result.parent == tmp_path / "override"
    assert re.fullmatch(r"\d{8}", result.name)


def test_web_batch_output_dir_uses_same_date_template(tmp_path: Path) -> None:
    workspace = BatchWorkspace(base_dir=tmp_path)
    spec = BatchSpec(name="daily", output_dir=str(tmp_path / "{date}"))

    result = workspace._output_dir(
        spec,
        data={},
        spec_path=tmp_path / "batch.yaml",
        run_dir=tmp_path / "work",
    )

    assert result.parent == tmp_path
    assert re.fullmatch(r"\d{8}", result.name)
