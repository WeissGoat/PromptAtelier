from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..plans.search import AssetSearchFilter, AssetSearchService
from ..submissions.models import SubmissionRevisionConflictError
from ..submissions.service import SubmissionService


class SubmissionMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    title: str
    source_import_id: str | None = None
    sets: dict[str, list[str]]
    scheduled_at: str | None = None


def _sync_submission_schedule(
    root: Path,
    task_id: str,
    title: str,
    scheduled_at: str | None,
) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ..plans.models import ScheduleEntry, TaskContent
    from ..service import PublishingService

    if not scheduled_at or not scheduled_at.strip():
        return

    clean_sched = scheduled_at.strip()
    try:
        dt = datetime.fromisoformat(clean_sched)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        month_str = dt.strftime("%Y-%m")
    except Exception:
        return

    svc = PublishingService()
    try:
        try:
            plan = svc.schedule_show(root, month_str)
        except KeyError:
            plan = svc.schedule_create(root, month_str)

        if plan.status == "locked":
            return

        existing_entry = None
        for e in plan.entries:
            if isinstance(e.content, TaskContent) and e.content.task_id == task_id:
                existing_entry = e
                break

        if existing_entry is not None:
            new_entry = ScheduleEntry(
                entry_id=existing_entry.entry_id,
                scheduled_at=dt,
                title=title or existing_entry.title,
                content=TaskContent(task_id=task_id),
                execution=existing_entry.execution,
            )
            svc.schedule_update_entry(root, month_str, new_entry, expected_revision=plan.revision)
        else:
            new_entry = ScheduleEntry(
                entry_id=f"entry-{task_id}",
                scheduled_at=dt,
                title=title,
                content=TaskContent(task_id=task_id),
            )
            svc.schedule_add_entry(root, month_str, new_entry, expected_revision=plan.revision)
    except Exception:
        pass


def _find_task_scheduled_at(root: Path, task_id: str) -> str | None:
    from ..plans.models import TaskContent
    from ..service import PublishingService
    from ..config import load_workspace

    paths, _ = load_workspace(root)
    if not paths.plans.is_dir():
        return None

    try:
        for plan_dir in paths.plans.iterdir():
            if plan_dir.is_dir() and (plan_dir / "plan.yaml").is_file():
                try:
                    plan = PublishingService().schedule_show(root, plan_dir.name)
                    for e in plan.entries:
                        if isinstance(e.content, TaskContent) and e.content.task_id == task_id:
                            return e.scheduled_at.isoformat()
                except Exception:
                    pass
    except Exception:
        pass
    return None


