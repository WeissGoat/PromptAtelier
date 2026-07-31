# Publishing Workspace unknown 节点投影设计

## 1. 背景

Publishing Workspace 支持从 NeeView 播放列表、目录和快捷方式导入图片，并通过两种 Reader 读取图片内嵌的旧版或新版节点信息。Reader 返回的是图片实际存在的原始节点：某些图片可能没有 `artist`、`character`、`action_group` 或 `action`，甚至完全没有可识别的节点。

当前 `ClassificationViewBuilder` 已经可以在部分层级缺失时临时使用 `missing_value`，但这个回退只存在于分类器内部：

- Catalog 中保存的节点仍然是不完整的；
- 后续筛选器或新的 Exporter 需要重新实现缺失值逻辑；
- “Reader 没读到节点”和“分类路径使用 unknown”没有明确边界；
- 全部节点缺失的图片虽然理论上可以分类，但没有统一的下游数据结构。

本次将 `unknown` 变成统一的运行时节点投影值，使缺失图片能够正常进入正式分类和导出。

## 2. 目标

1. 对当前分类层级中的每个 role 提供确定的值。
2. 缺失节点默认使用 `classification.missing_value`，默认值为 `unknown`。
3. `skip_missing: false` 时，缺失图片正常生成分类视图并正常导出。
4. 保留 Reader 和 Catalog 中的原始节点，不伪造图片元数据。
5. 不修改 SQLite schema，不要求迁移已有 Catalog。
6. 分类器、现有 Exporter 和未来 Exporter 使用同一个标准节点投影接口。
7. 保留多角色、多动作节点的多值语义，不把多个节点压缩成单值。

## 3. 非目标

- 不修改图片 PNG 内嵌信息。
- 不改变 Core Reader、Legacy Reader 的识别优先级。
- 不把 `unknown` 写入 `asset_nodes`，也不改变 Reader 统计中的 `unknown` 含义。
- 不改变 `ActionGroupManifestEnricher` 的动作组补全规则。
- 不新增投稿任务、二次筛选或图片处理功能。

## 4. 术语与边界

### 4.1 原始节点

原始节点是 Reader 或 Enricher 实际得到的 `ImageNodeInfo.nodes`。它只描述图片元数据中确实存在的节点，例如：

```json
[
  {"role": "artist", "id": "20260412"},
  {"role": "action", "id": "foot_detail"}
]
```

原始节点不因分类配置而改变。

### 4.2 标准节点投影

标准节点投影是按照当前分类配置对原始节点解析后的下游输入。它覆盖 `classification.hierarchy` 中的每一个 role，并记录哪些 role 是通过缺失值补出的。

示例：

```json
{
  "values": {
    "artist": ["20260412"],
    "character": ["unknown"],
    "action_group": ["st_foot"],
    "action": ["foot_detail"]
  },
  "missing_roles": ["character"]
}
```

标准投影是运行时结果，不写回 Catalog。改变 `hierarchy` 或 `missing_value` 后，可以重新得到新的投影。

## 5. 配置语义

```yaml
classification:
  hierarchy:
    - artist
    - character
    - action_group
    - action
  missing_value: unknown
  skip_missing: false
```

- `hierarchy`：需要生成分类路径的节点 role。只有列在这里的 role 才参与补值。
- `missing_value`：某个 role 没有有效值时使用的目录名和标准投影值。必须是非空字符串，默认是 `unknown`。
- `skip_missing`：显式控制是否排除缺失节点的图片。
  - `false`：使用 `missing_value`，正常进入正式分类和导出。
  - `true`：只要 `missing_roles` 非空，就不生成该图片的分类视图。

`skip_missing` 是兼容现有配置的显式过滤开关；默认值保持 `false`，因此默认行为是“缺失也正常导出”。

## 6. 运行时接口

在 `models.py` 增加标准投影模型，建议接口如下：

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

`AssetRecord` 增加：

```python
def node_projection(
    self,
    hierarchy: list[str],
    *,
    missing_value: str = "unknown",
) -> NodeValueProjection:
    ...
```

投影规则：

1. 按 `hierarchy` 原顺序处理 role。
2. 调用原始 `ImageNodeInfo.values_for(role)` 获取有效值。
3. 有效值保留原顺序并去重。
4. 没有有效值时，将该 role 的值设为 `[missing_value]`，并加入 `missing_roles`。
5. 不在 `hierarchy` 中的原始 role 不进入投影。
6. `missing_value` 为空时直接抛出配置错误，不能生成空目录。

