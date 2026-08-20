# Publishing Workspace 双页面与投稿导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Publishing Workspace 拆成独立的日历页和素材库页，支持基于 asset_id 的投稿保存、task 持久化、真实导出进度和导出目录打开，同时保持旧 API、旧 task 和旧 inline 计划兼容。

**Architecture:** 保留现有 FastAPI、Catalog、MonthlyPlan、TaskWorkflowService、PackageBuilder 和 ImageProcessingPipeline。新增 SubmissionService 管理 submission.yaml 与 task 选择集合，新增 AssetPageResult 提供稳定分页，新增 ExportJobService 在 Web 进程后台调用 PackageBuilder。旧 schedule.html 和旧 API 保留为兼容入口；正式入口改为 /calendar 和 /library。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、PyYAML、SQLite Catalog、Pillow、原生 HTML/CSS/JavaScript、pytest、uvicorn。

## Global Constraints

- 不创建新 Git 分支，不使用 git reset --hard 或 git checkout --。
- 不回滚当前工作区已有修改；每个提交只包含本计划明确的文件。
- 不迁移 Catalog，不修改旧 task 的图片和 build。
- 不改变旧 /api/assets/search 返回数组的行为。
- 不改变 PackageBuilder.build(root, task_id) 和现有 CLI 的默认返回结构。
- 新投稿保存时立即创建或更新 task。
- 保存时后端自动补齐：post=all、cover=post[0]。
- post 和 cover 不强制是 all 的子集，沿用现有 build warning。
- 不新增自动排期、推荐排期或复制投稿入口。
- 导出进度必须来自实际 PackageBuilder 处理回调，不使用假进度。
- 业务验收必须包含真实 workspace 的筛选、保存 task、真实导出和打开导出目录。
- 代码注释使用中文；新增日志使用现有 trace/info/warning/error 体系。

---

## 文件边界总览

### 新增文件

- src/publishing_workspace/submissions/models.py：Submission 数据模型。
- src/publishing_workspace/submissions/repository.py：submission.yaml 读写和历史任务摘要。
- src/publishing_workspace/submissions/service.py：asset 校验、task 创建/更新和集合物化。
- src/publishing_workspace/export_jobs/models.py：导出作业和进度模型。
- src/publishing_workspace/export_jobs/repository.py：导出作业 JSON 原子持久化。
- src/publishing_workspace/export_jobs/service.py：应用级后台导出调度。
- src/publishing_workspace/web/library_api.py：素材库和 Submission API。
- src/publishing_workspace/web/static/calendar.html/js/css：正式日历页。
- src/publishing_workspace/web/static/library.html/js/css：正式素材库页。

### 保留为兼容的文件

- src/publishing_workspace/web/static/schedule.html
- src/publishing_workspace/web/static/schedule.js
- src/publishing_workspace/web/static/schedule.css
- /api/assets/search
- /api/tasks
- 旧 MonthlyPlan.inline_selection

旧文件不删除、不重写为新页面的共享状态。根路径改到正式日历页，但 schedule.html 仍可通过旧静态 URL 访问。

---

### Task 1: 建立稳定的素材分页检索契约

**Files:**
- Modify: src/publishing_workspace/plans/search.py
- Modify: src/publishing_workspace/catalog/repository.py
- Test: tests/test_plan_search.py
- Test: tests/test_catalog_repository.py（不存在时创建）

**Interfaces:**

新增：

~~~python
class AssetPageResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.asset-page/v1"] = Field(
        default="publishing-workspace.asset-page/v1",
        alias="schema",
    )
    items: list[AssetSearchResult]
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None
~~~

扩展内部分页查询模型：

~~~python
class AssetSearchFilter(BaseModel):
    # 现有 import_id、text、节点和 facets 字段保持不变。
    offset: int = Field(default=0, ge=0)
    # 保持旧 /api/assets/search 的 1000 条上限；新素材库 API 单独限制为 200。
    limit: int = Field(default=100, ge=1, le=1000)
~~~

新增方法签名：

~~~text
AssetSearchService.search_page(root: str | Path, filters: AssetSearchFilter) -> AssetPageResult
~~~

保留现有方法签名：

~~~text
AssetSearchService.search(root: str | Path, filters: AssetSearchFilter) -> list[AssetSearchResult]
~~~

旧 search 必须始终忽略 offset，只按原行为返回前 limit 条数组；旧 /api/assets/search 继续支持 limit<=1000。只有新 /api/library/assets 在 FastAPI Query 参数层限制 limit<=200，然后把已验证的 offset/limit 传给 search_page。

在 AssetSearchResult 中加入图片布局需要的只读字段：

~~~python
width: int
height: int
image_format: str
~~~

在 CatalogRepository 中新增：

~~~text
CatalogRepository.assets_by_ids(
    asset_ids: Collection[str],
    *,
    import_id: str | None = None,
) -> dict[str, AssetRecord]
~~~

- [ ] **Step 1: 写相邻分页测试**

~~~python
def test_search_page_returns_stable_adjacent_pages(tmp_path: Path):
    seed_catalog_with_assets(tmp_path, count=5)

    first = AssetSearchService().search_page(
        tmp_path,
        AssetSearchFilter(offset=0, limit=2),
    )
    second = AssetSearchService().search_page(
        tmp_path,
        AssetSearchFilter(offset=2, limit=2),
    )

    assert first.offset == 0
    assert first.next_offset == 2
    assert first.has_more is True
    assert second.offset == 2
    assert not {item.asset_id for item in first.items}.intersection(
        item.asset_id for item in second.items
    )
~~~

再增加：

- 最后一页 next_offset 为 None；
- 相同筛选条件连续请求的 asset_id 顺序一致；
- 节点筛选和 facet 筛选在分页前生效；
- offset 超过结果数量返回空 items 而不是 422；
- limit=0、offset=-1、limit=1001 被 Pydantic 拒绝；
- 旧 search 即使收到 offset=2 也仍返回第一条，证明旧调用语义不变。

