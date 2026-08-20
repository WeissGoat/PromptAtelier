# Custom 节点启用与排序设计

## 1. 背景

Custom 工作台目前把同一类型的节点拆成 `primary` 和 `compares` 两组。随着 Artist、Character、Action 的 Compare 节点增多，这种模型带来三个问题：

- 用户需要理解“原始节点”和“Compare 节点”的区别，但实际使用时它们都是同一类型的候选节点。
- `primary` 被普通 Generate 特殊使用，Compare Matrix 又使用 `primary + compares`，两条规则不一致。
- 节点没有独立的启用状态，用户只能删除节点来临时排除它；删除还会丢失编辑内容和排列位置。

本次只调整 refactor 的 Web Custom 工作台，不修改旧 `tags_machine`，也不改变 AgentComposer 链路。

## 2. 目标与非目标

### 2.1 目标

- Artist、Character、Action 每个类型都使用一个有序节点列表。
- 每个节点可以启用或关闭，关闭后保留节点内容。
- 同一类型的节点可以拖动排序。
- 普通 Generate 和 Compare Generate 使用同一套节点选择语义。
- 节点顺序持久化，并影响 Compare Matrix 的组合顺序。
- 旧工作台缓存可以自动迁移，不丢失已有节点和编辑状态。

### 2.2 非目标

- 不重构 Prompt Behavior 配置。它仍然拥有自己的 `primary/compares` 结构和 Compare 维度。
- 不改变节点文件格式、节点读取 API、PromptComposer、Renderer 或 NovelAI 请求协议。
- 不引入跨类型拖动。Artist、Character、Action 只能在各自列表内排序。
- 不把关闭节点从工作台删除或从本地缓存清除。

## 3. 核心模型

### 3.1 统一节点列表

`NodeVariantSlot` 不再包含 `mode`，增加 `enabled`：

```ts
type NodeVariantSlot = {
  slotId: string;
  role: NodeRole;
  enabled: boolean;
  sourceKind?: "fixed" | "random";
  randomSpec?: NodePoolSpec | null;
  sourceRef: string | null;
  sourceNode: NodeDocument | null;
  draftNode: NodeDocument | null;
  sourceEditor?: NodeEditorDocument | null;
  draftEditorValues?: Record<string, unknown> | null;
};

type RoleNodeGroup = {
  slots: NodeVariantSlot[];
};
```

新建工作区时每个类型初始化一个空白、启用的槽位，保持当前首次打开 Custom 页面即可选择节点的体验；用户删除后列表可以为空。

列表顺序同时表示：

1. Custom 页面中的显示顺序。
2. 普通 Generate 选择节点的优先级。
3. Compare Matrix 对应类型维度的展开顺序。

不再出现 `primary`、`compare`、`Primary`、`Compare` 等节点级概念。`slotId` 仍然是稳定标识，用于编辑器、临时节点、结果标识和缓存定位。

### 3.2 节点可用性

节点的 `enabled` 只表示用户是否允许它参与当前工作台运行；节点还必须满足现有的“已选择/已配置”条件才算可用：

- `sourceKind: "fixed"`：`draftNode` 存在。
- `sourceKind: "random"`：随机来源非空，且随机配置有效。

统一定义 `activeSlots(group)`：先按 `slots` 原顺序遍历，再筛选 `enabled === true` 且节点可用的槽位。所有普通生成和 Compare 计算都通过这个选择器，不直接读取列表下标。

关闭节点仍然可以编辑、恢复、删除和拖动。关闭节点不会进入 Prompt 预览、随机解析、Compare Matrix、任务数量统计或生图请求。

## 4. 运行语义

### 4.1 普通 Generate

普通 Generate 对每个节点类型取 `activeSlots(group)[0]`：

- Artist 没有可用节点时，沿用当前可省略 Artist 的行为。
- Character 和 Action 沿用当前校验，二者合计至少需要一个可用节点。
- 如果列表第一个节点关闭、为空或随机配置无效，则选择列表中下一个可用节点。
- 普通 Generate 不会因为后面还有多个启用节点而自动生成多张图。