`ImageNodeInfo.values_for()` 保持原始语义，不默认返回 `unknown`。这样 `ActionGroupManifestEnricher` 仍能正确判断 action_group 是否真实存在，避免把虚拟默认值误认为 Reader 已经读到了节点。

## 7. 分类链路

`ClassificationViewBuilder` 不再自己重复实现缺失值拼接，而是：

1. 为每个 Asset 创建 `NodeValueProjection`。
2. `skip_missing=true` 且投影存在 `missing_roles` 时跳过该 Asset。
3. 否则将投影中每个 role 的值作为一个维度。
4. 对多值维度执行现有笛卡尔积逻辑。
5. 继续按现有自然排序和源顺序生成 `ExportPlan`。

示例一，图片没有任何可读节点：

```text
hierarchy = artist/character/action_group/action
path = unknown/unknown/unknown/unknown
```

示例二，图片只有 artist 和 action：

```text
path = 20260412/unknown/unknown/foot_detail
```

示例三，图片有两个 character，action_group 缺失：

```text
20260412/akemi_homura/unknown/standing
20260412/madoka/unknown/standing
```

## 8. 导出链路

Exporters 不需要识别或过滤 `unknown`。它们继续接收 `ExportPlan.views`，因此 `unknown` 与普通目录名具有完全相同的导出语义：

- NeeView Exporter 生成对应的 `.nvpls`；
- Windows Shortcut Exporter（启用时）生成对应的分类目录；
- 增量导出 hash 将 `unknown` 路径作为普通 view path 参与计算；
- 重复执行仍按现有逻辑返回 `skipped`。

默认情况下，完全缺失节点的图片会进入：

```text
workspace/exports/neev/unknown/unknown/unknown/unknown.nvpls
```

路径清理仍由现有 Exporter 负责，`unknown` 不增加特殊分支。

## 9. 数据与兼容性

- `assets`、`asset_nodes`、`imports` 和 `import_items` 表不变。
- 旧 Catalog 无需迁移。
- 原始 `reader_counts` 不变：Reader 无法解析时仍统计为 `unknown`。
- `NodeValueProjection` 中的 `unknown` 不代表 Reader 类型；它只代表某个分类 role 缺失。
- 现有 `AssetRecord.node_values(role)` 和 `ImageNodeInfo.values_for(role)` 保留，避免影响 Reader、Enricher 和已有调用方。
- 未来需要“只显示原始完整节点”时，可根据 `missing_roles` 过滤，而不必重新读取图片。

## 10. 验收标准

### 10.1 业务验收

使用现有 Publishing Workspace 真实导入结果验证：

1. 完整节点图片仍进入原有分类路径。
2. 只缺少一个节点的图片进入对应 `unknown` 层级。
3. 完全没有节点的图片进入 `unknown/unknown/unknown/unknown`。
4. `export` 能生成包含这些图片的 `.nvpls`，不因缺少节点失败。
5. 重复执行导出时，内容不变的 `unknown` 视图返回 `skipped`。
6. 多角色和多动作图片仍生成多个视图，缺失维度只补一次 `unknown`。
7. `skip_missing: true` 时缺失节点图片不进入视图；完整节点图片行为不变。

### 10.2 自动化验证

至少覆盖：

- 全部 role 缺失；
- 单个 role 缺失；
- 多值 role 与缺失 role 的组合；
- 自定义 `missing_value`；
- 空 `missing_value` 配置被拒绝；
- `skip_missing` 为 `true` 和 `false`；
- NeeView 导出未知路径；
- 重复导出的增量状态。

### 10.3 真实列表验证

对 `G:\ai_publish` 的现有 Catalog 使用：

```powershell
uv run publishing-workspace classify G:\ai_publish --log-level info
uv run publishing-workspace export G:\ai_publish --exporter neev --log-level info
```

验证报告需要记录：

- 生成的总视图数；
- 包含 `unknown` 的视图数；
- 完全缺失节点图片数量；
- `.nvpls` 写入数和跳过数；
- 重复执行后的 skipped 数量。

## 11. 实现范围

预计修改：

- `src/publishing_workspace/models.py`：增加投影模型和 Asset 投影接口；
- `src/publishing_workspace/views/builder.py`：统一使用投影；
- `src/publishing_workspace/config.py`：补充 `missing_value` 非空校验；
- `tests/test_pipeline.py`：增加投影、分类和导出验收；
- `README.md`：补充 unknown 语义和示例。

不修改：

- Reader 实现；
- PNG 解析；
- SQLite schema；
- NovelAI 或 tags_machine_core 代码。
