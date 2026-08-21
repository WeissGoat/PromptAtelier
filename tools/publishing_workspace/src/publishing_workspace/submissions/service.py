from __future__ import annotations

import datetime
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..catalog.repository import CatalogRepository
from ..config import PublishingWorkspaceConfig, WorkspacePaths, load_workspace
from ..logging import get_logger
from ..models import AssetRecord, ImportedItem, SelectionSet, utc_now_iso
from ..tasks.models import TaskConfig
from ..tasks.paths import TaskPaths
from ..tasks.repository import TaskRepository
from ..tasks.selection import SelectionMaterializer, SelectionSnapshotWriter
from .models import (
    SelectionName,
    Submission,
    SubmissionDetail,
    SubmissionRevisionConflictError,
    SubmissionSummary,
)
from .repository import SUPPORTED_IMAGE_EXTENSIONS, SubmissionRepository

logger = get_logger(__name__)


def selection_from_assets(
    assets: list[AssetRecord],
    *,
    source_ref: str,
    source_type: str = "catalog",
) -> SelectionSet:
    """将 Catalog 的 AssetRecord 列表转为 SelectionSet。"""
    items = []
    for order, asset in enumerate(assets, start=1):
        items.append(
            ImportedItem(
                source_path=asset.path,
                resolved_path=asset.path,
                source_type=source_type,
                source_ref=source_ref,
                source_order=order,
                display_name=asset.display_name or Path(asset.path).name,
                warnings=list(asset.warnings),
            )
        )
    return SelectionSet(
        source_type=source_type,
        source_ref=source_ref,
        items=items,
    )