- [ ] **Step 2: 运行测试确认当前接口失败**

Run:

~~~powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest tests/test_plan_search.py -q
~~~

Expected: 新测试因 search_page 或 offset 未实现而失败，已有测试仍可收集。

- [ ] **Step 3: 拆出匹配、排序和分页**

将 AssetSearchService.search 的逻辑拆成以下内部阶段：

1. 读取指定 import 或全 Catalog 的候选资产；
2. 为每个候选计算节点值和 classify facet；
3. 应用 text、节点和 facet 匹配；
4. 用稳定键排序；
5. search_page 对匹配结果执行 offset/limit；旧 search 固定从 0 开始，只执行 limit；
6. 将结果转换为 AssetSearchResult。

排序键固定为：

~~~python
(asset.source_order, asset.display_name.casefold(), asset.asset_id)
~~~

不能依赖 SQLite 无显式排序时的返回顺序。search_page 的 has_more 使用过滤后的完整匹配数量；第一版可以在内存中完成，后续再把筛选下推 SQLite。

- [ ] **Step 4: 实现按 asset_id 查询**

assets_by_ids 使用分块 SQL 查询 assets、asset_paths、asset_nodes，并复用 CatalogRepository 当前的 AssetRecord 组装逻辑。返回字典只包含找到的 ID，不静默报错；调用方通过 requested_ids - found_ids 得到缺失列表。

当传入 import_id 时，只允许返回该 import 的资产路径；不传时从 Catalog 的可用路径中选取。资产 ID 必须去重，保留请求顺序由 service 负责。

- [ ] **Step 5: 运行分页和回归测试**

Run:

~~~powershell
uv run pytest tests/test_plan_search.py tests/test_catalog_repository.py -q
~~~

Expected: 分页、稳定排序、asset_id 查询和原有 facet/node 搜索测试通过。

- [ ] **Step 6: 提交**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/plans/search.py tools/publishing_workspace/src/publishing_workspace/catalog/repository.py tools/publishing_workspace/tests/test_plan_search.py tools/publishing_workspace/tests/test_catalog_repository.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: add paged asset search contract"
~~~

---

### Task 2: 实现 Submission 模型、仓库和保存服务

**Files:**
- Create: src/publishing_workspace/submissions/__init__.py
- Create: src/publishing_workspace/submissions/models.py
- Create: src/publishing_workspace/submissions/repository.py
- Create: src/publishing_workspace/submissions/service.py
- Modify: src/publishing_workspace/tasks/paths.py
- Test: tests/test_submission_models.py
- Test: tests/test_submission_repository.py
- Test: tests/test_submission_service.py

**Interfaces:**

Submission 模型：

~~~python
class Submission(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.submission/v1"] = Field(
        default="publishing-workspace.submission/v1",
        alias="schema",
    )
    submission_id: NonEmptyText
    task_id: NonEmptyText
    title: NonEmptyText
    revision: int = Field(default=1, ge=1)
    source_import_id: str | None = None
    sets: dict[SelectionName, list[NonEmptyText]]
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_export: dict[str, Any] | None = None


class SubmissionDetail(Submission):
    warnings: list[str] = Field(default_factory=list)
    unresolved_files: list[str] = Field(default_factory=list)


class SubmissionScheduleRef(BaseModel):
    plan_id: NonEmptyText
    entry_id: NonEmptyText
    scheduled_at: str


class SubmissionSummary(BaseModel):
    submission_id: NonEmptyText
    task_id: NonEmptyText
    title: NonEmptyText
    counts: dict[SelectionName, int]
    updated_at: str
    scheduled_entries: list[SubmissionScheduleRef] = Field(default_factory=list)
    last_export: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
~~~

SubmissionDetail 的 warnings 和 unresolved_files 只用于 API 展示，不写入 submission.yaml；仓库只持久化 Submission 定义的字段。

服务接口：

~~~python
class SubmissionRevisionConflictError(RuntimeError):
    pass
~~~

~~~text
SubmissionService.create_or_update(
    root: str | Path,
    *,
    task_id: str | None,
    title: str,
    source_import_id: str | None,
    sets: dict[str, list[str]],
    expected_revision: int | None = None,
) -> SubmissionDetail
SubmissionService.get(root: str | Path, task_id: str) -> SubmissionDetail
SubmissionService.list(root: str | Path) -> list[SubmissionSummary]
~~~

TaskPaths 增加：

~~~python
self.submission_yaml = self.task_root / "submission.yaml"
~~~

- [ ] **Step 1: 写模型归一化测试**

~~~python
def test_submission_fills_post_and_cover_from_all():
    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="测试投稿",
        sets={"all": ["sha256:a", "sha256:b"], "post": [], "cover": []},
    )

    assert submission.sets["post"] == ["sha256:a", "sha256:b"]
    assert submission.sets["cover"] == ["sha256:a"]
~~~

测试还要覆盖：

- 未知集合名称拒绝；
- 集合内重复 ID 只保留第一次；
- all 为空由 service 拒绝；
- task_id 和 submission_id 不一致拒绝；
- source_import_id 空白值归一为 None；
- 更新已有 task 后，selection/history 下的旧历史 JSON 原样保留；
- 在 selection 交换后模拟 submission.yaml 保存失败，旧 all/post/cover、history 和 candidates 文件全部恢复。

- [ ] **Step 2: 写正确的 revision 冲突测试**

先创建投稿，再用 expected_revision=created.revision 成功更新一次，得到 revision=2；随后再次使用 expected_revision=created.revision，确认抛出 SubmissionRevisionConflictError。避免把第一次保存误当成冲突。

