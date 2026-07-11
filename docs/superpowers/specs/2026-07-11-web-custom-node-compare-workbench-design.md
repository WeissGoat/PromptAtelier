# Web Custom 节点对比工作台设计

## 目标

重构 Custom 页面，使节点搜索、临时编辑、对比生成和浏览器状态恢复形成一套连续工作流。

主要目标：

- 节点搜索使用临时下拉浮层，不再长期占据 Nodes 栏高度。
- 节点编辑从侧边抽屉移动到中间工作区，并提供结构化表单与 JSON 双视图。
- Custom 工作台状态在页面切换和浏览器刷新后保持。
- Compare 从独立页面合并到 Custom 的 Nodes 区域，支持每种角色多个 Compare 节点。
- Compare Generate 按 Artist、Character、Action 的笛卡尔积生成图片。
- Negative 默认值为空。

## 页面结构

Custom 工作台保持三栏布局：

```text
左栏 Nodes
  -> 主节点与 Compare 节点
  -> Negative 和生成参数

中栏 Workspace
  -> 默认显示 Prompt Preview
  -> 点击节点后显示结构化节点编辑器

右栏 Generate & Results
  -> 普通 Generate
  -> Compare Generate
  -> Job 状态与生成图片
```

删除侧栏中的 Compare 导航入口，并删除独立 CompareStudio 页面。Compare 是 Custom Nodes 的一种节点组织方式，不再是独立业务模式。

## 节点槽位模型

每种节点角色维护一个主节点和任意数量 Compare 节点：

```ts
type NodeVariantSlot = {
  slotId: string;
  role: "artist" | "character" | "action";
  mode: "primary" | "compare";
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
};

type RoleNodeGroup = {
  primary: NodeVariantSlot;
  compares: NodeVariantSlot[];
};
```

`slotId` 是稳定的浏览器工作台标识，用于编辑定位、持久化和生成结果映射。它不进入节点库，也不参与 NodeDocument 校验。

每种 role 的节点集合为：

```text
已选择的 primary + 已选择的 compare slots
```

未选择节点的 Compare 空槽位不参与生成组合。已创建 `draftNode` 但 positive prompt 为空的临时节点视为未完成节点，阻止生成并显示具体槽位错误。

## Nodes 区域

### 主节点与 Compare 节点

Artist、Character、Action 分别显示：

```text
Role 标题                         [新增 Compare]
[主节点搜索框] [编辑] [空白] [恢复] [清除]
[Compare 标识] [Compare 搜索框] [编辑] [删除]
[Compare 标识] [Compare 搜索框] [编辑] [删除]
```

- 主节点继续支持选择、临时编辑、空白节点、恢复和清除。
- 点击“新增 Compare”添加一个空 Compare 槽位。
- Compare 节点具备与主节点相同的选择、临时编辑和保存能力。
- 删除 Compare 槽位只删除浏览器工作台状态，不修改节点库文件。
- 同一 ref 的多个槽位允许拥有不同临时编辑，生成时视为不同节点。

### 节点显示名称

搜索输入框、搜索结果、节点标题和生成结果只显示节点文件夹名称 `NodeSummary.name`。

界面不显示完整磁盘路径或 relative path。内部仍保留 `sourceRef`，用于读取、保存和生成请求。

同名节点仍以不同 `ref` 作为内部唯一值；用户选择哪个结果，必须提交该结果对应的精确 ref。

## 搜索交互

NodePicker 改为类似浏览器地址栏的组合框：

- 输入框聚焦时显示结果浮层。
- 空查询聚焦时请求并显示前 6 个节点。
- 输入后防抖 300ms 发起搜索。
- 后端请求 `limit=6`。
- 选择结果后关闭浮层。
- 点击组件外部、按 `Escape` 或失去焦点后关闭浮层。
- 浮层使用绝对定位，不参与 Nodes 栏高度计算。
- 搜索结果只显示文件夹名称。
- 移除刷新按钮，保留清除选择图标。
- 加载、空结果和错误在浮层内部显示，不永久占用节点槽位空间。

Character 和 Action 不再要求输入两个字符后才能展示结果。聚焦空输入即可显示前 6 个；输入内容后继续使用后端 query 缩小范围。

