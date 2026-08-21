from __future__ import annotations

import pytest
from pydantic import ValidationError

from publishing_workspace.submissions.models import (
    Submission,
    SubmissionDetail,
    SubmissionScheduleRef,
    SubmissionSummary,
)


def test_submission_fills_post_and_cover_from_all():
    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        sets={"all": ["sha256:a", "sha256:b"], "post": [], "cover": []},
    )

    assert submission.sets["post"] == ["sha256:a", "sha256:b"]
    assert submission.sets["cover"] == ["sha256:a"]


def test_submission_deduplicates_items_preserving_order():
    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        sets={
            "all": ["sha256:a", "sha256:b", "sha256:a", "sha256:c"],
            "post": ["sha256:b", "sha256:b"],
            "cover": ["sha256:b"],
        },
    )

    assert submission.sets["all"] == ["sha256:a", "sha256:b", "sha256:c"]
    assert submission.sets["post"] == ["sha256:b"]
    assert submission.sets["cover"] == ["sha256:b"]


def test_submission_rejects_unknown_selection_name():
    with pytest.raises(ValidationError):
        Submission(
            submission_id="task-1",
            task_id="task-1",
            title="测试投稿",
            sets={"all": ["sha256:a"], "extra": ["sha256:b"]},  # type: ignore[dict-item]
        )


def test_submission_rejects_mismatched_task_and_submission_id():
    with pytest.raises(ValidationError):
        Submission(
            submission_id="task-1",
            task_id="task-2",
            title="测试投稿",
            sets={"all": ["sha256:a"]},
        )


def test_submission_normalizes_empty_source_import_id():
    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        source_import_id="   ",
        sets={"all": ["sha256:a"]},
    )
    assert submission.source_import_id is None


def test_submission_detail_and_summary():
    detail = SubmissionDetail(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        sets={"all": ["sha256:a"]},
        warnings=["测试告警"],
        unresolved_files=["missing.png"],
    )
    assert detail.warnings == ["测试告警"]
    assert detail.unresolved_files == ["missing.png"]

    ref = SubmissionScheduleRef(
        plan_id="2026-08",
        entry_id="entry-1",
        scheduled_at="2026-08-25T10:00:00+08:00",
    )
    summary = SubmissionSummary(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        counts={"all": 1, "post": 1, "cover": 1},
        updated_at="2026-08-21T10:00:00Z",
        scheduled_entries=[ref],
    )
    assert summary.counts["all"] == 1
    assert len(summary.scheduled_entries) == 1