这样普通 Generate 的选择规则与节点排列顺序一致，用户通过拖动即可控制默认节点。

### 4.2 Compare Generate

Compare Matrix 的每个节点维度使用 `activeSlots(group)`：

```text
artist   = activeSlots(artist)
character = activeSlots(character)
action    = activeSlots(action)
```

每个维度按列表顺序展开笛卡尔积。某个维度没有可用节点时，保留现有的空维度占位行为，不生成该类型节点提示词。节点启用状态只影响当前矩阵，不影响其他类型。

因此，启用节点数量为 `a × c × k` 时，基础 Compare 组合数为 `a * c * k`，再乘以 Prompt Behavior 变体数和 Compare Matrix 的 `nt` 分组数。关闭节点不会计数，也不会占用任务。

每组的 seed、输出目录、结果归档和现有 Compare 流程保持不变；本次只替换节点维度的来源。

## 5. 工作台交互

### 5.1 节点组

每个 Artist、Character、Action 区域显示一个“节点列表”：

- 顶部显示类型名称、启用数量和总数量。
- 加号按钮改为“新增节点”，不再显示或使用 Compare 文案。
- 节点卡片只显示节点文件名或临时节点名称，不显示 Primary/Compare 徽标。
- 每个节点提供启用开关。关闭后卡片降低视觉强调，并显示“已关闭”状态。
- 每个节点提供拖动手柄，只能在当前类型列表内拖动。
- 保留现有编辑、临时编辑、恢复、清空和删除操作。

新增节点延续当前镜像体验：优先复制该类型列表中的第一个节点；列表为空时创建空白节点。复制后的节点默认启用，并追加到列表末尾。

### 5.2 排序交互

使用同一类型列表内的拖放排序：

- 拖动开始时记录 `slotId`，不依赖数组下标。
- 放置到目标节点前或目标节点后时重排数组。
- 拖动完成立即更新工作台状态并持久化。
- 拖动关闭节点也允许，关闭状态不影响排序。
- 为保证可访问性，同时提供上移、下移操作；首节点不能上移，末节点不能下移。
- 拖动过程中只改变顺序，不改变 `enabled`、节点内容或临时编辑状态。

### 5.3 生成区提示

Compare 区域数量文案改为按启用且有效节点统计，例如：

```text
Artist 2 × Character 3 × Action 4 × Behavior 1 × Groups 2 = 48
```

Character 和 Action 都没有启用且有效节点时，生成按钮仍可点击，但执行前给出明确错误；Artist 没有可用节点仍可省略。不再让用户通过后端 500 才发现问题。

## 6. 状态迁移与持久化

### 6.1 新 schema

Custom 工作台 schema 升级到下一个版本，例如：

```text
promptatelier.custom-workspace/v3
```

新的 `groups` 形态为：

```json
{
  "artist": { "slots": [] },
  "character": { "slots": [] },
  "action": { "slots": [] }
}
```

保存时只写入新结构，不再写入 `primary`、`compares` 或节点 `mode`。

### 6.2 旧快照迁移

读取旧 v1/v2 工作台快照时：

1. 按 `primary` 后接 `compares` 的原有顺序生成 `slots`。
2. 删除每个节点的 `mode` 字段。
3. 所有已有节点补 `enabled: true`，保证迁移后 Compare 结果不会无故减少。
4. 保留 `slotId`、源节点、临时节点、编辑值、随机配置和预览状态。
5. 如果编辑器当前指向某个旧槽位，继续通过 `slotId` 恢复编辑状态。
6. 加载成功后以 v3 结构保存，后续不重复迁移。

Prompt Behavior 的旧迁移逻辑独立保留，不把它混入节点迁移。

## 7. 模块职责与改动边界

### 7.1 `workspace/types.ts`

- 删除节点槽位 `SlotMode` 和 `mode` 字段。
- 为槽位增加 `enabled`。
- 将 `RoleNodeGroup` 改为 `slots` 列表。

### 7.2 `workspace/storage.ts`

