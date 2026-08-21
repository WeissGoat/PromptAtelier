from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from publishing_workspace.config import init_workspace
from publishing_workspace.plans.service import ScheduleService
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository
from publishing_workspace.web.schedule_api import create_app


def entry_payload(entry_id: str = "entry-1") -> dict:
    return {
        "revision": 1,
        "entry": {
            "entry_id": entry_id,
            "scheduled_at": "2026-09-05T20:00:00+08:00",
            "title": "API 测试",
            "content": {"kind": "inline_selection", "sets": {"all": [], "post": ["sha256:a"], "cover": []}},
        },
    }


def client_for(root: Path) -> TestClient:
    init_workspace(root)
    ScheduleService().create_plan(root, "2026-09")
    return TestClient(create_app(root))


def test_plan_api_returns_revision_and_entries(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.get("/api/plans/2026-09")

    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert response.json()["entries"] == []


def test_plan_api_get_creates_missing_month(tmp_path: Path):
    init_workspace(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/plans/2026-10")

    assert response.status_code == 200
    assert response.json()["month"] == "2026-10"
    assert response.json()["status"] == "draft"
    assert (tmp_path / "plans" / "2026-10" / "plan.yaml").is_file()


def test_plan_api_adds_and_moves_entry(tmp_path: Path):
    client = client_for(tmp_path)

    created = client.post("/api/plans/2026-09/entries", json=entry_payload())
    assert created.status_code == 200
    assert created.json()["revision"] == 2

    moved = client.patch(
        "/api/plans/2026-09/entries/entry-1/date",
        json={"revision": 2, "target_date": "2026-09-08"},
    )
    assert moved.status_code == 200
    assert moved.json()["entries"][0]["scheduled_at"].startswith("2026-09-08")


def test_plan_api_returns_409_for_stale_revision(tmp_path: Path):
    client = client_for(tmp_path)
    client.post("/api/plans/2026-09/entries", json=entry_payload())

    response = client.post(
        "/api/plans/2026-09/lock",
        json={"revision": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_revision_conflict"


def test_asset_search_api_returns_empty_result_for_empty_catalog(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.get("/api/assets/search", params={"limit": 10})

    assert response.status_code == 200
    assert response.json() == []


def test_asset_search_api_accepts_subtype_facet(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.get(
        "/api/assets/search",
        params={"facets": json.dumps({"subtype": ["kiss"]})},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_node_search_api_returns_paginated_candidates(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.get(
        "/api/nodes",
        params={"role": "character", "q": "hom", "offset": 0, "limit": 20},
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema": "publishing-workspace.web.node-list/v1",
        "role": "character",
        "nodes": [],
        "offset": 0,
        "limit": 20,
        "has_more": False,
    }


def test_schedule_api_serves_static_calendar(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "月度投稿计划" in response.text
    assert "classify.yaml 二次过滤" in response.text
    assert "添加筛选" in response.text
    assert "Subtype" in response.text
    assert "创建空计划" not in response.text
    assert "锁定计划" not in response.text


def test_schedule_api_lists_existing_tasks(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    TaskRepository.create(TaskPaths.from_workspace(paths, "demo-task"), title="演示任务")
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json() == [{"task_id": "demo-task", "title": "演示任务"}]
