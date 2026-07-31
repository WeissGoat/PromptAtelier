# Publishing unknown 节点投影 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Publishing Workspace 增加统一的运行时节点投影，让分类层级中的缺失节点默认使用 `unknown`，并在 `skip_missing: false` 时正常生成和导出分类视图。

**Architecture:** Reader 和 Catalog 继续保存图片实际读取到的原始节点；`AssetRecord.node_projection()` 根据当前分类层级生成完整的标准节点投影，并记录缺失 role。`ClassificationViewBuilder` 只消费这个投影，Exporter 继续消费现有 `ExportPlan`，不新增 Exporter 特殊逻辑，也不修改 SQLite schema。

**Tech Stack:** Python 3.11+, Pydantic 2, PyYAML, pytest, Pillow, SQLite, `uv`。

## Global Constraints

- 只对 `classification.hierarchy` 中声明的 role 补 `classification.missing_value`，默认值为 `unknown`。
- `skip_missing: false` 时缺失图片必须正常进入正式分类和导出；`true` 时仍可显式排除缺失图片。
- `ImageNodeInfo.values_for()` 保持原始语义，不默认返回 `unknown`。
- 不把虚拟 `unknown` 节点写入 `asset_nodes`，不修改 PNG 元数据，不修改 SQLite schema。
- 保留多角色、多动作的多值语义和现有笛卡尔积行为。
- 不修改 Reader、Enricher、NovelAI 或 `tags_machine_core` 代码。
- 保留工作区已有未提交文件，不将其加入本功能提交。

---

### Task 1: 增加标准节点投影模型

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/models.py`
- Modify: `tools/publishing_workspace/src/publishing_workspace/config.py`
- Test: `tools/publishing_workspace/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ImageNodeInfo.values_for(role)`、分类层级 `list[str]` 和 `missing_value: str`。
- Produces: `NodeValueProjection`，以及 `AssetRecord.node_projection(hierarchy, missing_value)`。

- [ ] **Step 1: 写标准投影的失败测试**

在 `test_pipeline.py` 增加导入：

```python
from publishing_workspace.models import AssetRecord, AssetFingerprint, AssetImageInfo, ImageNodeInfo, ImageNodeRef
```

增加测试辅助对象和测试：

```python
def _asset_with_nodes(nodes: list[ImageNodeRef]) -> AssetRecord:
    return AssetRecord(
        asset_id="sha256:test",
        path="F:/images/test.png",
        fingerprint=AssetFingerprint(size=1, modified_ns=1, sha256="test"),
        image=AssetImageInfo(width=32, height=48, format="PNG"),
        node_info=ImageNodeInfo(format="core", reader="core", nodes=nodes),
    )


def test_asset_node_projection_fills_missing_roles_and_keeps_multiple_values():
    asset = _asset_with_nodes(
        [
            ImageNodeRef(role="artist", id="artist_a"),
            ImageNodeRef(role="character", id="homura", index=0),
            ImageNodeRef(role="character", id="madoka", index=1),
            ImageNodeRef(role="action", id="standing"),
        ]
    )

    projection = asset.node_projection(
        ["artist", "character", "action_group", "action"],
        missing_value="unknown",
    )

    assert projection.values == {
        "artist": ["artist_a"],
        "character": ["homura", "madoka"],
        "action_group": ["unknown"],
        "action": ["standing"],
    }
    assert projection.missing_roles == ["action_group"]
    assert projection.has_missing is True


def test_asset_node_projection_rejects_empty_missing_value():
    asset = _asset_with_nodes([])

    with pytest.raises(ValueError, match="missing_value"):
        asset.node_projection(["artist"], missing_value=" ")
```

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest tests/test_pipeline.py -k "node_projection" -v
```

预期：新增测试失败，原因是 `AssetRecord.node_projection` 尚未存在。

- [ ] **Step 2: 实现最小投影模型**

在 `models.py` 的 `ImageNodeInfo` 与 `AssetRecord` 之间增加：

```python
class NodeValueProjection(BaseModel):
    hierarchy: list[str]
    missing_value: str
    values: dict[str, list[str]]
    missing_roles: list[str] = Field(default_factory=list)

    def values_for(self, role: str) -> list[str]:
        return list(self.values.get(role, []))

    @property
    def has_missing(self) -> bool:
        return bool(self.missing_roles)
```

在 `AssetRecord` 中增加：

