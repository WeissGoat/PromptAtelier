# Web 临时节点编辑设计

## 目标

Custom 页面支持在不修改节点库文件的情况下临时编辑节点，并使用编辑后的内容进行提示词预览和真实生图。同时支持从空白模板创建临时节点。

两种入口统一为同一种数据模型：当前浏览器标签页内维护的 `NodeDocument` 草稿。

## 范围

本期覆盖 Custom 页的 Artist、Character 和 Action 节点：

- 已有节点可以读取后临时编辑。
- 可以不选择已有节点，直接新建空白临时节点。
- Preview 和 Generate 使用同一份临时节点快照。
- 只有用户明确点击“保存到节点库”才调用持久化接口。
- 页面刷新或关闭标签页后，所有未保存草稿清空。

本期不实现服务器会话、临时文件目录、跨设备同步和自动恢复草稿。

## 核心概念

### 节点槽位

Custom 页中的 Artist、Character、Action 分别是一个节点槽位。每个槽位维护：

```ts
type NodeSlotState = {
  role: "artist" | "character" | "action";
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  state: "empty" | "original" | "modified" | "temporary";
};
```

- `sourceRef`：已选择节点的原始引用。空白临时节点没有来源引用。
- `sourceNode`：从节点库读取的原始快照，用于恢复和判断是否修改。
- `draftNode`：当前参与预览和生成的节点内容。
- `original`：已选择节点，草稿与原始内容一致。
- `modified`：已有节点的草稿被临时修改。
- `temporary`：从空白模板创建、尚未保存的新节点。

`state` 可以由前三个字段推导，前端不必重复持久化。

### 临时节点不是新领域类型

临时节点仍然是标准 `NodeDocument`。系统不增加 `TemporaryNode` 模型，也不在 Composer 或 Renderer 中增加临时节点判断。

临时性只描述它在 Web 页面中的保存状态，不改变提示词生成和生图业务含义。

## 用户交互

### 节点选择

每个节点槽位显示搜索选择器和状态标识。选择节点后，前端调用 `/api/nodes/read`，同时设置 `sourceNode` 与 `draftNode`。

节点操作包括：

- `查看/临时编辑`：打开右侧节点抽屉。
- `新建空白`：清除当前来源，创建对应 role 的最小合法草稿。
- `恢复原节点`：用 `sourceNode` 覆盖 `draftNode`。
- `清空`：移除该槽位的来源和草稿。
- `保存到节点库`：明确确认目标引用后调用 `/api/nodes/save`。

Node Editor 不再常驻 Custom 页中央区域，而是在用户操作具体节点时打开。默认查看态只读，用户点击编辑后才能修改。

### 状态反馈

节点槽位应明确显示：

- `原始节点`
- `临时修改`
- `空白临时节点`

离开未保存草稿、替换当前节点或清空槽位时，前端需要确认，避免误丢编辑内容。页面刷新不会提供恢复机制。

### 空白节点

空白模板按 role 创建最小合法节点：

```yaml
schema: tags-machine-core.node/v1
kind: character
id: temporary-character
prompt:
  positive: []
  negative: []
```

Artist 和 Action 使用对应的 `kind` 与临时 ID。临时 ID 只用于模型校验和日志识别，不作为节点库中的正式 ID。

空白节点允许先创建再编辑，但参与 Preview 或 Generate 前必须包含至少一段有效 positive prompt。完全空白的草稿在界面中标记为“未完成”。

## 请求契约

### 未编辑节点

未编辑节点保持现有引用请求：

```json
{
  "role": "character",
  "ref": "F:/.../design/角色/.../meta.yaml"
}
```

### 临时节点

临时修改和空白临时节点以内联对象传递：

```json
{
  "role": "character",
  "ref": "F:/.../design/角色/.../meta.yaml",
  "node": {
    "schema": "tags-machine-core.node/v1",
    "kind": "character",
    "id": "akemi_homura",
    "prompt": {
      "positive": [
        {"text": "1girl, akemi_homura, long_hair"}
      ],
      "negative": []
    }
  }
}
```

空白临时节点没有真实来源路径，使用仅供追踪的会话引用：

```json
{
  "role": "action",
  "ref": "web-temporary:action:temporary-action",
  "node": {
    "schema": "tags-machine-core.node/v1",
    "kind": "action",
    "id": "temporary-action",
    "prompt": {
      "positive": [
        {"text": "standing, looking_at_viewer"}
      ],
      "negative": []
    }
  }
}
```

