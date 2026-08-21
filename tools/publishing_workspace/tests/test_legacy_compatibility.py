from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from publishing_workspace.config import init_workspace
from publishing_workspace.catalog.repository import CatalogRepository
from publishing_workspace.metadata import default_image_node_reader_registry
from publishing_workspace.models import ImportedItem, SelectionSet
from publishing_workspace.packages.builder import PackageBuilder
from publishing_workspace.png_metadata import read_png_text_chunks
from publishing_workspace.plans.models import (
    InlineContent,
    MonthlyPlan,
    ScheduleEntry,
    TaskContent,
)
from publishing_workspace.plans.paths import PlanPaths
from publishing_workspace.plans.repository import PlanRepository
from publishing_workspace.tasks import TaskConfig, TaskPaths, TaskRepository
from publishing_workspace.web.schedule_api import create_app


def _make_image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    return path


def _seed_catalog(root: Path) -> tuple[Path, str, list[str]]:
    paths, _, _ = init_workspace(root)
    img_a = _make_image(root / "source" / "a.png", "red")
    img_b = _make_image(root / "source" / "b.png", "blue")

    selection = SelectionSet(
        id="import-1",
        source_type="directory",
        source_ref=str(root / "source"),
        items=[
            ImportedItem(
                source_path=str(img_a),
                resolved_path=str(img_a),
                source_type="directory",
                source_ref=str(root / "source"),
                source_order=0,
                display_name=img_a.name,
            ),
            ImportedItem(
                source_path=str(img_b),
                resolved_path=str(img_b),
                source_type="directory",
                source_ref=str(root / "source"),
                source_order=1,
                display_name=img_b.name,
            ),
        ],
    )
    catalog_repo = CatalogRepository(paths.catalog)
    catalog_repo.import_selection(
        selection,
        readers=default_image_node_reader_registry(),
        enrichers=[],
    )
    imported = catalog_repo.assets_for_import("import-1")
    asset_ids = [item.asset_id for item in imported]
    return paths.root, "import-1", asset_ids


def test_legacy_task_without_submission_yaml_is_listed(tmp_path: Path):
    root, import_id, asset_ids = _seed_catalog(tmp_path)
    paths, _, _ = init_workspace(root)

    # 创建一个没有 submission.yaml 的旧任务
    task_paths = TaskPaths.from_workspace(paths, "legacy-task-1")
    TaskRepository.create(task_paths, title="旧格式任务")
    img = root / "source" / "a.png"
    (task_paths.selection_dirs["all"] / "0001_a.png").write_bytes(img.read_bytes())
    (task_paths.selection_dirs["post"] / "0001_a.png").write_bytes(img.read_bytes())
    (task_paths.selection_dirs["cover"] / "0001_a.png").write_bytes(img.read_bytes())

    assert not task_paths.submission_yaml.exists()

    with TestClient(create_app(root)) as client:
        # 1. 确认在 /api/submissions 中列出
        list_resp = client.get("/api/submissions")
        assert list_resp.status_code == 200
        summaries = list_resp.json()
        assert any(s["task_id"] == "legacy-task-1" for s in summaries)

        # 2. 确认详情可读
        get_resp = client.get("/api/submissions/legacy-task-1")
        assert get_resp.status_code == 200
        detail = get_resp.json()
        assert detail["task_id"] == "legacy-task-1"
        assert len(detail["sets"]["all"]) >= 1

    # 3. 确认仍能直接调用 PackageBuilder 打包
    build_result = PackageBuilder().build(root, "legacy-task-1")
    assert build_result.output_paths["all"].is_dir()
    assert (build_result.build_root / "build_manifest.json").is_file()


def test_legacy_inline_plan_remains_readable_and_movable(tmp_path: Path):
    root, _, asset_ids = _seed_catalog(tmp_path)
    paths, _, _ = init_workspace(root)

    plan_paths = PlanPaths.from_workspace(paths, "2026-08")
    plan = PlanRepository().create(plan_paths)
    plan.entries.append(
        ScheduleEntry(
            entry_id="inline-entry-1",
            scheduled_at="2026-08-20T20:00:00+08:00",
            title="散图排期测试",
            content=InlineContent(
                source_import_id="import-1",
                sets={"all": asset_ids, "post": [asset_ids[0]], "cover": [asset_ids[0]]},
            ),
        )
    )
    PlanRepository().save(plan_paths, plan, expected_revision=1)

    with TestClient(create_app(root)) as client:
        # 1. GET 读取
        get_resp = client.get("/api/plans/2026-08")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["content"]["kind"] == "inline_selection"

        # 2. PATCH 移动日期
        patch_resp = client.patch(
            "/api/plans/2026-08/entries/inline-entry-1/date",
            json={"revision": data["revision"], "target_date": "2026-08-22"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["entries"][0]["scheduled_at"].startswith("2026-08-22")

        # 3. DELETE 删除
        del_resp = client.delete(
            f"/api/plans/2026-08/entries/inline-entry-1?revision={patch_resp.json()['revision']}"
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["entries"] == []


def test_legacy_inline_converts_only_after_explicit_submission_save(tmp_path: Path):
    root, import_id, asset_ids = _seed_catalog(tmp_path)
    paths, _, _ = init_workspace(root)

    plan_paths = PlanPaths.from_workspace(paths, "2026-08")
    plan = PlanRepository().create(plan_paths)
    plan.entries.append(
        ScheduleEntry(
            entry_id="inline-entry-conv",
            scheduled_at="2026-08-18T19:00:00+08:00",
            title="待转换散图",
            content=InlineContent(
                source_import_id=import_id,
                sets={"all": asset_ids},
            ),
        )
    )
    PlanRepository().save(plan_paths, plan, expected_revision=1)

    with TestClient(create_app(root)) as client:
        # 只查看计划或素材库，不发生自动迁移
        client.get("/api/plans/2026-08")
        client.get("/api/library/assets")
        plan_check = PlanRepository().load(plan_paths)
        assert plan_check.entries[0].content.kind == "inline_selection"

        # 模拟前端明确点击保存投稿并关联
        create_resp = client.post(
            "/api/submissions",
            json={
                "title": "转换后的投稿",
                "source_import_id": import_id,
                "sets": {"all": asset_ids},
            },
        )
        assert create_resp.status_code == 200
        new_task_id = create_resp.json()["task_id"]

        # 更新月度计划 entry 为 TaskContent
        update_resp = client.put(
            "/api/plans/2026-08/entries/inline-entry-conv",
            json={
                "revision": plan_check.revision,
                "entry": {
                    "entry_id": "inline-entry-conv",
                    "scheduled_at": "2026-08-18T19:00:00+08:00",
                    "title": "待转换散图",
                    "content": {"kind": "task", "task_id": new_task_id},
                },
            },
        )
        assert update_resp.status_code == 200

        updated_plan = PlanRepository().load(plan_paths)
        assert updated_plan.entries[0].entry_id == "inline-entry-conv"
        assert updated_plan.entries[0].title == "待转换散图"
        assert updated_plan.entries[0].content.kind == "task"
        assert updated_plan.entries[0].content.task_id == new_task_id


def test_old_asset_search_array_contract_is_unchanged(tmp_path: Path):
    root, import_id, _ = _seed_catalog(tmp_path)

    with TestClient(create_app(root)) as client:
        response = client.get("/api/assets/search", params={"limit": 1000})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert "asset_id" in data[0]
        assert "path" in data[0]
        assert "display_name" in data[0]
        assert "width" in data[0]
        assert "height" in data[0]