def register_library_routes(app: FastAPI) -> None:
    """注册素材库与 Submission 相关的 HTTP API。"""

    @app.get("/api/library/assets")
    def search_library_assets(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
        import_id: str | None = None,
        text: str = "",
        artist: str | None = None,
        character: str | None = None,
        action_group: str | None = None,
        action: str | None = None,
        facets: str | None = None,
        posted: bool | None = None,
        favorite_mode: str = "all",
        favorite_ids: str | None = None,
    ):
        parsed_facets: dict[str, set[str]] = {}
        if facets:
            try:
                raw = json.loads(facets)
            except json.JSONDecodeError as exc:
                raise ValueError(f"facets 必须是 JSON 对象：{exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError("facets 必须是 JSON 对象")
            parsed_facets = {
                str(field): set(values if isinstance(values, list) else [values])
                for field, values in raw.items()
            }

        parsed_fav_ids: set[str] = set()
        if favorite_ids:
            try:
                raw_fav = json.loads(favorite_ids)
                if isinstance(raw_fav, list):
                    parsed_fav_ids = {str(x).strip() for x in raw_fav if str(x).strip()}
                elif isinstance(raw_fav, str):
                    parsed_fav_ids = {x.strip() for x in raw_fav.split(",") if x.strip()}
            except Exception:
                parsed_fav_ids = {x.strip() for x in favorite_ids.split(",") if x.strip()}

        fav_mode = favorite_mode if favorite_mode in {"all", "favorited", "unfavorited"} else "all"

        filters = AssetSearchFilter(
            offset=offset,
            limit=limit,
            import_id=import_id,
            text=text,
            artist=artist,
            character=character,
            action_group=action_group,
            action=action,
            facets=parsed_facets,
            posted=posted,
            favorite_mode=fav_mode,
            favorite_ids=parsed_fav_ids,
        )
        return AssetSearchService().search_page(
            app.state.publishing_root, filters
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/library/facets")
    def library_facets(import_id: str | None = None):
        return AssetSearchService().facets(app.state.publishing_root, import_id=import_id)

    @app.get("/api/submissions")
    def list_submissions():
        return [
            item.model_dump(mode="json")
            for item in SubmissionService().list(app.state.publishing_root)
        ]

    @app.get("/api/submissions/{task_id}")
    def get_submission(task_id: str):
        try:
            sub = SubmissionService().get(
                app.state.publishing_root, task_id
            ).model_dump(mode="json")
            sub["scheduled_at"] = _find_task_scheduled_at(app.state.publishing_root, task_id)
            return sub
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "task_not_found", "message": str(exc)}},
            )

    @app.post("/api/submissions")
    def create_submission(payload: SubmissionMutation):
        try:
            detail = SubmissionService().create_or_update(
                app.state.publishing_root,
                task_id=None,
                title=payload.title,
                source_import_id=payload.source_import_id,
                sets=payload.sets,
                expected_revision=payload.revision,
            )
            if payload.scheduled_at:
                _sync_submission_schedule(
                    app.state.publishing_root,
                    detail.task_id,
                    payload.title,
                    payload.scheduled_at,
                )
            result = detail.model_dump(mode="json")
            result["scheduled_at"] = payload.scheduled_at
            return result
        except SubmissionRevisionConflictError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": "submission_revision_conflict", "message": str(exc)}},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "invalid_submission", "message": str(exc)}},
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "asset_unavailable", "message": str(exc)}},
            )

    @app.put("/api/submissions/{task_id}")
    def update_submission(task_id: str, payload: SubmissionMutation):
        try:
            detail = SubmissionService().create_or_update(
                app.state.publishing_root,
                task_id=task_id,
                title=payload.title,
                source_import_id=payload.source_import_id,
                sets=payload.sets,
                expected_revision=payload.revision,
            )
            if payload.scheduled_at is not None:
                _sync_submission_schedule(
                    app.state.publishing_root,
                    task_id,
                    payload.title,
                    payload.scheduled_at,
                )
            result = detail.model_dump(mode="json")
            result["scheduled_at"] = payload.scheduled_at
            return result
        except SubmissionRevisionConflictError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": "submission_revision_conflict", "message": str(exc)}},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "invalid_submission", "message": str(exc)}},
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "asset_unavailable", "message": str(exc)}},
            )

    # 导出作业相关路由
    @app.post("/api/submissions/{task_id}/exports")
    def start_task_export(task_id: str):
        try:
            job = app.state.export_jobs.start(app.state.publishing_root, task_id)
            status_code = 202 if job.status == "queued" else 200
            return JSONResponse(
                status_code=status_code,
                content=job.model_dump(mode="json", by_alias=True),
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "task_not_found", "message": str(exc)}},
            )

    @app.get("/api/export-jobs/{job_id}")
    def get_export_job(job_id: str):
        try:
            job = app.state.export_jobs.get(app.state.publishing_root, job_id)
            return job.model_dump(mode="json", by_alias=True)
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "export_job_not_found", "message": str(exc)}},
            )

    @app.get("/api/submissions/{task_id}/exports")
    def list_task_exports(task_id: str):
        jobs = app.state.export_jobs.list_for_task(app.state.publishing_root, task_id)
        return [job.model_dump(mode="json", by_alias=True) for job in jobs]

    @app.post("/api/export-jobs/{job_id}/open-output")
    def open_export_output(job_id: str):
        from ..export_jobs.models import ExportOutputNotFoundError, ExportOutputOpenError

        try:
            output_dir = app.state.export_jobs.open_output(app.state.publishing_root, job_id)
            return {"output_dir": output_dir}
        except ExportOutputNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "export_output_not_found", "message": str(exc)}},
            )
        except ExportOutputOpenError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "export_output_open_failed",
                        "message": str(exc),
                        "output_dir": exc.output_dir,
                    }
                },
            )

    @app.get("/api/favorites")
    def get_favorites(import_id: str | None = None):
        from ..catalog.repository import CatalogRepository
        from ..config import load_workspace

        paths, _ = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        marks_map = catalog.all_asset_marks()
        fav_ids = [asset_id for asset_id, marks in marks_map.items() if "favorite" in marks]
        if import_id and import_id != "__all__":
            with catalog.connection() as conn:
                rows = conn.execute(
                    "SELECT asset_id FROM import_items WHERE import_id=?", (import_id,)
                ).fetchall()
                snapshot_assets = {r["asset_id"] for r in rows if r["asset_id"]}
            fav_ids = [aid for aid in fav_ids if aid in snapshot_assets]
        return {"favorites": fav_ids}

    @app.post("/api/favorites/toggle")
    async def toggle_favorite_mark(req: Request):
        from ..catalog.repository import CatalogRepository
        from ..config import load_workspace

        body = await req.json()
        asset_id = str(body.get("asset_id", "")).strip()
        favorited = bool(body.get("favorited", True))
        if not asset_id:
            raise HTTPException(status_code=422, detail="asset_id 不能为空")

        paths, _ = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        if favorited:
            catalog.set_asset_marks([asset_id], mark="favorite", note="Web UI favorite")
        else:
            with catalog.connection() as conn:
                conn.execute(
                    "DELETE FROM asset_marks WHERE asset_id=? AND mark='favorite'", (asset_id,)
                )
                conn.commit()
        return {"asset_id": asset_id, "favorited": favorited}

    @app.get("/api/assets/{asset_id}/details")
    def get_asset_details(asset_id: str):
        import datetime
        from ..catalog.repository import CatalogRepository
        from ..config import load_workspace
        from ..png_metadata import read_png_text_chunks

        paths, config = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        assets = catalog.assets_by_ids([asset_id])
        asset = assets.get(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="找不到资产记录")

        p = Path(asset.path)
        gen_info: dict[str, Any] = {
            "file_size": 0,
            "file_size_human": "",
            "modified_at": "",
            "prompt": "",
            "negative_prompt": "",
            "seed": None,
            "model": "",
            "sampler": "",
            "steps": None,
            "scale": None,
            "noise_schedule": "",
            "software": "",
            "raw_parameters": "",
            "all_chunks": {},
        }

        if p.is_file():
            stat = p.stat()
            gen_info["file_size"] = stat.st_size
            size_mb = stat.st_size / (1024 * 1024)
            gen_info["file_size_human"] = (
                f"{size_mb:.2f} MB" if size_mb >= 1 else f"{stat.st_size / 1024:.1f} KB"
            )
            gen_info["modified_at"] = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            try:
                chunks = read_png_text_chunks(p)
                gen_info["all_chunks"] = chunks
                gen_info["software"] = chunks.get("Software", "")
                gen_info["model"] = chunks.get("Source", "")

                if "Comment" in chunks:
                    try:
                        import json
                        comment_obj = json.loads(chunks["Comment"])
                        if isinstance(comment_obj, dict):
                            gen_info["prompt"] = comment_obj.get("prompt") or chunks.get("Description", "")
                            gen_info["negative_prompt"] = comment_obj.get("uc") or comment_obj.get("negative_prompt", "")
                            gen_info["seed"] = comment_obj.get("seed")
                            gen_info["steps"] = comment_obj.get("steps")
                            gen_info["scale"] = comment_obj.get("scale")
                            gen_info["sampler"] = comment_obj.get("sampler")
                            gen_info["noise_schedule"] = comment_obj.get("noise_schedule")
                            if not gen_info["model"]:
                                gen_info["model"] = comment_obj.get("model", "")
                    except Exception:
                        gen_info["raw_parameters"] = chunks["Comment"]

                if not gen_info["prompt"] and "parameters" in chunks:
                    raw = chunks["parameters"]
                    gen_info["raw_parameters"] = raw
                    lines = raw.split("\n")
                    prompt_lines = []
                    neg_lines = []
                    param_line = ""
                    mode = "prompt"
                    for line in lines:
                        if line.startswith("Negative prompt:"):
                            mode = "neg"
                            neg_lines.append(line.replace("Negative prompt:", "").strip())
                        elif mode == "neg" and ("Steps:" in line or "Sampler:" in line):
                            param_line = line
                            mode = "params"
                        elif mode == "prompt" and ("Steps:" in line or "Sampler:" in line):
                            param_line = line
                            mode = "params"
                        elif mode == "prompt":
                            prompt_lines.append(line)
                        elif mode == "neg":
                            neg_lines.append(line)
                    gen_info["prompt"] = "\n".join(prompt_lines).strip()
                    gen_info["negative_prompt"] = "\n".join(neg_lines).strip()

                    if param_line:
                        for part in param_line.split(","):
                            if ":" in part:
                                k, v = part.split(":", 1)
                                k = k.strip().lower()
                                v = v.strip()
                                if k == "seed": gen_info["seed"] = v
                                elif k == "steps": gen_info["steps"] = v
                                elif k == "sampler": gen_info["sampler"] = v
                                elif k == "cfg scale": gen_info["scale"] = v
                                elif k == "model": gen_info["model"] = v

                if not gen_info["prompt"] and "Description" in chunks:
                    gen_info["prompt"] = chunks["Description"]
            except Exception:
                pass

        marks = catalog.all_asset_marks().get(asset_id, [])
        is_fav = "favorite" in marks
        is_posted = any(m == "posted" or m.startswith("posted:") for m in marks)

        return {
            "asset_id": asset.asset_id,
            "path": str(asset.path),
            "display_name": asset.display_name,
            "width": asset.image.width,
            "height": asset.image.height,
            "image_format": asset.image.format,
            "is_favorited": is_fav,
            "is_posted": is_posted,
            "marks": marks,
            "generation_info": gen_info,
        }

    @app.post("/api/assets/{asset_id}/reveal")
    def reveal_asset_file(asset_id: str):
        import subprocess
        from ..catalog.repository import CatalogRepository
        from ..config import load_workspace

        paths, _ = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        assets = catalog.assets_by_ids([asset_id])
        asset = assets.get(asset_id)
        if asset is None or not Path(asset.path).is_file():
            raise HTTPException(status_code=404, detail="文件不存在或不可用")

        resolved_path = str(Path(asset.path).resolve())
        try:
            subprocess.Popen(["explorer", f"/select,{resolved_path}"])
            return {"success": True, "path": resolved_path}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"打开文件所在文件夹失败: {exc}")

    @app.post("/api/assets/{asset_id}/toggle-posted")
    async def toggle_asset_posted(asset_id: str, req: Request):
        from ..catalog.repository import CatalogRepository
        from ..config import load_workspace

        body = await req.json()
        posted = bool(body.get("posted", True))

        paths, _ = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        if posted:
            catalog.set_asset_marks([asset_id], mark="posted", note="Web UI manual mark")
        else:
            with catalog.connection() as conn:
                conn.execute(
                    "DELETE FROM asset_marks WHERE asset_id=? AND (mark='posted' OR mark LIKE 'posted:%')",
                    (asset_id,),
                )
                conn.commit()
        return {"asset_id": asset_id, "posted": posted}