~~~python
def test_submission_service_rejects_stale_revision(tmp_path: Path):
    service = SubmissionService(catalog_factory=FakeCatalogFactory())
    created = service.create_or_update(
        tmp_path,
        task_id=None,
        title="初稿",
        source_import_id="import-1",
        sets={"all": ["sha256:a"]},
    )
    updated = service.create_or_update(
        tmp_path,
        task_id=created.task_id,
        title="第二版",
        source_import_id="import-1",
        sets={"all": ["sha256:a"]},
        expected_revision=created.revision,
    )

    assert updated.revision == created.revision + 1
    with pytest.raises(SubmissionRevisionConflictError):
        service.create_or_update(
            tmp_path,
            task_id=created.task_id,
            title="旧版本",
            source_import_id="import-1",
            sets={"all": ["sha256:a"]},
            expected_revision=created.revision,
        )
~~~

- [ ] **Step 3: 运行失败测试**

Run:

~~~powershell
uv run pytest tests/test_submission_models.py tests/test_submission_repository.py tests/test_submission_service.py -q
~~~

Expected: 新模块不存在或接口未实现，测试失败。

- [ ] **Step 4: 实现模型和 YAML 仓库**

模型 validator 负责：

- 只允许 all、post、cover；
- 集合内按首次出现顺序去重；
- post 为空且 all 非空时复制 all；
- cover 为空且 post 非空时取 post 第一项；
- all 为空不在模型层猜测或补值，由 service 返回 submission_empty；
- source_import_id 空白值规范为 None。

repository 负责：

- submission.yaml 的 UTF-8 YAML 读取；
- 顶层 schema 校验；
- 临时文件 + os.replace 原子保存；
- expected_revision 比较；
- 不存在 submission.yaml 时返回 None，而不是把旧 task 当成损坏。

- [ ] **Step 5: 实现 task 创建和素材物化**

创建或更新流程固定为：

1. load_workspace；
2. 新建时生成安全 task_id：submission-YYYYMMDD-HHMMSS-短随机串；
3. 归一化三套集合；
4. 用 CatalogRepository.assets_by_ids 查询所有 ID；
5. 对缺失 ID 返回 asset_not_found，并列出具体 ID；
6. 对 Catalog 路径不存在或不可读返回 asset_unavailable；
7. 新 task 使用 TaskRepository.create 的默认 TaskConfig；
8. 已有 task 读取 TaskConfig，只更新 title，不覆盖 processing/packages；
9. 在 task 根目录创建 `.submission-save.<uuid>.tmp` 临时 task 根，并用 `TaskPaths.from_task_root(workspace, staging_root, task_id=task_id)` 得到 staged_paths；
10. 若旧 selection/history 存在，用 `shutil.copytree(task_paths.history_dir, staged_paths.history_dir, dirs_exist_ok=True)` 复制到临时 selection/history，不能丢失任何历史 JSON；
11. 把 AssetRecord 转为 SelectionSet，在 staged_paths.selection_dirs 内分别物化 all/post/cover；
12. 调用 SelectionSnapshotWriter.write_candidates(staged_paths, all_selection)，基于临时 all 生成新的 candidates.snapshot.json 和 candidates.nvpls，旧 candidates 文件不直接复制；
13. 三套集合和 candidates 都成功后，先把旧 selection 原子改名为 `.selection.<uuid>.old`，再把 staged_paths.selection_root 原子改名为 selection；
14. 保存 task.yaml 和 submission.yaml；全部成功后才删除 `.selection.<uuid>.old`；
15. 任一步失败时删除临时根；若已经交换 selection，则移走失败的新 selection 并把 `.selection.<uuid>.old` 原子恢复；新建 task 失败时只删除本次创建的空 task；builds 始终不移动、不删除。

更新已有 task 时，在写入前保存旧 task.yaml 与 submission.yaml 的原始字节快照；如果 task.yaml 已更新但 submission.yaml 保存失败，除恢复 selection 外还要原子恢复两份 YAML。expected_revision 必须在任何图片物化前检查，冲突时不创建临时目录。

转换函数：

~~~text
selection_from_assets(
    assets: list[AssetRecord],
    *,
    source_ref: str,
    source_type: str = "catalog",
) -> SelectionSet
~~~

更新已有任务时目录结构为：

~~~text
tasks/<task_id>/.submission-save.<uuid>.tmp/
  selection/
    all/
    post/
    cover/
    history/                    # 从旧 selection/history 复制
    candidates.snapshot.json   # 按新 all 重建
    candidates.nvpls           # 按新 all 重建
~~~

交换前后的 `.selection.<uuid>.old` 只是事务备份，不能被列表 API 当成 task 内容。成功后临时目录替换为 selection；失败必须恢复旧 selection。不要复制或删除 builds，也不要通过“直接删除整个 selection 后重建”的方式实现。

- [ ] **Step 6: 实现历史 task 摘要**

