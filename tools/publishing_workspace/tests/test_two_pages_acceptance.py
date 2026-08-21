from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from publishing_workspace.catalog.repository import CatalogRepository
from publishing_workspace.config import init_workspace
from publishing_workspace.metadata import default_image_node_reader_registry
from publishing_workspace.models import ImportedItem, SelectionSet
from publishing_workspace.png_metadata import read_png_text_chunks
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.web.schedule_api import create_app


def _image_with_metadata(path: Path, prompt_text: str = "1girl, solo, masterpiece") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (16, 16), color="purple")
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", prompt_text)
    info.add_text("seed", "123456")
    img.save(path, pnginfo=info)
    return path


def test_full_two_pages_end_to_end_acceptance(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)

    # 1. 准备 Catalog 素材
    source_a = _image_with_metadata(tmp_path / "source" / "img_a.png", "artist:alice, character:homura")
    source_b = _image_with_metadata(tmp_path / "source" / "img_b.png", "artist:bob, character:madoka")
    source_c = _image_with_metadata(tmp_path / "source" / "img_c.png", "artist:alice, character:madoka")

    selection = SelectionSet(
        id="import-acceptance",
        source_type="directory",
        source_ref=str(tmp_path / "source"),
        items=[
            ImportedItem(
                source_path=str(source_a),
                resolved_path=str(source_a),
                source_type="directory",
                source_ref=str(tmp_path / "source"),
                source_order=0,
                display_name="img_a.png",
            ),
            ImportedItem(
                source_path=str(source_b),
                resolved_path=str(source_b),
                source_type="directory",
                source_ref=str(tmp_path / "source"),
                source_order=1,
                display_name="img_b.png",
            ),
            ImportedItem(
                source_path=str(source_c),
                resolved_path=str(source_c),
                source_type="directory",
                source_ref=str(tmp_path / "source"),
                source_order=2,
                display_name="img_c.png",
            ),
        ],
    )
    catalog_repo = CatalogRepository(paths.catalog)
    catalog_repo.import_selection(
        selection,
        readers=default_image_node_reader_registry(),
        enrichers=[],
    )
    imported = catalog_repo.assets_for_import("import-acceptance")
    assert len(imported) == 3
    asset_ids = [item.asset_id for item in imported]

    app = create_app(tmp_path)
    with TestClient(app) as client:
        # 2. 检索素材库
        lib_resp = client.get("/api/library/assets", params={"import_id": "import-acceptance", "limit": 60})
        assert lib_resp.status_code == 200
        page = lib_resp.json()
        assert len(page["items"]) == 3
        assert page["has_more"] is False

        # 3. 创建投稿（保存 Submission），自动补齐 post 和 cover
        sub_resp = client.post(
            "/api/submissions",
            json={
                "title": "验收投稿测试",
                "source_import_id": "import-acceptance",
                "sets": {
                    "all": asset_ids,
                    # post/cover 为空，触发自动补齐
                },
            },
        )
        assert sub_resp.status_code == 200
        sub_data = sub_resp.json()
        task_id = sub_data["task_id"]
        assert sub_data["sets"]["post"] == asset_ids
        assert sub_data["sets"]["cover"] == [asset_ids[0]]
        assert sub_data["revision"] == 1

        # 确认磁盘生成了 tasks/<task_id>/submission.yaml 和 task.yaml
        task_paths = TaskPaths.from_workspace(paths, task_id)
        assert task_paths.task_yaml.is_file()
        assert task_paths.submission_yaml.is_file()
        assert (task_paths.selection_dirs["all"] / "0001_img_a.png").is_file()

        # 4. 更新投稿
        update_resp = client.put(
            f"/api/submissions/{task_id}",
            json={
                "title": "验收投稿测试(已更新)",
                "source_import_id": "import-acceptance",
                "sets": {
                    "all": [asset_ids[0], asset_ids[1]],
                    "post": [asset_ids[0]],
                    "cover": [asset_ids[0]],
                },
                "revision": 1,
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["revision"] == 2
        assert len(update_resp.json()["sets"]["all"]) == 2

        # 5. 触发后台导出
        export_resp = client.post(f"/api/submissions/{task_id}/exports")
        assert export_resp.status_code in {200, 202}
        job_id = export_resp.json()["job_id"]

        # 轮询直至完成
        job_status = None
        for _ in range(30):
            status_resp = client.get(f"/api/export-jobs/{job_id}")
            assert status_resp.status_code == 200
            job_status = status_resp.json()["status"]
            if job_status in {"completed", "failed", "interrupted"}:
                break
            time.sleep(0.1)

        assert job_status == "completed"
        final_job = client.get(f"/api/export-jobs/{job_id}").json()
        output_dir = Path(final_job["output_dir"])
        assert output_dir.is_dir()

        # 验证 PNG 清参数（prompt 和 seed 被清理）
        all_output_images = list((output_dir / "output" / "all").glob("*.png"))
        assert len(all_output_images) == 2
        for out_img in all_output_images:
            assert read_png_text_chunks(out_img) == {}

        # 6. 打开输出目录 API (mock os.startfile)
        with patch("os.startfile", create=True) as mock_startfile:
            open_resp = client.post(f"/api/export-jobs/{job_id}/open-output")
            assert open_resp.status_code == 200
            assert open_resp.json()["output_dir"] == str(output_dir.resolve())
            mock_startfile.assert_called_once()

        # 7. 在月历中编排该投稿条目
        plan_get_resp = client.get("/api/plans/2026-08")
        assert plan_get_resp.status_code == 200

        entry_resp = client.post(
            "/api/plans/2026-08/entries",
            json={
                "entry": {
                    "entry_id": "acceptance-entry-1",
                    "scheduled_at": "2026-08-25T20:00:00+08:00",
                    "title": "月末大图集",
                    "content": {"kind": "task", "task_id": task_id},
                }
            },
        )
        assert entry_resp.status_code == 200
        entry_data = entry_resp.json()["entries"][0]
        assert entry_data["content"]["task_id"] == task_id
        entry_id = entry_data["entry_id"]

        # 8. 拖拽日历移动日期
        move_resp = client.patch(
            f"/api/plans/2026-08/entries/{entry_id}/date",
            json={
                "revision": entry_resp.json()["revision"],
                "target_date": "2026-08-28",
            },
        )
        assert move_resp.status_code == 200
        moved_entry = move_resp.json()["entries"][0]
        assert moved_entry["scheduled_at"] == "2026-08-28T20:00:00+08:00"
