# Web Prompt Behavior 完整方案 Compare 设计

## 1. 文档信息

- 日期：2026-07-24
- 状态：设计已确认，等待实现计划
- 适用项目：PromptAtelier `refactor`
- 相关设计：[Web 提示词行为配置设计](2026-07-24-web-prompt-behavior-controls-design.md)

## 2. 背景

当前 Custom 页面已经可以编辑一份 Prompt Behavior 配置，包含：

- `identity_minimal_sections`
- NovelAI Character Prompts
- PromptPolicy 单条规则覆盖

Artist、Character、Action 已经支持节点级 Compare。Prompt Behavior 目前是 Workspace 级的单值，因此一次 Compare 中所有节点组合都使用相同的行为配置，无法直接比较例如：

- Character Prompts `Auto` 与 `Off`
- 不同的 Identity Minimal Sections
- 某条 Policy 开启与关闭
- 两套完整的规则组合

本设计将一整套 Prompt Behavior 作为一个 Compare 维度。每个维度项是完整配置快照，而不是把每条规则拆成独立的笛卡尔积维度。

## 3. 目标

### 3.1 必须实现

1. Custom 页面可以保存一个 Primary Prompt Behavior 方案。
2. 用户可以通过 `+` 镜像 Primary，创建多个 Compare Behavior 方案。
3. 每个方案可以独立编辑 Identity、Character Prompts 和 Policy Rules。
4. Compare Generate 可以把 Behavior 方案加入节点矩阵。
5. 同一 NT 组内所有组合使用相同 seed，保证比较公平。
6. 普通 Preview 和 Generate 继续只使用 Primary 方案。
7. 刷新页面后方案和已有 Workspace 数据能够恢复。
8. AgentComposer 链路不被改写或绕过。
9. 至少完成一组 NovelAI 真实出图业务验证。

### 3.2 非目标

本次不实现：

- 将每一条 Policy Rule 独立建成矩阵轴。
- Policy 模板切换。
- 浏览器内创建或删除 Policy Rule。
- AgentComposer 专用的 Behavior Compare 语义。
- 手动编辑 Character Prompts 的底层 `char_captions`。
- Batch Studio 的 Prompt Behavior Compare UI。

## 4. 术语

### 4.1 PromptBehaviorParams

一份完整的、可以实际发送给后端的提示词行为配置：

```ts
type PromptBehaviorParams = {
  identityMinimal: {
    mode: "inherit" | "override";
    sections: string[];
  };
  characterPrompts: {
    mode: "auto" | "off";
    addMaleCaption: boolean;
  };
  policyRules: Record<string, {
    state: "inherit" | "enabled" | "disabled";
    options?: Record<string, unknown>;
  }>;
};
```

### 4.2 PromptBehaviorVariant

矩阵中的一个行为方案。它包含完整配置，不引用另一个方案的实时状态。

```ts
type PromptBehaviorVariant = {
  slotId: string;
  label: string;
  mode: "primary" | "compare";
  value: PromptBehaviorParams;
};
```

### 4.3 PromptBehaviorGroup

Workspace 中的行为方案集合：

```ts
type PromptBehaviorGroup = {
  primary: PromptBehaviorVariant;
  compares: PromptBehaviorVariant[];
};
```

`primary` 始终存在，`compares` 可以为空。只有 `compares` 中的方案参与 Behavior Compare 维度。

## 5. Workspace 状态

### 5.1 新状态

`CustomWorkspaceState` 将当前单值：

```ts
promptBehavior: PromptBehaviorParams;
```

扩展为：

```ts
promptBehaviorGroup: PromptBehaviorGroup;
activePromptBehaviorSlotId: string;
```

`activePromptBehaviorSlotId` 仅用于编辑和预览选择，不改变 Primary/Compare 的身份。

### 5.2 镜像规则

点击 `+ Compare` 时：

1. 深拷贝 `primary.value`。
2. 生成新的 `slotId`。
3. 默认名称为 `Compare 1`、`Compare 2` 等可读名称。
4. `mode` 设置为 `compare`。
5. 后续修改 Compare 方案不影响 Primary。

不支持 Compare 方案继续派生子方案，避免形成嵌套引用关系。

### 5.3 旧数据迁移