- 创建空工作区时初始化空 `slots`。
- 新增 v2 到 v3 的快照迁移和校验。
- 统一补齐旧槽位的 `enabled` 默认值。

### 7.3 `workspace/CustomWorkspaceProvider.tsx`

提供面向统一列表的操作：

- `addNode(role)`
- `removeNode(slotId)`
- `toggleNode(slotId, enabled)`
- `reorderNodes(role, activeSlotId, overSlotId)`

现有选择、编辑、临时节点和随机节点操作改为遍历 `group.slots`。Prompt Behavior 的 `addCompare/removeCompare` 保持原样。

### 7.4 `compare/matrix.ts`

- `selectedSlots` 改为 `activeSlots`。
- 只处理启用且有效节点。
- 保持当前矩阵维度、组合 ID、Prompt Behavior 和随机节点逻辑。

### 7.5 `CustomGeneratePanel.tsx` 与 Compare 控制器

- 普通 Generate 使用每个类型的第一个 active slot。
- Compare 控制器接收统一的 groups，不读取 `primary` 或 `compares`。
- 预览、校验、数量统计与 Compare Matrix 共享同一选择器。

### 7.6 `NodeRoleGroup.tsx`、`NodeSlot.tsx`、编辑器

- 改为列表渲染和列表级排序。
- 移除节点级 Primary/Compare 文案。
- 增加启用开关、关闭状态和拖动/上移/下移控件。
- 编辑器标题改为“编辑 Artist/Character/Action 节点”，不显示节点模式。

Prompt Behavior 组件不在本次节点 UI 改造范围内。

## 8. 验收标准

### 8.1 状态与迁移

- 已有 v1/v2 工作台刷新后，所有原节点仍存在，顺序为原 `primary` 后接原 `compares`。
- 已有节点默认全部启用，迁移前后的 Compare 数量一致。
- 关闭一个节点后刷新页面，关闭状态、节点内容和位置都保留。
- 临时节点和临时编辑值在拖动、关闭、刷新后不丢失。

### 8.2 普通生成

- 列表中第一个节点关闭时，普通 Generate 使用下一个启用且有效节点。
- 排序后，普通 Generate 使用新的第一个启用且有效节点。
- 后续启用节点不会被普通 Generate 自动展开成多张图。
- Character 和 Action 合计没有可用节点时，前端明确阻止生成并显示类型错误；只有其中一个类型为空时仍允许使用另一个类型。

### 8.3 Compare

- 启用 `a/c/k` 个节点时，矩阵节点维度为 `a × c × k`。
- 关闭节点不产生任务、不计入数量、不出现在请求组合中。
- 拖动同类型节点后，生成组合顺序与页面顺序一致。
- Compare 的组 seed、`nt` 分组、输出目录和结果详情保持现有行为。
- 普通 Generate 与 Compare Generate 仍使用同一份节点内容和编辑结果。

### 8.4 业务验证

至少用当前 Web Custom 工作台完成以下验证：

1. 单 Artist、单 Character、单 Action 生成一张真实 NovelAI 图片。
2. 添加同类型节点，关闭其中一个，确认 Compare 任务数量和实际图片数量减少。
3. 重新启用并拖动节点，确认 Compare 结果卡片顺序随节点顺序变化。
4. 刷新页面后重复预览，确认启用状态、顺序和临时节点保持。
5. 验证 Prompt Behavior Compare 仍能独立工作，且不受节点列表迁移影响。

## 9. 风险与处理

- **旧缓存格式不兼容**：先迁移再校验；无法识别的快照显示现有工作台恢复提示，不覆盖旧数据。
- **所有节点被关闭**：数量显示为零，并在生成前给出类型级错误；不向后端提交空任务。
- **随机节点关闭后误解析**：统一从 `activeSlots` 进入随机解析，关闭节点不会调用随机扫描或抽取。
- **排序导致组合 ID 变化**：组合 ID 继续由 `slotId` 组成，排序只改变任务顺序，不改变节点身份。
- **编辑器引用失效**：所有编辑器定位继续使用 `slotId`，重排不改变槽位对象身份。
