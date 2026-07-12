# 节点 Form 与源文件 Diff 保存设计

## 1. 目标

Web Node Editor 不再把完整 `NodeDocument` 当作普通 Form 展示，而是针对节点角色和数据来源提供精简、可理解的编辑模型。

保存时必须更新节点原数据源：

- Artist 保存回原 `tags.txt`。
- Action 保存回原 `tags.txt`；涉及分类数据时可同时保存 `classify.yaml`。
- Character 保存回原 `meta.yaml`。

第一次点击保存只生成源文件 Diff，不修改磁盘。用户在 Diff 弹窗中二次确认后，系统才正式写入文件。

## 2. 当前问题

### 2.1 Form 泄漏运行时结构

当前前端直接从完整 `NodeDocument` 生成 Form。`path`、`legacy`、`renderers`、`generation` 等运行时或兼容层字段会进入“扩展字段”，实际体验仍接近编辑 JSON。

后端 `/nodes/read` 已返回精简的 `form`，但前端没有使用该字段。

### 2.2 保存不区分数据来源

当前 `/nodes/save` 无论节点原本来自 `tags.txt` 还是 `meta.yaml`，都会将完整归一化 `NodeDocument` 写入新的 `meta.yaml`。

这会造成：

- Artist 保存后不再走原有 Artist `tags.txt` 解析链路。
- Action 同时存在旧 `tags.txt` 和包含完整快照的 `meta.yaml`。
- Character 的 `meta.yaml` 被写入大量运行时、路径及 legacy 字段。
- Form 保存结果与其他使用原提示词库的工具不一致。

## 3. 核心边界

系统明确区分三种对象：

```text
源文件 Source Document
  tags.txt / meta.yaml / classify.yaml
             ↓ SourceAdapter.read
Form Edit Model              Runtime NodeDocument
适合人编辑的精简字段          供 Composer/Renderer 使用的统一对象
             ↓ SourceAdapter.preview
FileMutation[]
待写入文件、完整目标文本、源文件哈希及 Unified Diff
```

`NodeDocument` 继续作为运行时统一协议，但不再等同于 Form，也不直接作为源文件保存格式。

## 4. 编辑会话协议

`GET /api/nodes/read` 增加 `editor`：

```json
{
  "schema": "tags-machine-core.web.node/v2",
  "ref": "F:/.../design/画风/20260412",
  "node": {},
  "editor": {
    "adapter": "legacy_artist_tags/v1",
    "role": "artist",
    "values": {},
    "sources": [
      {
        "path": "F:/.../20260412/tags.txt",
        "format": "tags.txt",
        "sha256": "...",
        "writable": true
      }
    ],
    "capabilities": {
      "save": true,
      "multi_file": false
    }
  }
}
```

前端保存两份状态：

- `editValues`：Form 正在编辑的来源模型。
- `draftNode`：由后端预览接口归一化出的临时 `NodeDocument`，继续用于 Preview 和 Generate。

临时编辑不会自动写入源文件。

## 5. 角色 Form

### 5.1 Artist

普通 Form 只展示：

- 节点名称。
- Prompt Prefix，每行一个片段。
- Prompt Suffix，每行一个片段。
- Negative Prompt。
- After Negative Prompt。
- 模型。
- Sampler。
- Steps。
- Scale。
- Noise Schedule。
- 常用布尔参数。
- Flags。

不展示：

- `path`。
- `legacy`。
- `renderers.novelai.path`。
- `artist_ref` 等可从来源推导的字段。
- 未识别的内部结构。

高级 JSON 页仍可查看归一化 `NodeDocument`，但保存仍必须经过来源 Adapter，不能直接把 JSON 覆盖到源文件。

### 5.2 Action

普通 Form 展示：

- 节点名称。
- 动作 Prompt，每行对应 `tags.txt` 的一个 Prompt 段。
- Negative Prompt，仅在源节点支持时显示。
- `selected_keys`。
- 分类标签及少量已正式化的 Action 元数据。

Action 保存可以同时生成：

- `tags.txt` 变更。
- `classify.yaml` 变更。

两个文件在同一个 Diff 弹窗中按文件分别展示并一次确认写入。

### 5.3 Character

普通 Form 展示：

- ID 和名称。
- Description。
- Positive Prompt。
- Negative Prompt。
- `identity_minimal`。
- Relations。
- Tags 分组。

不显示运行时 renderer 数据和 legacy 原文快照。

## 6. SourceAdapter

统一接口：

```python
class NodeSourceAdapter(Protocol):
    adapter_id: str

    def read_editor(self, node_dir: Path) -> NodeEditorDocument: ...

    def build_runtime_node(
        self,
        node_dir: Path,
        values: dict[str, Any],
    ) -> NodeDocument: ...

    def preview_mutations(
        self,
        node_dir: Path,
        values: dict[str, Any],
    ) -> list[FileMutation]: ...
```

首批 Adapter：

- `LegacyArtistTagsAdapter`
- `LegacyActionTagsAdapter`
- `CharacterMetaYamlAdapter`

Adapter 由后端根据 role、目录中实际文件以及节点格式选择。前端不判断 `tags.txt` 或 `meta.yaml`。

### 6.1 tags.txt 保留策略

Artist 和 Action Writer 将 `tags.txt` 解析成有序段落：

- Prompt 行。
- `type` 行。
- `=` 分隔符。
- 已识别扩展行。
- 未识别行。

保存时只重建 Form 管理的段落。未识别行、未知 flags 和未知扩展参数必须原样保留，不能因为 UI 不展示而丢失。

### 6.2 YAML 保存策略

Character Writer 只输出 Character 规范允许的源字段，不将完整 `NodeDocument` 回写到 `meta.yaml`。