```python
def node_projection(
    self,
    hierarchy: list[str],
    *,
    missing_value: str = "unknown",
) -> NodeValueProjection:
    normalized_hierarchy = [str(role).strip() for role in hierarchy if str(role).strip()]
    normalized_missing = str(missing_value or "").strip()
    if not normalized_missing:
        raise ValueError("missing_value 不能为空")

    values: dict[str, list[str]] = {}
    missing_roles: list[str] = []
    for role in normalized_hierarchy:
        role_values = self.node_info.values_for(role)
        if role_values:
            values[role] = role_values
        else:
            values[role] = [normalized_missing]
            missing_roles.append(role)
    return NodeValueProjection(
        hierarchy=normalized_hierarchy,
        missing_value=normalized_missing,
        values=values,
        missing_roles=missing_roles,
    )
```

在 `config.py` 为 `ClassificationConfig.missing_value` 增加非空校验，校验后的值去除首尾空格：

```python
@field_validator("missing_value")
@classmethod
def validate_missing_value(cls, value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("classification.missing_value 不能为空")
    return normalized
```

不要修改 `ImageNodeInfo.values_for()` 的默认行为，否则 `ActionGroupManifestEnricher` 会把虚拟默认值当成真实 action_group。

- [ ] **Step 3: 运行模型测试**

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "node_projection" -v
```

预期：2 个测试 PASS。

- [ ] **Step 4: 验证原始 Reader 语义未改变**

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "reader_prefers_core or import_enriches_action_group" -v
```

预期：Reader 回退和 action_group manifest 补全测试 PASS；`values_for("action_group")` 在真实缺失时仍返回空列表，enricher 仍会工作。

- [ ] **Step 5: 提交模型变更**

```powershell
git add -- tools/publishing_workspace/src/publishing_workspace/models.py tools/publishing_workspace/src/publishing_workspace/config.py tools/publishing_workspace/tests/test_pipeline.py
git commit -m "feat(publishing): add unknown node projection"
```

---

### Task 2: 让分类器统一消费标准投影

**Files:**
- Modify: `tools/publishing_workspace/src/publishing_workspace/views/builder.py`
- Test: `tools/publishing_workspace/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `AssetRecord.node_projection()` 返回的 `NodeValueProjection`。
- Produces: 与现有 schema 相同的 `ExportPlan`；缺失节点产生普通 `ViewEntry`。

- [ ] **Step 1: 写分类行为的失败测试**

在测试文件增加：

```python
from publishing_workspace.views.builder import ClassificationViewBuilder


def test_classification_builds_full_unknown_path_for_asset_without_nodes():
    asset = _asset_with_nodes([])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action_group", "action"],
        missing_value="unknown",
        skip_missing=False,
    )

    assert [view.key for view in plan.views] == [
        "unknown/unknown/unknown/unknown",
    ]
    assert plan.views[0].items[0].asset_id == asset.asset_id


def test_classification_can_explicitly_skip_missing_projection():
    asset = _asset_with_nodes([ImageNodeRef(role="artist", id="artist_a")])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action"],
        missing_value="unknown",
        skip_missing=True,
    )

    assert plan.views == []


def test_classification_uses_custom_missing_value_in_each_missing_dimension():
    asset = _asset_with_nodes([ImageNodeRef(role="action", id="standing")])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action"],
        missing_value="未分类",
        skip_missing=False,
    )

    assert [view.key for view in plan.views] == [
        "未分类/未分类/standing",
    ]
```

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "classification_builds_full_unknown or classification_can_explicitly_skip or custom_missing_value" -v
```

预期：新增测试先失败或暴露 builder 未使用标准投影的问题。

- [ ] **Step 2: 修改 ClassificationViewBuilder**

将当前逐 role 的缺失值处理替换为标准投影：

```python
for asset in assets:
    projection = asset.node_projection(
        hierarchy,
        missing_value=missing_value,
    )
    if skip_missing and projection.has_missing:
        continue
    dimensions = [projection.values_for(role) for role in projection.hierarchy]
    for path in product(*dimensions):
        views.setdefault(tuple(path), []).append(
            ViewItem(
                asset_id=asset.asset_id,
                source_path=asset.path,
                display_name=asset.display_name or asset.path.rsplit("/", 1)[-1],
                order=asset.source_order,
            )
        )
```

保留现有的路径自然排序、成员排序和 `ExportPlan` 结构，不为 `unknown` 添加分支。

- [ ] **Step 3: 运行分类测试**

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "classification_" -v
```

预期：全缺失、显式跳过和自定义缺失值测试 PASS。

- [ ] **Step 4: 运行已有多角色和 manifest 测试**

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "multi_character or enriches_action_group" -v
```

预期：多角色仍生成多个 character 视图，action_group manifest 补全结果不变。

- [ ] **Step 5: 提交分类变更**

```powershell
git add -- tools/publishing_workspace/src/publishing_workspace/views/builder.py tools/publishing_workspace/tests/test_pipeline.py
git commit -m "feat(publishing): classify missing nodes as unknown"
```

---

### Task 3: 导出验收、文档和真实工作区验证