搜索请求必须具备请求代次保护：旧请求晚返回时不能覆盖较新的查询或用户已经选择的节点。

## 中间节点编辑器

### 工作区切换

中栏默认显示 Prompt Preview。点击任意主节点或 Compare 节点后，中栏切换为节点编辑器。

编辑器顶部显示：

- 节点文件夹名称
- role
- `主节点` 或 `Compare`
- `表单` / `JSON` 页签
- 应用、保存、恢复和关闭命令

关闭编辑器后，中栏恢复 Prompt Preview。

### 表单模式

表单模式直接编辑标准 NodeDocument，不创建单独的简化节点模型。

固定字段：

- `kind`
- `id`
- `name`
- `description`

Prompt 区域：

- Positive prompt
- Negative prompt

Tags 区域：

- 每行显示分组 key 和提示词字符串。
- 支持添加、删除和重命名分组。
- 提示词以字符串编辑，提交时归一化为 NodeDocument 的字符串数组。

扩展字段区域：

- `composition`
- `generation`
- `renderers`
- `relations`
- `clothing`
- `agent`
- 其他 NodeDocument 中存在的扩展字段

扩展字段使用可展开的键值表。对象显示为嵌套表格，数组显示为可增删行列表，标量使用对应 input、number input、checkbox 或 textarea。

表单编辑必须保留未显示或未知字段，不能在表单与 JSON 转换时丢失 NodeDocument 扩展内容。

### JSON 模式

JSON 页签保留原始完整 NodeDocument 编辑能力。

- 表单与 JSON 共用同一个 draft。
- 从 JSON 切回表单前执行 JSON 解析和 NodeDocument 校验。
- 校验失败时停留在 JSON 页签并显示具体错误。
- 表单修改立即更新 JSON 表示。

### 应用与保存

- `应用到本次运行`：更新当前 NodeVariantSlot 的 `draftNode`，不写磁盘。
- `保存到节点库`：调用 `/api/nodes/save`，成功后更新 `sourceRef`、`sourceNode` 和 `draftNode`。
- 空白节点保存时要求输入 design_root 内的目标 ref。
- 编辑器存在未应用修改时，关闭或切换节点需要确认。
- Apply 或 Save 成功后更新编辑基线。

## 普通生成

普通 Preview 和 Generate 只使用三个 role 的主节点：

```text
primary Artist + primary Character + primary Action
```

- 普通 Generate 继续使用当前 NT。
- 至少 Character 或 Action 主节点存在。
- Compare 节点不会影响普通 Prompt Preview 和普通 Generate。
- Negative 默认值从 `lowres` 改为空字符串。

## Compare Generate

### 组合规则

Compare Generate 使用每个 role 的全部已选择节点：

```text
artists = selected primary Artist + selected compare Artists
characters = selected primary Character + selected compare Characters
actions = selected primary Action + selected compare Actions
```

组合数量为：

```text
Artist 数量 × Character 数量 × Action 数量
```

某一 role 没有任何节点时，使用一个 `null` 占位，因此该 role 的乘数为 1。Character 和 Action 至少有一类存在。

每个组合固定：

```text
n_samples = 1
```

Compare Generate 忽略普通 NT，最终图片数量严格等于组合数量。

### 生成确认

按钮显示预计数量：

```text
Compare Generate · 12
```

点击后展示组合摘要并确认：

```text
Artist 2 × Character 3 × Action 2 = 12 张
```

确认后才开始提交任务。

### 运行控制

`CompareMatrixPlanner` 是纯函数，输入 RoleNodeGroup，输出普通组合任务：

```ts
type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};
```

`CompareRunController` 负责：

- 为每个组合调用 compose-preview。
- 使用返回的最新 RenderRequest 提交 Generate Job。
- 固定前端并发数为 2。
- 轮询每个 Job 到终态。
- 单个组合失败时继续执行其他组合。
- 汇总 queued、running、succeeded、failed 数量。

### 结果展示

结果按组合显示：

- Artist、Character、Action 文件夹名称
- 状态
- seed
- 图片
- 失败原因