已有 Workspace 只保存单一 `promptBehavior` 时，加载阶段转换为：

```text
旧 promptBehavior
  -> promptBehaviorGroup.primary.value
  -> promptBehaviorGroup.primary.mode = primary
  -> compares = []
```

迁移不清除节点、临时节点、参数、预览结果或编辑器草稿。保存时使用新的 Workspace schema 版本。

## 6. 前端交互

### 6.1 Prompt Behavior 区域

Prompt Behavior 面板从单一表单变为方案列表：

```text
Prompt Behavior
  [Default]       Primary
  [No Captions]   Compare   [删除]
  [Minimal ID]    Compare   [删除]
  [+ Compare]
```

每个方案显示：

- 名称
- Primary 或 Compare 标记
- 当前选中状态
- Identity Minimal Sections 表单
- Character Prompts 表单
- Policy Rules 表单

方案名称允许在面板内编辑，用于结果卡片和日志识别；名称不参与业务请求语义。

### 6.2 预览与普通生成

- 选中某个方案后，Preview 可以查看该方案对应的最终 Prompt 和 Render 参数。
- 普通 Generate 始终使用 Primary，按钮和状态区域明确显示 `Primary`。
- Compare 方案只通过 Compare Generate 执行，避免用户误把实验配置当成普通生成配置。
- Preview、普通 Generate 和 Compare Generate 继续共用同一个 Request Builder。

### 6.3 Compare Generate

当存在至少一个 Compare Behavior 方案，Compare Generate 按钮启用。矩阵摘要显示：

```text
Artist 2 × Character 3 × Action 4 × Behavior 2 × Groups 3 = 144
```

Compare 结果卡片额外显示：

```text
Behavior: No Captions
```

删除最后一个 Compare Behavior 后，Behavior 维度回到 1，不影响普通 Generate。

## 7. Compare Matrix

### 7.1 组合模型

当前组合：

```ts
type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
};
```

扩展为：

```ts
type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
  promptBehavior: PromptBehaviorVariant;
};
```

Behavior 维度至少包含 Primary，因此没有 Compare Behavior 时矩阵行为与现有版本一致。

### 7.2 数量

设：

- `A`：Artist 方案数
- `C`：Character 方案数
- `K`：Action 方案数
- `B`：Prompt Behavior 方案数
- `N`：NT 组数

则总任务数为：

```text
A × C × K × B × N
```

`B` 只代表完整 Behavior 方案数量，不代表 Policy Rule 数量。

### 7.3 Seed

沿用当前 `buildCompareRunPlan` 规则：

- 每个 NT 组产生一个唯一 `groupSeed`。
- 组内所有 Artist、Character、Action、Behavior 组合使用同一个 `groupSeed`。
- 不同组使用不同 seed。
- 每个请求的 `n_samples = 1`。

这样可以在同一随机条件下比较 Prompt Behavior 的影响。

### 7.4 组合标识

`combinationId` 必须包含 Behavior slot id：

```text
artist-slot::character-slot::action-slot::behavior-slot
```

Behavior 的 label 不用于唯一性，避免用户改名导致任务 ID 改变。

## 8. 请求链路

```text
PromptBehaviorVariant.value
        |
        v
Compare Matrix
        |
        v
buildComposeRenderRequest(combination, params, behavior)
        |
        v
POST /api/compose-preview
        |
        v
GenerationJsonApi.compose_render_plan
        |
        +--> ScriptComposer / PromptPolicyPipeline
        |
        +--> NovelAI Renderer
        |
        v
POST /api/generate
```

每个组合的请求必须使用自己的 `promptBehavior.value`：

- Identity 覆盖进入 `compose.identity_minimal_sections`。
- Policy 覆盖进入 `compose.prompt_policy.rules`。
- Character Prompts 进入 `render.params.character_prompts`。
- `inherit` 规则不写入请求，由项目配置提供基线。

后端 API 不新增新的 Behavior 专用端点，也不需要了解 Compare 维度；它只处理每次请求收到的完整配置。

## 9. 缓存与 AgentComposer 边界

### 9.1 缓存区分

不同 Behavior 方案必须产生不同的有效请求语义：

```text
相同节点 + Character Prompts Auto
!=
相同节点 + Character Prompts Off
```

