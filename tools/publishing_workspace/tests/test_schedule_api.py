from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from publishing_workspace.config import init_workspace
from publishing_workspace.plans.service import ScheduleService
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