每个组合结果保留对应 `combinationId` 和三个 slotId，避免同名节点或相同 ref 的临时变体无法区分。

## 状态持久化

### App 级状态

Custom 工作台状态由 `CustomWorkspaceProvider` 持有，并位于页面导航之上。切换 Custom、Batch、Results 时 CustomStudio 可以卸载，但工作台数据不会丢失。

App 内存状态包括：

- 所有主节点和 Compare 节点
- 当前编辑节点
- 尚未应用的编辑器草稿
- Negative、尺寸、seed、NT
- 最后一次 Prompt Preview
- Compare 运行状态和当前 Job 列表

### localStorage 快照

持久化 key：

```text
promptatelier.custom-workspace/v1
```

持久化内容：

- 主节点和 Compare 节点
- 临时编辑后的 NodeDocument
- 编辑器草稿和当前页签
- Negative、尺寸、seed、NT
- 最后一次成功 Preview

不持久化：

- 正在运行的 Job 轮询器
- Job 的异步 Promise
- 后端连接错误

状态变化后防抖写入 localStorage。页面初始化时执行 schema 和数据校验：

- 合法 v1 快照正常恢复。
- JSON 损坏、schema 不匹配或 NodeDocument 无法校验时回退为空工作台。
- 恢复失败时显示可关闭错误，不覆盖损坏数据，直到用户点击“重置工作台”。

提供“重置工作台”命令，清除 localStorage 和内存输入状态。重置前需要确认。

## 导航调整

侧栏保留：

```text
Custom
Batch
Results
```

删除 Compare 入口和 CompareStudio 组件引用。已有 CompareStudio 文件可以删除。

页面切换只修改当前导航 key，不销毁 `CustomWorkspaceProvider`。

## 错误处理

- 搜索失败：错误显示在当前搜索浮层，不影响已选择节点。
- 节点读取失败：保留原槽位状态。
- 表单或 JSON 校验失败：保留当前编辑草稿，不 Apply、不 Save。
- Compare 组合不完整：生成前指出 role 和 slot 名称。
- 单个 Compare 组合 Preview 失败：记录该组合失败，继续队列。
- Job 失败：保留组合和错误信息，其他组合继续。
- localStorage 写入失败：工作台继续使用内存状态，并显示 warning。
- 页面卸载：停止组件级计时器；App 级 CompareRunController 继续运行。

## 验收标准

1. NodePicker 聚焦后显示最多 6 个结果，选择或失焦后浮层消失。
2. 搜索浮层不改变 Nodes 栏高度，结果只显示文件夹名称。
3. 搜索旧响应不会覆盖新的查询或已选择节点。
4. 点击节点后，中栏显示结构化编辑器，不出现侧边抽屉。
5. 表单与 JSON 双向切换，不丢失 renderers、composition 等扩展字段。
6. 未 Apply 的编辑在切换节点或关闭编辑器前要求确认。
7. 切换 Custom、Batch、Results 后返回，工作台数据不变。
8. 刷新浏览器后主节点、Compare 节点、临时编辑和参数恢复。
9. 点击重置工作台后 localStorage 和输入状态清空。
10. Compare 导航和独立 CompareStudio 删除。
11. 每个 role 可以添加多个 Compare 节点并独立临时编辑。
12. 删除 Compare 节点不会修改节点库文件。
13. `2 × 3 × 2` 精确展开 12 个组合。
14. Compare Generate 每组合 `n_samples=1`，总图片数严格等于组合数。
15. 普通 Generate 只使用主节点并继续遵守 NT。
16. Compare 结果能追溯每张图使用的三个节点名称和 slotId。
17. Negative 初始为空字符串。
18. 使用真实 NovelAI 完成至少一个 `2 × 1 × 2 = 4` 的 Compare 出图验收。

## 非目标

- 不把 Compare 节点保存成新的后端领域类型。
- 不改变 ScriptComposer、AgentComposer 或 Renderer 的节点语义。
- 不让 Compare Generate 使用普通 NT。
- 不恢复浏览器刷新前仍在运行的 Job。
- 不提供跨浏览器或跨设备工作台同步。
- 不迁移旧 CompareStudio 的假数据结构。