SubmissionRepository.list 扫描 tasks/*/task.yaml：

- 有 submission.yaml：正常读取；
- 没有 submission.yaml：读取 TaskConfig、扫描三套图片；
- 用文件 SHA-256 与 Catalog asset_id 匹配；
- 无法匹配的图片放入 unresolved_files 和 warning；
- 仍然返回历史投稿摘要，不能因为缺少 submission.yaml 隐藏任务；
- 用户第一次成功保存该任务时补写 submission.yaml。

列表摘要至少包含 task_id、title、counts、updated_at、scheduled_entries、last_export 和 warnings。

- [ ] **Step 7: 运行服务测试并提交**

Run:

~~~powershell
uv run pytest tests/test_submission_models.py tests/test_submission_repository.py tests/test_submission_service.py -q
~~~

Expected: task.yaml、submission.yaml、三套 selection、自动补齐、revision 和失败清理全部通过。

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/submissions tools/publishing_workspace/src/publishing_workspace/tasks/paths.py tools/publishing_workspace/tests/test_submission_models.py tools/publishing_workspace/tests/test_submission_repository.py tools/publishing_workspace/tests/test_submission_service.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: add submission persistence service"
~~~

---

### Task 3: 增加素材库和投稿 Web API

**Files:**
- Create: src/publishing_workspace/web/library_api.py
- Modify: src/publishing_workspace/web/schedule_api.py
- Modify: src/publishing_workspace/service.py
- Test: tests/test_library_api.py
- Modify: tests/test_schedule_api.py

**Interfaces:**

请求模型：

~~~python
class SubmissionMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    title: str
    source_import_id: str | None = None
    sets: dict[str, list[str]]
~~~

路由注册签名：

~~~text
register_library_routes(app: FastAPI) -> None
~~~

新增 API：

~~~text
GET  /api/library/assets
GET  /api/library/facets
GET  /api/submissions
GET  /api/submissions/{task_id}
POST /api/submissions
PUT  /api/submissions/{task_id}
~~~

- [ ] **Step 1: 写素材分页 API 测试**

~~~python
def test_library_assets_returns_page_contract(tmp_path: Path):
    client = client_for(tmp_path)
    response = client.get(
        "/api/library/assets",
        params={
            "offset": 0,
            "limit": 2,
            "facets": json.dumps({"subtype": ["kiss"]}),
        },
    )

    assert response.status_code == 200
    assert response.json()["schema"] == "publishing-workspace.asset-page/v1"
    assert response.json()["offset"] == 0
    assert response.json()["limit"] == 2
~~~

- [ ] **Step 2: 写投稿 CRUD API 测试**

使用真实的最小 Catalog fixture：

~~~python
def test_create_submission_returns_task_and_filled_sets(tmp_path: Path):
    client = client_with_catalog(tmp_path)
    response = client.post(
        "/api/submissions",
        json={
            "title": "API 投稿",
            "source_import_id": "import-1",
            "sets": {"all": ["sha256:first"]},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"]
    assert body["sets"]["post"] == ["sha256:first"]
    assert body["sets"]["cover"] == ["sha256:first"]
    assert (tmp_path / "tasks" / body["task_id"] / "submission.yaml").is_file()
~~~

还要测试 GET 详情、PUT revision、未知 asset 返回具体错误、空 all 返回 422。

- [ ] **Step 3: 运行失败测试**

Run:

~~~powershell
uv run pytest tests/test_library_api.py tests/test_schedule_api.py -q
~~~

Expected: 新路由不存在，旧 schedule 测试仍可运行。

- [ ] **Step 4: 注册素材库路由**

GET /api/library/assets：

- 解析 facets JSON 对象；
- 构造带 offset/limit 的 AssetSearchFilter；
- 返回 AssetPageResult；
- `offset: int = Query(default=0, ge=0)`；
- `limit: int = Query(default=60, ge=1, le=200)`，页面上限为 200；
- API 测试确认 limit=201 返回 422，而旧 /api/assets/search 的 limit=1000 仍返回 200。

GET /api/library/facets 复用 AssetSearchService.facets。

旧 GET /api/assets/search：

- 继续返回 JSON 数组；
- 保留原 limit 1 到 1000 校验；
- 不返回分页包装对象。

- [ ] **Step 5: 注册 Submission 路由和错误处理**

SubmissionRevisionConflictError 返回 409：

~~~json
{
  "detail": {
    "code": "submission_revision_conflict",
    "message": "投稿 revision 已变化"
  }
}
~~~

缺失资产返回 422 或 404 时必须在 detail.items 中列出 asset_id；统一错误处理不得把这些信息抹掉。

- [ ] **Step 6: 注册页面路由**

在 StaticFiles mount 之前增加：

~~~text
GET /calendar -> static/calendar.html
GET /library  -> static/library.html
GET /         -> static/calendar.html
~~~

保留 /schedule.html、/schedule.js、/schedule.css。现有测试中针对素材库的断言改为请求 /schedule.html；新增测试验证根路径是日历页。

- [ ] **Step 7: 运行 API 回归并提交**

Run:

~~~powershell
uv run pytest tests/test_library_api.py tests/test_schedule_api.py -q
~~~

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/web/library_api.py tools/publishing_workspace/src/publishing_workspace/web/schedule_api.py tools/publishing_workspace/src/publishing_workspace/service.py tools/publishing_workspace/tests/test_library_api.py tools/publishing_workspace/tests/test_schedule_api.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: add library and submission web api"
~~~

---

### Task 4: 拆出正式日历页和素材库页

**Files:**
- Create: src/publishing_workspace/web/static/calendar.html
- Create: src/publishing_workspace/web/static/calendar.js
- Create: src/publishing_workspace/web/static/calendar.css
- Create: src/publishing_workspace/web/static/library.html
- Create: src/publishing_workspace/web/static/library.js
- Create: src/publishing_workspace/web/static/library.css
- Leave unchanged: src/publishing_workspace/web/static/schedule.html/js/css
- Test: tests/test_web_pages.py

**Interfaces:**

- Consumes: Task 3 的 HTTP API。
- Produces: 两个不共享页面状态的原生 JavaScript 页面。

- [ ] **Step 1: 写静态页面测试**

~~~python
def test_calendar_page_contains_only_calendar_surface(tmp_path: Path):
    client = client_for(tmp_path)
    response = client.get("/calendar")

    assert response.status_code == 200
    assert "月度投稿计划" in response.text
    assert "classify.yaml" not in response.text
~~~

~~~python
def test_library_page_contains_filters_and_submission_editor(tmp_path: Path):
    client = client_for(tmp_path)
    response = client.get("/library")

    assert response.status_code == 200
    assert "素材库" in response.text
    assert "Submission" in response.text
    assert "classify.yaml" in response.text
~~~

- [ ] **Step 2: 创建 calendar 页面**

从现有 schedule.html/js/css 提取并调整：

- 月份切换；
- 月历渲染；
- 投稿卡片拖拽改期；
- revision 冲突提示；
- 新建投稿时选择已有 Submission/task；
- 点击投稿跳转 /library?submission_id=<task_id>；
- 旧 inline entry 的“编辑素材”跳转 /library?plan_id=<YYYY-MM>&entry_id=<entry_id>，只传引用，不在日历页迁移；
- 卡片显示 post 数量和最近导出状态。

删除日历页中的素材搜索、facet 控件、asset 预览和 all/post/cover 编辑器。旧 schedule 文件不改，以保证旧入口兼容。

- [ ] **Step 3: 创建 library 页面**

实现已确认的三栏布局：

~~~text
左：import、节点、classify facet 筛选
中：瀑布流 asset cards + infinite scroll
右：历史投稿 / Submission 编辑器
~~~

交互契约：

- 初始请求 offset=0、limit=60；
- IntersectionObserver 触发下一页；
- 使用 asset_id Set 去重；
- 筛选变化取消旧请求、清空结果、重置 offset；
- 点击素材改变选中状态；
- 点击加入 all 才写入右侧 Submission；
- 集合标签切换只改变当前编辑集合；
- all/post/cover 支持移除和拖拽排序；
- 保存后用服务端返回值覆盖本地集合；
- 点击历史投稿请求详情并进入编辑；
- 新建按钮清空编辑器并在保存时生成 task。

瀑布流卡片读取 width/height，用 CSS aspect-ratio 预留图片区域，避免图片加载和分页时布局跳动。预览 URL 继续使用 /api/assets/{asset_id}/preview。

- [ ] **Step 4: 加入响应式和可访问交互**

必须满足：

- 900px 以下由三栏变为筛选、素材、编辑的纵向区域；
- 620px 以下保持两列瀑布流；
- 图标按钮有 title 和 aria-label；
- 文字不溢出按钮、卡片或面板；
- 页面区域不使用卡片嵌套卡片；
- 不依赖本地 F:\ThreeState 或旧项目绝对路径。

- [ ] **Step 5: 运行页面语法和测试**

Run:

~~~powershell
node --check src/publishing_workspace/web/static/calendar.js
node --check src/publishing_workspace/web/static/library.js
uv run pytest tests/test_web_pages.py tests/test_schedule_api.py -q
~~~

Expected: 两个页面能被 API 返回，JavaScript 语法通过，旧 schedule 页面测试不回归。

- [ ] **Step 6: 提交**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/web/static/calendar.html tools/publishing_workspace/src/publishing_workspace/web/static/calendar.js tools/publishing_workspace/src/publishing_workspace/web/static/calendar.css tools/publishing_workspace/src/publishing_workspace/web/static/library.html tools/publishing_workspace/src/publishing_workspace/web/static/library.js tools/publishing_workspace/src/publishing_workspace/web/static/library.css tools/publishing_workspace/tests/test_web_pages.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: split calendar and library pages"
~~~

---

### Task 5: 给 PackageBuilder 增加真实进度回调

**Files:**
- Modify: src/publishing_workspace/packages/models.py
- Modify: src/publishing_workspace/packages/builder.py
- Modify: src/publishing_workspace/packages/__init__.py
- Test: tests/test_package_builder.py

**Interfaces:**

~~~python
class BuildProgress(BaseModel):
    phase: Literal["validate", "process", "archive", "finalize"]
    processed: int
    total: int
    current_selection: SelectionName | None = None
    current_filename: str | None = None

ProgressCallback = Callable[[BuildProgress], None]
~~~

扩展两个入口，但保持旧调用有效：

~~~text
PackageBuilder.build(
    root: str | Path,
    task_id: str,
    *,
    progress: ProgressCallback | None = None,
) -> BuildResult
PackageBuilder.build_paths(
    task_paths: TaskPaths,
    *,
    output_root: str | Path | None = None,
    workspace_config: PublishingWorkspaceConfig | None = None,
    progress: ProgressCallback | None = None,
) -> BuildResult
~~~

- [ ] **Step 1: 写回调测试**

~~~python
def test_builder_reports_real_processing_progress(tmp_path: Path):
    root, task_paths = make_valid_task(tmp_path, image_count=2)
    events: list[BuildProgress] = []

    PackageBuilder().build(
        root,
        task_paths.task_id,
        progress=events.append,
    )

    assert events[0].phase == "validate"
    assert any(event.phase == "process" for event in events)
    assert events[-1].phase == "finalize"
    assert events[-1].processed == events[-1].total
~~~

- [ ] **Step 2: 运行失败测试**

Run:

~~~powershell
uv run pytest tests/test_package_builder.py::test_builder_reports_real_processing_progress -q
~~~

Expected: 当前 build 不接受 progress 参数，测试失败。

- [ ] **Step 3: 实现可选回调**

在输入校验完成、每个图片处理完成、每个 ZIP 完成和正式目录替换后调用回调。无回调时不构造额外状态，不改变 build 输出、manifest 和异常行为。

total 使用三个集合实际文件数总和；同一图片出现在多个集合时按每个集合的实际处理项计数。validate 阶段可以发送 processed=0、total=总项数。

- [ ] **Step 4: 运行打包回归**

Run:

~~~powershell
uv run pytest tests/test_package_builder.py tests/test_pipeline.py -q
~~~

Expected: 清 PNG 参数、mosaic、ZIP、失败清理测试通过。

- [ ] **Step 5: 提交**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/packages/models.py tools/publishing_workspace/src/publishing_workspace/packages/builder.py tools/publishing_workspace/src/publishing_workspace/packages/__init__.py tools/publishing_workspace/tests/test_package_builder.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: expose package build progress"
~~~

---

### Task 6: 实现应用级 ExportJobService 和导出 API

**Files:**
- Create: src/publishing_workspace/export_jobs/__init__.py
- Create: src/publishing_workspace/export_jobs/models.py
- Create: src/publishing_workspace/export_jobs/repository.py
- Create: src/publishing_workspace/export_jobs/service.py
- Modify: src/publishing_workspace/web/library_api.py
- Modify: src/publishing_workspace/web/schedule_api.py
- Test: tests/test_export_jobs.py
- Modify: tests/test_schedule_api.py

**Interfaces:**

~~~python
class ExportJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.export-job/v1"] = Field(
        default="publishing-workspace.export-job/v1",
        alias="schema",
    )
    job_id: NonEmptyText
    task_id: NonEmptyText
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    phase: Literal["validate", "process", "archive", "finalize"] | None = None
    processed: int = 0
    total: int = 0
    percent: int = 0
    current_selection: SelectionName | None = None
    current_filename: str | None = None
    build_id: str | None = None
    output_dir: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
~~~

~~~python
class ExportOutputNotFoundError(FileNotFoundError):
    pass


class ExportOutputOpenError(RuntimeError):
    def __init__(self, message: str, *, output_dir: str):
        super().__init__(message)
        self.output_dir = output_dir
~~~

~~~text
ExportJobService.start(root: str | Path, task_id: str) -> ExportJob
ExportJobService.get(root: str | Path, job_id: str) -> ExportJob
ExportJobService.list_for_task(root: str | Path, task_id: str) -> list[ExportJob]
ExportJobService.recover_interrupted(root: str | Path) -> int
ExportJobService.open_output(root: str | Path, job_id: str) -> str
ExportJobService.close(*, wait: bool = True) -> None
~~~

ExportJobService 必须由 create_app 创建一次并存入 app.state.export_jobs，不能在每个 HTTP 请求中 new 一个 service。这样 ThreadPoolExecutor 和 active job 索引在整个 Web 进程中共享。

- [ ] **Step 1: 写作业持久化和去重测试**

~~~python
def test_start_returns_same_active_job_for_same_task(tmp_path: Path):
    task_id = make_valid_task(tmp_path)
    builder = BlockingBuilder()
    service = ExportJobService(builder=builder)
    try:
        first = service.start(tmp_path, task_id)
        second = service.start(tmp_path, task_id)

        assert first.job_id == second.job_id
        assert second.status in {"queued", "running"}
    finally:
        builder.release.set()
        service.close(wait=True)
~~~

~~~python
def test_recover_interrupted_marks_orphaned_running_jobs(tmp_path: Path):
    write_job(tmp_path, task_id="task-1", status="running")
    service = ExportJobService()
    try:
        assert service.recover_interrupted(tmp_path) == 1
        assert service.get(tmp_path, "job-1").status == "interrupted"
    finally:
        service.close(wait=True)
~~~

再覆盖 failed job 不阻塞新 job、同一 task 的 completed job 可以再次导出和 open-output 路径校验。

增加应用生命周期测试：进入 TestClient 上下文时会调用 recover_interrupted；离开上下文时会调用 close(wait=True)。测试中的 fake service 记录调用次数，不能真的启动线程池。

- [ ] **Step 2: 运行失败测试**

Run:

~~~powershell
uv run pytest tests/test_export_jobs.py -q
~~~

Expected: 新模块不存在或作业接口未实现，测试失败。

- [ ] **Step 3: 实现原子 repository**

状态文件固定在：

~~~text
workspace/state/export_jobs/<job_id>.json
~~~

repository 提供 save、load、list、find_active。每次写入使用临时文件和 os.replace。损坏 JSON 跳过并记录 error，不阻止其他 job 列表读取。

- [ ] **Step 4: 实现单 worker 后台执行**

使用应用级 ThreadPoolExecutor(max_workers=1)，并用 threading.Lock 保护 active job 的检查和提交：

1. 查找同 task 的 queued/running job；
2. 有活动 job 时直接返回；
3. 没有时写 queued；
4. 提交后台函数并立即返回；
5. 后台函数写 running；
6. 将 BuildProgress 映射到 ExportJob 并原子保存；
7. 成功后保存 build_id、output_dir 和 completed；
8. 异常后保存 failed 和异常类型/消息；
9. 调用 SubmissionRepository 更新 last_export 摘要。

后台线程只能调用 PackageBuilder，不修改 MonthlyPlan。close(wait=True) 调用 executor.shutdown(wait=True, cancel_futures=False)，让已排队和正在运行的真实导出进入 completed/failed 终态后再关闭 Web 进程；close 后再次 start 必须明确报错。进程崩溃来不及 close 时，持久化的 queued/running job 由下一次启动的 recover_interrupted 标记为 interrupted。

- [ ] **Step 5: 接入 FastAPI lifespan**

create_app 先解析一次 publishing_root，并通过 asynccontextmanager 管理应用级 ExportJobService：

~~~python
from contextlib import asynccontextmanager


def create_app(root: str | Path) -> FastAPI:
    publishing_root = Path(root).expanduser().resolve()
    export_jobs = ExportJobService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recovered = export_jobs.recover_interrupted(publishing_root)
        if recovered:
            logger.warning("Web 启动时恢复中断导出：count=%s", recovered)
        try:
            yield
        finally:
            export_jobs.close(wait=True)

    app = FastAPI(
        title="Publishing Workspace Schedule API",
        lifespan=lifespan,
    )
    app.state.publishing_root = publishing_root
    app.state.export_jobs = export_jobs
    register_library_routes(app)
    # 现有计划、旧素材搜索和静态页面路由继续在这里注册。
    return app
~~~

所有导出路由只访问 app.state.export_jobs。应用状态在 create_app 返回前就可用，避免不进入 lifespan 的旧只读调用丢失 publishing_root；启动恢复仍必须在正式接受请求前完成，关闭等待发生在 TestClient/uvicorn lifespan 退出期间。tests/test_schedule_api.py 和新增 Web 测试把 client helper 改为 yield fixture 或显式 `with TestClient(create_app(root)) as client:`，确保每个测试都执行 startup/shutdown。

- [ ] **Step 6: 实现安全打开目录**

只接受 job 中已保存的 output_dir：

~~~python
candidate = Path(job.output_dir).resolve()
workspace_root = paths.root.resolve()
candidate.relative_to(workspace_root)
if not candidate.is_dir():
    raise ExportOutputNotFoundError(f"导出目录不存在：{candidate}")
~~~

Windows 使用 os.startfile(str(candidate))；目录不存在抛 ExportOutputNotFoundError，映射为 404 export_output_not_found。非 Windows、无桌面环境或 os.startfile 失败时抛 ExportOutputOpenError，响应 422 export_output_open_failed，并在 detail.output_dir 返回已校验路径。禁止直接使用前端提交的任意路径调用系统命令。

- [ ] **Step 7: 注册 Web API**

新增：

~~~text
POST /api/submissions/{task_id}/exports
GET  /api/export-jobs/{job_id}
GET  /api/submissions/{task_id}/exports
POST /api/export-jobs/{job_id}/open-output
~~~

新建 job 返回 202；已有活动 job 返回 200；页面刷新通过 list_for_task 恢复最近状态。

- [ ] **Step 8: 运行作业和 API 测试**

Run:

~~~powershell
uv run pytest tests/test_export_jobs.py tests/test_schedule_api.py -q
~~~

Expected: 状态转换、并发去重、失败保留、启动恢复、关闭等待和目录安全校验通过。

- [ ] **Step 9: 提交**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/export_jobs tools/publishing_workspace/src/publishing_workspace/web/library_api.py tools/publishing_workspace/src/publishing_workspace/web/schedule_api.py tools/publishing_workspace/tests/test_export_jobs.py tools/publishing_workspace/tests/test_schedule_api.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: add background submission export jobs"
~~~

---

### Task 7: 接入素材库保存、导出进度和日历导航

**Files:**
- Modify: src/publishing_workspace/web/static/library.html
- Modify: src/publishing_workspace/web/static/library.js
- Modify: src/publishing_workspace/web/static/library.css
- Modify: src/publishing_workspace/web/static/calendar.html
- Modify: src/publishing_workspace/web/static/calendar.js
- Test: tests/test_web_pages.py

**Interfaces:**

前端函数边界：

~~~text
loadAssetPage({reset: boolean = false}) -> Promise<void>
loadSubmission(taskId: string) -> Promise<void>
saveSubmission() -> Promise<void>
startExport(taskId: string) -> Promise<void>
pollExport(jobId: string) -> Promise<void>
~~~

- [ ] **Step 1: 实现素材库状态模型**

library.js 状态至少包含：

- filters 快照；
- offset；
- hasMore；
- loadingPage；
- requestToken；
- selectedAssetIds；
- 当前 Submission 的 all/post/cover 有序数组；
- 当前集合名称；
- 当前 submission revision；
- legacyInlineSource（plan_id、entry_id、plan_revision 或 null）；
- active export job。

筛选变化递增 requestToken；旧响应的 token 不等于当前 token 时直接丢弃，避免慢请求覆盖新结果。

- [ ] **Step 2: 实现瀑布流加载**

初始请求 offset=0、limit=60。IntersectionObserver 只在 hasMore 且没有 loadingPage 时触发。追加结果使用 asset_id 去重。筛选重置时取消 AbortController、清空卡片和 selectedAssetIds，再请求第一页。

图片卡片使用 API 的 width/height 设置 aspect-ratio，实际图片懒加载。分页结束显示“已加载全部”，错误显示可重试按钮。

- [ ] **Step 3: 实现 Submission 编辑器**

右侧支持：

- 历史投稿列表；
- 新建按钮；
- title；
- all/post/cover 标签；
- 图片移除和拖拽排序；
- 从中间选中图片加入当前集合；
- 保存；
- 保存后用服务端返回的 sets、revision、task_id 覆盖本地状态。

默认加入 all；后端负责 post/cover 补齐，前端只显示补齐结果，不复制规则。

打开 `/library?plan_id=<month>&entry_id=<entry_id>` 时读取现有 plan，只有 content.kind=inline 才把其 title 和 sets 装入编辑器，并记录 plan revision。仅查看或离开页面不迁移。用户第一次明确点击保存时：

1. POST /api/submissions 创建 task；
2. 用服务端返回的 task_id 构造 TaskContent；
3. PUT /api/plans/{month}/entries/{entry_id}，保留原 scheduled_at、title 和 entry_id，只替换 content，并携带读取时的 revision；
4. 更新成功后把 URL 替换为 `/library?submission_id=<task_id>`；
5. 若 plan revision 冲突，新 task 保留为可见的独立投稿，旧 inline entry 不变，页面提示用户刷新后重试，不能静默覆盖。

- [ ] **Step 4: 接入导出轮询**

导出按钮 POST /api/submissions/{task_id}/exports，然后每 1 秒 GET job。显示 phase、processed/total、percent、current_selection、current_filename。

completed 后显示 build_id/output_dir 和“打开导出目录”；failed/interrupted 后显示错误和“重新导出”。页面刷新时读取 task 最近 job，active 状态自动继续轮询。

- [ ] **Step 5: 实现 calendar 页面导航**

calendar.js 只保留月计划、日期拖拽、投稿卡片和 task 选择。TaskContent 点击编辑素材跳转 `/library?submission_id=<task_id>`；旧 inline entry 显示 legacy 标记，点击编辑跳转 `/library?plan_id=<month>&entry_id=<entry_id>`，仍可用旧计划 API 移动和删除。

- [ ] **Step 6: 响应式和可访问性检查**

必须验证：

- 1440px 桌面三栏不重叠；
- 900px 以下纵向布局；
- 390px 文字不溢出；
- 图标按钮提供 title/aria-label；
- 瀑布流追加不改变已有卡片位置；
- 真实 preview API 能加载图片。

- [ ] **Step 7: 语法和页面回归**

Run:

~~~powershell
node --check src/publishing_workspace/web/static/calendar.js
node --check src/publishing_workspace/web/static/library.js
uv run pytest tests/test_web_pages.py tests/test_schedule_api.py -q
~~~

- [ ] **Step 8: 提交**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/src/publishing_workspace/web/static/calendar.html tools/publishing_workspace/src/publishing_workspace/web/static/calendar.js tools/publishing_workspace/src/publishing_workspace/web/static/calendar.css tools/publishing_workspace/src/publishing_workspace/web/static/library.html tools/publishing_workspace/src/publishing_workspace/web/static/library.js tools/publishing_workspace/src/publishing_workspace/web/static/library.css tools/publishing_workspace/tests/test_web_pages.py
git -C F:\my_project\new\tags_machine\refactor commit -m "feat: connect submission library workflow"
~~~

---

### Task 8: 兼容回归、文档和真实业务验收

**Files:**
- Modify: README.md
- Modify: docs/acceptance-monthly-publishing-calendar.md
- Create: docs/acceptance-publishing-workspace-two-pages.md
- Test: tests/test_legacy_compatibility.py

**Interfaces:**

兼容测试名称固定为：

~~~text
test_legacy_task_without_submission_yaml_is_listed
test_legacy_inline_plan_remains_readable_and_movable
test_legacy_inline_converts_only_after_explicit_submission_save
test_old_asset_search_array_contract_is_unchanged
~~~

- [ ] **Step 1: 增加旧 task 和 inline 测试**

旧 task 测试只创建 task.yaml 和 selection 图片，不预先创建 submission.yaml。确认它能在 /api/submissions 列出、详情可读、仍能调用旧 task build。

旧 inline 计划测试确认：

- GET /api/plans/{month} 仍能读取；
- PATCH 日期仍有效；
- 删除仍有效；
- 只打开素材库不会隐式迁移它；
- 模拟显式保存后，entry 保留原 entry_id、scheduled_at 和 title，只把 InlineContent 替换为指向新 task 的 TaskContent。

旧 assets/search 测试确认响应顶层仍为数组，且原字段不减少。

- [ ] **Step 2: 更新 README**

加入启动命令：

~~~powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run publishing-workspace web G:\ai_publish --host 127.0.0.1 --port 61302 --log-level info
~~~

说明：

- /calendar 只负责日期和时间；
- /library 负责素材筛选、投稿保存和导出；
- 保存投稿会生成 tasks/<task_id>；
- all/post/cover 补齐规则；
- 导出进度、失败重试和打开目录；
- 旧 schedule.html、旧 API 和 inline 计划的兼容语义。

- [ ] **Step 3: 编写业务验收记录模板**

记录字段固定为：

~~~text
workspace:
import_id:
filters:
asset_count_page_1:
asset_count_page_2:
submission_task_id:
all_count:
post_count:
cover_count:
export_job_id:
build_id:
output_dir:
png_cleanup_verified:
mosaic_verified:
calendar_move_verified:
legacy_compat_verified:
result:
~~~

- [ ] **Step 4: 运行全量自动化检查**

Run:

~~~powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest -q
node --check src/publishing_workspace/web/static/calendar.js
node --check src/publishing_workspace/web/static/library.js
~~~

Expected: 全部通过；历史 warning 记录来源，不通过删除测试消除。

- [ ] **Step 5: 运行真实业务验收**

使用一个小规模真实 import 或现有 workspace：

1. 在素材库组合节点和 classify facet 筛选；
2. 加载至少两页瀑布流；
3. 选择图片并保存投稿；
4. 关闭并重新打开页面确认历史投稿和顺序；
5. 真实执行导出；
6. 确认 PNG 参数清除；
7. 若 workspace 开启 mosaic，确认打码输出；
8. 打开实际 build 目录；
9. 在日历移动日期；
10. 重新打开素材库确认 task 不变；
11. 打开旧 task 和旧 inline 计划确认兼容；只查看不迁移，并在测试副本中显式保存一次确认懒转换成功。

不使用 dry-run 代替业务验收。

- [ ] **Step 6: 提交文档和验收记录**

~~~powershell
git -C F:\my_project\new\tags_machine\refactor add -- tools/publishing_workspace/README.md tools/publishing_workspace/docs/acceptance-monthly-publishing-calendar.md tools/publishing_workspace/docs/acceptance-publishing-workspace-two-pages.md tools/publishing_workspace/tests/test_legacy_compatibility.py
git -C F:\my_project\new\tags_machine\refactor commit -m "docs: document two-page publishing workflow"
~~~

---

## 完成门槛

实现不得以“页面能打开”作为完成标准。必须同时满足：

1. /calendar 和 /library 是独立页面；
2. 素材分页没有重复、跳过和旧请求覆盖新请求；
3. 保存投稿真实生成 task 和 submission.yaml；
4. 旧 task、旧 API、旧 inline 计划仍可用；
5. 导出调用真实 PackageBuilder；
6. 页面能显示真实导出阶段和文件进度；
7. 清 PNG 参数、mosaic、ZIP 和 build manifest 结果保持；
8. 完成一次真实 workspace 业务导出；
9. 全量 pytest、JavaScript 语法检查和页面回归通过；
10. 工作区其他既有修改没有被回滚或混入提交。