实现要求：

1. Request Builder 对每个组合序列化对应方案。
2. Identity 和 Policy 继续由现有 Composer/Policy 缓存签名参与区分。
3. Character Prompts 继续由 NovelAI Render 参数区分。
4. Compare 结果保存 `behavior_slot_id`、`behavior_label` 和规范化 fingerprint，便于日志和结果回溯。

不新增一套独立的 Agent cache key 规则。

### 9.2 AgentComposer

本功能不修改 AgentComposer 的输入、缓存或结果结构。

如果某个组合触发现有 `requires_agent` 流程，按当前 Web 行为处理，不因为加入 Behavior 维度而自动绕过 Agent，也不把 Behavior 伪装成 Agent 输入。

## 10. 错误处理

- Identity override 为空：在表单层阻止，并在 Request Builder 层再次校验。
- Behavior 方案缺少有效配置：阻止加入矩阵并显示具体方案名称。
- 单个组合 Preview 或 Generate 失败：只标记该组合为 failed，继续执行其他组合。
- Behavior 方案删除后仍有旧结果：旧结果保留，显示其历史 label 和 slot id。
- Compare 数量过大：沿用当前矩阵数量提示，在生成前显示完整任务数量。

## 11. 代码职责边界

预计涉及的前端职责：

| 模块 | 职责 |
| --- | --- |
| `workspace/types.ts` | 定义 Variant、Group 和 Workspace 状态 |
| `workspace/storage.ts` | 保存、读取和旧状态迁移 |
| `CustomWorkspaceProvider` | 增删、镜像、选择和更新 Behavior 方案 |
| `PromptBehaviorPanel` | 方案列表和完整表单编辑 |
| `compare/matrix.ts` | 将 Behavior 作为矩阵维度 |
| `compare/runPlan.ts` | 沿用 NT 分组和 seed 规划 |
| `useCompareRunController.ts` | 为每个组合传入对应 Behavior |
| `requestBuilder.ts` | 序列化当前组合的 Behavior |
| `CustomGeneratePanel.tsx` | 显示数量、状态和 Behavior 结果标签 |

后端原则上只需要复用现有 API；如业务测试暴露出结果元数据缺少 Behavior 标识，再在现有结果 metadata 扩展，不改变 PromptBundle 主结构。

## 12. 验收标准

### 12.1 前端状态

- 从旧 Workspace 加载后，Primary 配置与原来的 `promptBehavior` 完全一致。
- 添加 Compare 后，完整配置深拷贝，修改一方不影响另一方。
- 刷新页面后 Primary、Compare、名称和表单值全部恢复。
- 删除 Compare 不影响 Primary。

### 12.2 矩阵与请求

- `A × C × K × B × N` 数量准确。
- 同一组所有请求的 seed 相同。
- 不同 Behavior 方案的请求只在预期 Behavior 字段上产生差异。
- 普通 Generate 始终发送 Primary。
- Compare Generate 不会把所有任务错误地发送成 Primary。
- 每个 Compare 请求 `n_samples=1`。

### 12.3 业务验证

至少使用一组真实 NovelAI 配置完成：

1. 固定 Artist、Character、Action。
2. 创建两个 Behavior 方案，例如 Character Prompts `Auto` 和 `Off`。
3. 使用 `NT=1` 生成两个 Compare 任务。
4. 检查两个请求的 seed 相同。
5. 检查生成参数中 Character Prompts 状态不同。
6. 检查图片和 PNG 参数均能读取。
7. 在 Web 结果卡片中能明确区分两个 Behavior 方案。

### 12.4 回归

- AgentComposer 现有 Web 链路保持通过。
- 现有 Artist/Character/Action Compare 测试保持通过。
- 普通 Preview、Generate 行为保持通过。
- 前端 TypeScript 编译和构建通过。

## 13. 实施顺序

1. 扩展 Workspace 类型和旧数据迁移。
2. 在 Provider 中实现 Behavior 方案的镜像、选择、更新和删除。
3. 重构 PromptBehaviorPanel 为方案列表。
4. 扩展 Compare Matrix 和请求构建。
5. 更新 Compare 数量、结果标签和状态展示。
6. 补充前端/后端链路测试。
7. 完成一组 NovelAI 真实出图验收。