现有 `GenerationJsonApi._load_resolved_nodes()` 已支持 `{role, ref, node}`，并以 `node` 内容构造 `ResolvedNode`。因此后端核心链路不需要临时节点兼容分支。

## 数据流

```text
选择已有节点 / 新建空白节点
  -> Web NodeSlotState.draftNode
  -> 节点编辑抽屉校验 NodeDocument
  -> compose.nodes[] 内联 draftNode
  -> GenerationJsonApi
  -> ResolvedNodeSet
  -> ScriptComposer 或 AgentComposer
  -> PromptBundle
  -> Renderer
  -> RenderRequest
  -> Generate Job
```

Preview 成功时，前端保存本次 `compose` 请求快照及返回的 `render_request`。点击 Generate 时，如果节点草稿自 Preview 后发生变化，必须重新 Preview；不能使用旧 `render_request`。

## Composer 与缓存行为

### ScriptComposer

ScriptComposer 直接读取内联 `NodeDocument`，与读取磁盘节点后的行为一致。规则流水线继续只作用于 ScriptComposer，不因临时节点改变。

### AgentComposer

AgentComposer 接收同一份 `ResolvedNodeSet`。其缓存键必须继续基于节点内容快照，而不是只基于 `ref`。因此：

- 草稿内容未变时可以命中已有组合缓存。
- 草稿内容变化时生成不同缓存键。
- 临时编辑不会覆盖磁盘节点，也不会修改旧缓存记录。
- Artist、Character、Action 的临时内容均参与现有节点快照与 hash 计算。

这里不新增“临时节点 prompt cache”。AgentComposer 的持久缓存与 Web 草稿状态保持独立。

## 保存行为

保存是单独的显式动作，不是 Preview 或 Generate 的副作用。

- 修改已有节点：默认保存回原 `sourceRef`，提交前展示目标路径并要求确认。
- 空白临时节点：必须先选择节点库中的目标目录或输入新节点引用。
- 保存成功后重新读取节点，把返回结果设为新的 `sourceNode` 与 `draftNode`，状态变为 `original`。
- 保存失败时保留当前草稿并显示后端错误。

## 校验与错误处理

前端编辑器在提交 Preview、Generate 或 Save 前校验：

- `schema`、`kind`、`id` 满足 `NodeDocument` 基础约束。
- 节点 `kind` 与槽位 role 一致。
- 参与生成的临时节点至少有一段非空 positive prompt。
- 节点拼接模式至少存在一个可用 Character 或 Action 节点。

后端继续使用 `NodeDocument.model_validate()` 做最终校验。校验错误通过现有 JSON API 错误结构返回，并在节点抽屉或 Custom 页生成区域显示。

## 前端组件边界

- `NodePicker`：搜索和选择正式节点，不负责编辑草稿。
- `NodeSlot`：组合选择器、状态和节点操作。
- `NodeEditorDrawer`：查看、编辑和校验一个 `NodeDocument` 草稿。
- `useTemporaryNodes`：维护各槽位的来源、草稿、dirty 状态和请求序列化。
- `CustomStudio`：协调输入模式、Preview 快照、Generate Job 和结果展示。

组件不直接理解 ScriptComposer、AgentComposer 或 NovelAI 参数，只负责产生标准 compose 请求。

## 验收标准

1. 选择 Character 节点，临时修改 positive prompt 后，Preview 显示修改后的内容，磁盘 `meta.yaml` 不变。
2. 使用同一草稿点击 Generate，实际 `render_request` 与 Preview 对应，生成链路读取临时内容。
3. 从空白 Character 或 Action 创建草稿，填写 positive prompt 后能够 Preview 和 Generate。
4. 完全空白草稿不能生成，界面给出明确提示。
5. 恢复原节点后，Preview 回到磁盘节点内容。
6. 替换、清空有未保存修改的节点时出现确认提示。
7. 刷新页面后未保存草稿消失，节点库文件不发生变化。
8. AgentComposer 使用临时节点时，内容变化会改变缓存键；相同内容可以命中相同缓存。
9. ScriptComposer 和 AgentComposer 均不新增针对临时节点的特殊业务分支。
10. 点击显式保存后才写入节点库，并能重新读取保存后的正式节点。

## 非目标

- 不保存浏览器草稿到 localStorage。
- 不在后端维护 Web session cache。
- 不创建 `.tmp` 节点文件。
- 不支持多人协作编辑和冲突合并。
- 不改变 PromptPolicyPipeline、Renderer 或 NovelAI Client 的职责。