class SubmissionService:
    """Submission 业务服务，负责 asset 校验、task 创建/更新与集合物化。"""

    def __init__(
        self,
        catalog_factory: Callable[[Path], CatalogRepository] | None = None,
    ) -> None:
        self.catalog_factory = catalog_factory

    def _get_catalog_repo(self, paths: WorkspacePaths) -> CatalogRepository:
        if self.catalog_factory is not None:
            return self.catalog_factory(paths.catalog)
        return CatalogRepository(paths.catalog)

    def create_or_update(
        self,
        root: str | Path,
        *,
        task_id: str | None,
        title: str,
        source_import_id: str | None,
        sets: dict[str, list[str]],
        expected_revision: int | None = None,
    ) -> SubmissionDetail:
        """创建或更新投稿，并在 tasks/<task_id> 下立即物化素材和配置文件。"""
        paths, workspace_config = load_workspace(root)

        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("title 不能为空")

        # 检查 all 集合
        raw_all = sets.get("all", []) if isinstance(sets, dict) else []
        clean_all = [str(x).strip() for x in raw_all if str(x).strip()]
        if not clean_all:
            raise ValueError("all 集合不能为空")

        # 自动补齐 post 与 cover
        raw_post = sets.get("post", []) if isinstance(sets, dict) else []
        clean_post = [str(x).strip() for x in raw_post if str(x).strip()]
        if not clean_post:
            clean_post = list(clean_all)

        raw_cover = sets.get("cover", []) if isinstance(sets, dict) else []
        clean_cover = [str(x).strip() for x in raw_cover if str(x).strip()]
        if not clean_cover:
            clean_cover = [clean_post[0]]

        clean_import_id = str(source_import_id).strip() if source_import_id is not None else None
        if not clean_import_id:
            clean_import_id = None

        # 确定 task_id
        if task_id is None or not str(task_id).strip():
            now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            target_task_id = f"submission-{now_str}-{uuid4().hex[:6]}"
            is_new = True
        else:
            target_task_id = str(task_id).strip()
            task_test_paths = TaskPaths.from_workspace(paths, target_task_id)
            is_new = not (task_test_paths.task_yaml.is_file() or task_test_paths.submission_yaml.is_file())

        task_paths = TaskPaths.from_workspace(paths, target_task_id)

        # 提前进行 expected_revision 冲突校验（在任何图片物化或临时目录创建前）
        if not is_new:
            existing_submission = SubmissionRepository.load(task_paths)
            current_rev = existing_submission.revision if existing_submission is not None else 1
            if expected_revision is not None and current_rev != expected_revision:
                raise SubmissionRevisionConflictError(
                    f"投稿 revision 已变化：expected={expected_revision} actual={current_rev}"
                )
            next_revision = current_rev + 1
            created_at = existing_submission.created_at if existing_submission is not None else utc_now_iso()
            last_export = existing_submission.last_export if existing_submission is not None else None
        else:
            existing_submission = None
            next_revision = 1
            created_at = utc_now_iso()
            last_export = None

        # 验证所有 asset_id 在 Catalog 中存在且文件可用
        all_unique_ids = list(dict.fromkeys(clean_all + clean_post + clean_cover))
        catalog_repo = self._get_catalog_repo(paths)
        asset_map = catalog_repo.assets_by_ids(all_unique_ids, import_id=clean_import_id)

        missing_ids = [aid for aid in all_unique_ids if aid not in asset_map]
        if missing_ids:
            raise ValueError(f"素材在 Catalog 中不存在：{missing_ids}")

        unavailable_ids = [aid for aid, rec in asset_map.items() if not Path(rec.path).is_file()]
        if unavailable_ids:
            raise FileNotFoundError(f"素材文件不存在或不可读：{unavailable_ids}")

        submission = Submission(
            submission_id=target_task_id,
            task_id=target_task_id,
            title=clean_title,
            revision=next_revision,
            source_import_id=clean_import_id,
            sets={
                "all": clean_all,
                "post": clean_post,
                "cover": clean_cover,
            },
            created_at=created_at,
            updated_at=utc_now_iso(),
            last_export=last_export,
        )

        # 临时 staging 目录与事务备份
        staging_root = task_paths.task_root / f".submission-save.{uuid4().hex}.tmp"
        staged_paths = TaskPaths.from_task_root(paths, staging_root, task_id=target_task_id)
        staged_paths.ensure_layout()

        old_task_yaml_bytes = (
            task_paths.task_yaml.read_bytes() if task_paths.task_yaml.exists() else None
        )
        old_submission_yaml_bytes = (
            task_paths.submission_yaml.read_bytes() if task_paths.submission_yaml.exists() else None
        )
        old_selection_backup = task_paths.task_root / f".selection.{uuid4().hex}.old"
        selection_swapped = False
        task_dir_created_empty = False

        try:
            if not task_paths.task_root.exists():
                task_paths.task_root.mkdir(parents=True, exist_ok=True)
                task_dir_created_empty = True

            # 复制既有 history（不能丢失任何历史 JSON）
            if task_paths.history_dir.is_dir():
                shutil.copytree(task_paths.history_dir, staged_paths.history_dir, dirs_exist_ok=True)

            # 在 staged_paths.selection_dirs 中分别物化 all/post/cover
            for name in ("all", "post", "cover"):
                target_ids = submission.sets[name]  # type: ignore[index]
                target_records = [asset_map[aid] for aid in target_ids]
                selection_set = selection_from_assets(
                    target_records,
                    source_ref=clean_import_id or "catalog",
                )
                SelectionMaterializer().materialize(
                    selection_set,
                    staged_paths.selection_dirs[name],
                    mode="replace",
                    image_extensions=set(workspace_config.image_extensions),
                )

            # 基于临时 all 生成 candidates.snapshot.json 和 candidates.nvpls
            all_records = [asset_map[aid] for aid in submission.sets["all"]]
            all_selection_set = selection_from_assets(
                all_records,
                source_ref=clean_import_id or "catalog",
            )
            SelectionSnapshotWriter().write_candidates(staged_paths, all_selection_set)

            # 原子替换 selection 目录
            if task_paths.selection_root.exists():
                os.replace(task_paths.selection_root, old_selection_backup)
            os.replace(staged_paths.selection_root, task_paths.selection_root)
            selection_swapped = True

            # 创建或更新 task.yaml（只更新 title，不覆盖 processing/packages）
            if is_new:
                task_config = TaskConfig(task_id=target_task_id, title=clean_title)
            else:
                try:
                    existing_task_config = TaskRepository.load(task_paths)
                    task_config = existing_task_config.model_copy(update={"title": clean_title})
                except Exception:
                    task_config = TaskConfig(task_id=target_task_id, title=clean_title)
            TaskRepository.save(task_paths, task_config)

            # 保存 submission.yaml
            SubmissionRepository.save(task_paths, submission)

            # 成功后清理备份和临时目录
            if old_selection_backup.exists():
                shutil.rmtree(old_selection_backup, ignore_errors=True)
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

        except BaseException:
            # 完整事务回滚
            if selection_swapped:
                if task_paths.selection_root.exists():
                    shutil.rmtree(task_paths.selection_root, ignore_errors=True)
                if old_selection_backup.exists():
                    os.replace(old_selection_backup, task_paths.selection_root)
            else:
                if old_selection_backup.exists():
                    shutil.rmtree(old_selection_backup, ignore_errors=True)

            if old_task_yaml_bytes is not None:
                task_paths.task_yaml.write_bytes(old_task_yaml_bytes)
            elif is_new and task_paths.task_yaml.exists():
                task_paths.task_yaml.unlink(missing_ok=True)

            if old_submission_yaml_bytes is not None:
                task_paths.submission_yaml.write_bytes(old_submission_yaml_bytes)
            elif is_new and task_paths.submission_yaml.exists():
                task_paths.submission_yaml.unlink(missing_ok=True)

            if is_new and task_dir_created_empty:
                shutil.rmtree(task_paths.task_root, ignore_errors=True)

            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            raise

        return SubmissionDetail.model_validate(
            {
                **submission.model_dump(mode="json"),
                "warnings": [],
                "unresolved_files": [],
            }
        )

    def get(self, root: str | Path, task_id: str) -> SubmissionDetail:
        """获取投稿详情；若缺少 submission.yaml 则通过扫描现有 selection 和 Catalog 组装。"""
        paths, _ = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        if not task_paths.task_root.is_dir() or not task_paths.task_yaml.is_file():
            raise FileNotFoundError(f"投稿任务不存在：{task_id}")

        submission = SubmissionRepository.load(task_paths)
        if submission is not None:
            return SubmissionDetail.model_validate(
                {
                    **submission.model_dump(mode="json"),
                    "warnings": [],
                    "unresolved_files": [],
                }
            )

        # 兼容旧 task：读取 task.yaml 并扫描 selection 目录
        task_config = TaskRepository.load(task_paths)
        catalog_repo = self._get_catalog_repo(paths)

        warnings: list[str] = ["缺少 submission.yaml 配置文件"]
        unresolved_files: list[str] = []
        sets: dict[SelectionName, list[str]] = {"all": [], "post": [], "cover": []}

        for name in ("all", "post", "cover"):
            sel_dir = task_paths.selection_dirs[name]
            if not sel_dir.is_dir():
                continue
            image_files = sorted(
                [
                    f
                    for f in sel_dir.iterdir()
                    if f.is_file() and f.suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS
                ],
                key=lambda f: f.name,
            )
            for img in image_files:
                digest = _sha256(img)
                candidate_id = f"sha256:{digest}"
                found = catalog_repo.assets_by_ids([candidate_id])
                if candidate_id in found:
                    if candidate_id not in sets[name]:
                        sets[name].append(candidate_id)
                else:
                    unresolved_files.append(str(img.name))
                    warnings.append(f"图片未在 Catalog 找到：{img.name}")

        return SubmissionDetail(
            submission_id=task_config.task_id,
            task_id=task_config.task_id,
            title=task_config.title,
            revision=1,
            source_import_id=None,
            sets=sets,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            last_export=None,
            warnings=warnings,
            unresolved_files=unresolved_files,
        )

    def list(self, root: str | Path) -> list[SubmissionSummary]:
        """列出所有投稿摘要。"""
        paths, _ = load_workspace(root)
        return SubmissionRepository.list(paths)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