首版允许 YAML 格式化发生变化，但所有变化都会在保存前的源文件 Diff 中展示。后续如需保留注释和格式，可将 YAML Writer 切换为 round-trip 实现，不影响接口。

## 7. 两阶段保存

### 7.1 预演

```http
POST /api/nodes/save-preview
```

请求：

```json
{
  "ref": "F:/.../node",
  "role": "artist",
  "adapter": "legacy_artist_tags/v1",
  "values": {}
}
```

后端执行：

1. 重新读取当前源文件。
2. 使用 Adapter 生成目标文本。
3. 对每个文件计算当前 `sha256`。
4. 生成 Unified Diff。
5. 保存短期 `SavePreview`，不修改磁盘。

响应：

```json
{
  "schema": "tags-machine-core.web.node-save-preview/v1",
  "preview_id": "save_01...",
  "node": {},
  "files": [
    {
      "path": "F:/.../tags.txt",
      "format": "tags.txt",
      "before_sha256": "...",
      "changed": true,
      "diff": "--- tags.txt\n+++ tags.txt\n...",
      "after_text": "..."
    }
  ],
  "warnings": [],
  "expires_at": "2026-07-12T16:30:00+08:00"
}
```

`after_text` 仅供折叠查看保存后的完整源文件，不作为最终提交内容从前端传回。

### 7.2 提交

```http
PUT /api/nodes/save-commit
```

请求：

```json
{
  "preview_id": "save_01..."
}
```

提交前必须重新计算所有源文件哈希：

- 哈希一致：原子写入所有文件。
- 哈希不同：返回 `409 source_changed`，不写入任何文件。
- Preview 已过期：返回 `409 save_preview_expired`。

成功后重新通过 Adapter 读取节点，并返回新的 `node` 和 `editor`。

## 8. 多文件原子性

Action 一次保存可能修改 `tags.txt` 和 `classify.yaml`。

提交步骤：

1. 校验所有文件哈希。
2. 为每个目标文件写同目录临时文件。
3. 所有临时文件写入成功后再逐个替换正式文件。
4. 任一临时写入失败时不替换任何正式文件。
5. 替换阶段失败时记录 ERROR 日志，并返回具体文件列表。

首版不实现跨文件系统事务，但源文件都位于同一节点目录，使用同目录临时文件和原子 replace 将风险限制在最小范围。

## 9. Diff 确认弹窗

弹窗结构：

- 标题：`保存 Artist · 20260412`
- 摘要：修改文件数量、警告数量。
- 多文件页签：`tags.txt`、`classify.yaml`。
- Unified Diff：删除红色、新增绿色、上下文灰色。
- 折叠区：保存后的完整源文件。
- 操作按钮：`取消`、`确认写入 N 个文件`。

没有实际变化时：

- 不显示确认写入按钮。
- 提示“源文件没有变化”。

取消弹窗不会修改源文件，也不会清除当前临时草稿。

保存成功后：

- 重新读取源节点。
- 更新 `sourceNode`、`draftNode` 和来源哈希。
- 清除临时修改标记。
- 显示保存成功状态。

## 10. 错误处理

- `unsupported_node_source`：当前来源没有 Writer，只允许临时编辑。
- `source_changed`：源文件在 Diff 预览后被外部修改，要求重新预览。
- `save_preview_expired`：保存预演过期，要求重新预览。
- `invalid_editor_values`：Form 数据不符合对应 Adapter 规范。
- `source_write_failed`：写入失败，返回受影响文件和错误原因。

所有错误必须在前端弹窗或页面提示，不能只写后端日志。

## 11. 日志

- TRACE：Adapter 选择、字段归一化、预演文件列表。
- INFO：保存预演创建、用户确认提交、保存成功。
- WARNING：源文件变化、未知字段被保留、预演过期。
- ERROR：序列化失败、临时写入失败、原子替换失败。

日志不得输出 NovelAI Token，也不应完整输出可能很长的 Prompt；Prompt 使用长度和 sha256 摘要。

## 12. 验收标准

### 12.1 Artist

1. 从真实 Artist `tags.txt` 载入 Form。
2. Form 不显示 `legacy/path/renderers` 等内部字段。
3. 修改一个 Prompt tag 后点击保存。
4. Diff 弹窗只显示 `tags.txt` 的对应变化。
5. 取消后源文件 sha256 不变。
6. 再次预演并确认后，原 `tags.txt` 被更新且没有新增 `meta.yaml`。
7. 重新读取、Preview 和真实出图使用保存后的 Artist。

### 12.2 Action

1. 修改 Action Prompt 和 `selected_keys`。
2. Diff 弹窗分别展示 `tags.txt` 和 `classify.yaml`。
3. 确认后两个文件均更新。
4. ScriptComposer 使用新的 Action 数据；AgentComposer 链路不受影响。

### 12.3 Character

1. 修改 Character Prompt 或 tags。
2. Diff 弹窗展示原 `meta.yaml` 与目标 YAML。
3. 保存后的 YAML 不包含 `path`、`legacy` 和运行时 renderer 快照。
4. 重新读取节点结构与保存前预演的 `NodeDocument` 等价。

### 12.4 并发保护

1. 创建保存预演。
2. 外部修改源文件。
3. 点击确认保存。
4. 接口返回 `409 source_changed`，外部修改不得被覆盖。

## 13. 非目标

- 不迁移现有提示词库。
- 不统一强制将所有节点转换成 YAML。
- 不让前端直接解析或序列化 legacy `tags.txt`。
- 不改变 Composer、Renderer 或 NovelAI Client 的输入协议。
- 不让 Form 自动保存到磁盘。