**Files:**
- Modify: `tools/publishing_workspace/tests/test_pipeline.py`
- Modify: `tools/publishing_workspace/README.md`
- Modify: `tools/publishing_workspace/docs/acceptance-phase-1.md`

**Interfaces:**
- Consumes: Task 2 生成的 `ExportPlan`，以及现有 `NeeViewPlaylistExporter` 和增量导出状态。
- Produces: unknown 分类的 `.nvpls`、文档中的配置说明和真实工作区验收记录。

- [ ] **Step 1: 写未知分类导出的失败测试**

在 `test_pipeline.py` 增加端到端测试：

```python
def test_full_pipeline_exports_unknown_nodes_and_skips_on_repeat(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "unknown.png")
    root = tmp_path / "publish"
    service = PublishingService()
    service.initialize(root)

    imported = service.import_source(root, source)
    plan, first_export = service.export(root)
    _, second_export = service.export(root)

    assert imported.imported_items == 1
    assert [view.key for view in plan.views] == [
        "unknown/unknown/unknown/unknown",
    ]
    assert first_export.results[0].written == 1
    assert second_export.results[0].skipped == 1

    paths, _ = load_workspace(root)
    playlist = paths.exports / "neev" / "unknown" / "unknown" / "unknown" / "unknown.nvpls"
    assert playlist.is_file()
    assert json.loads(playlist.read_text(encoding="utf-8"))["Items"] == [
        {"Path": str((source / "unknown.png").resolve())}
    ]
```

运行：

```powershell
uv run pytest tests/test_pipeline.py -k "exports_unknown_nodes" -v
```

预期：测试在导出链路还未被投影接通时失败，完成后 PASS。

- [ ] **Step 2: 补全 README 配置和结果说明**

在 `tools/publishing_workspace/README.md` 的 `workspace.yaml` 和分类章节补充：

```markdown
`classification.missing_value` 默认是 `unknown`。分类层级中的任意节点缺失时，Publishing Workspace 会在运行时投影该值；原始 Reader 和 Catalog 不会被修改。

默认 `skip_missing: false`，所以没有节点信息的图片也会导出到：

`unknown/unknown/unknown/unknown`

只有显式设置 `skip_missing: true`，缺少任意分类节点的图片才会被排除。
```

同时补充自定义 `missing_value` 的例子，并说明 Reader `unknown` 与节点路径 `unknown` 是两个不同概念。

- [ ] **Step 3: 运行完整自动化测试**

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest -q
```

预期：已有测试和新增测试全部 PASS，退出码为 0。

- [ ] **Step 4: 对真实 G:\ai_publish 做分类计划验证**

运行：

```powershell
uv run publishing-workspace classify G:\ai_publish --log-level info
```

记录输出计划中的：

- 总视图数量；
- 包含 `unknown` 的视图数量；
- `unknown/unknown/unknown/unknown` 是否存在（若当前 Catalog 没有完全缺失节点则允许为 0）；
- 现有完整节点路径是否仍存在。

- [ ] **Step 5: 对真实 G:\ai_publish 做 NeeView 导出验证**

运行：

```powershell
uv run publishing-workspace export G:\ai_publish --exporter neev --log-level info
uv run publishing-workspace export G:\ai_publish --exporter neev --log-level info
```

预期：

- 第一次只写入新增或变化视图；
- 第二次相同内容返回 `skipped`；
- 含 `unknown` 的视图可以生成 `.nvpls`；
- 原始图片路径保持不变，没有复制或重命名图片。

- [ ] **Step 6: 更新验收记录并提交**

把实际结果追加到 `docs/acceptance-phase-1.md`，包含执行时间、视图数量、unknown 视图数量、写入数和 skipped 数，不伪造没有实际运行得到的数字。

```powershell
git add -- tools/publishing_workspace/tests/test_pipeline.py tools/publishing_workspace/README.md tools/publishing_workspace/docs/acceptance-phase-1.md
git commit -m "test(publishing): verify unknown node export"
```

---

## 完成检查

实现完成前逐项确认：

- [ ] `NodeValueProjection` 只在运行时生成，不污染 Reader 和 Catalog。
- [ ] `ImageNodeInfo.values_for()` 原始语义不变，manifest enricher 仍能补 action_group。
- [ ] 默认缺失图片生成完整 `unknown` 路径。
- [ ] `skip_missing=true` 仍能显式排除缺失图片。
- [ ] 多角色、多动作笛卡尔积行为保持不变。
- [ ] NeeView 增量导出第一次写入、第二次跳过。
- [ ] `uv run pytest -q` 退出码为 0。
- [ ] 真实 `G:\ai_publish` 分类和导出已执行并记录实际统计。
- [ ] 未提交的用户文件没有被加入本功能提交。
