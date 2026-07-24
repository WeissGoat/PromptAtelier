# Web Prompt Behavior Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Custom Web 把一整套 Prompt Behavior 配置作为 Compare Matrix 的独立维度，同时保持普通 Generate、AgentComposer 和现有节点 Compare 行为稳定。

**Architecture:** Workspace 将单一 `promptBehavior` 升级为 Primary + Compare Variants，并通过稳定的旧数据迁移恢复现有浏览器状态。前端 Compare Matrix 负责展开 Behavior 维度，每个任务把对应完整配置传给现有 `/compose-preview`，后端 API 和 AgentComposer 不增加新契约。

**Tech Stack:** React 18、TypeScript 5.6、Vitest、Testing Library、Vite、FastAPI/NovelAI 现有 Web API。

## Global Constraints

- 直接在当前 `main` 开发，不创建新分支或 worktree。
- 不使用子 agent，使用 `superpowers:executing-plans` 在当前会话执行。
- Prompt Behavior 以完整配置方案为 Compare 维度，不把单条 Policy Rule 拆成独立维度。
- 普通 Preview 可以查看当前选中方案，普通 Generate 始终使用 Primary。
- 同一 NT 组内所有组合共享 seed，不同组使用不同 seed，每个组合 `n_samples=1`。
- 不修改 AgentComposer 输入、缓存或结果结构。
- 不新增后端 Behavior 专用 API。
- 验收以 Web 业务链路和 NovelAI 真实出图为最高优先级，单元测试只覆盖关键状态和请求契约。
- 每次提交只暂存本任务文件，不包含工作区现有无关改动。

---

### Task 1: Prompt Behavior 类型、辅助函数和 Workspace 迁移

**Files:**
- Create: `web/src/workspace/promptBehavior.ts`
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/storage.ts`
- Modify: `web/src/workspace/storage.test.ts`
- Test: `web/src/workspace/storage.test.ts`

**Interfaces:**
- Produces: `PromptBehaviorVariant`、`PromptBehaviorGroup`、`createDefaultPromptBehavior()`、`createDefaultPromptBehaviorGroup()`、`promptBehaviorVariants()`、`findPromptBehaviorVariant()`、`promptBehaviorFingerprint()`。
- Produces: `CustomWorkspaceState.promptBehaviorGroup` 和 `activePromptBehaviorSlotId`。
- Consumes: 现有 `PromptBehaviorParams`。Compare slot id 由 Provider 调用现有 `createSlotId()` 生成，避免 `promptBehavior.ts` 与 `storage.ts` 形成循环依赖。

- [ ] **Step 1: 增加状态迁移失败测试**

在 `storage.test.ts` 增加以下场景：

```ts
it("migrates v1 prompt behavior into the primary behavior variant", () => {
  const legacy = createEmptyWorkspace();
  const snapshot = JSON.parse(JSON.stringify(legacy)) as Record<string, unknown>;
  snapshot.schema = "promptatelier.custom-workspace/v1";
  snapshot.promptBehavior = {
    identityMinimal: { mode: "override", sections: ["character"] },
    characterPrompts: { mode: "off", addMaleCaption: false },
    policyRules: { visibility_policy: { state: "disabled" } },
  };
  delete snapshot.promptBehaviorGroup;
  delete snapshot.activePromptBehaviorSlotId;
  localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));

  const loaded = loadWorkspaceSnapshot(localStorage);

  expect(loaded.status).toBe("loaded");
  expect(loaded.state.promptBehaviorGroup.primary.value.characterPrompts.mode).toBe("off");
  expect(loaded.state.promptBehaviorGroup.compares).toEqual([]);
  expect(loaded.state.activePromptBehaviorSlotId).toBe("primary-prompt-behavior");
});
```

再增加完整 Variant round-trip 测试，验证 label、slotId、Compare value 和 active slot 均可恢复。

- [ ] **Step 2: 运行 Workspace 测试确认失败**

Run:

```powershell
cd web
npm test -- --run src/workspace/storage.test.ts
```

Expected: FAIL，错误集中在 `promptBehaviorGroup` 和 `activePromptBehaviorSlotId` 不存在。

- [ ] **Step 3: 定义 Prompt Behavior 方案类型**

在 `types.ts` 增加：

```ts
export type PromptBehaviorVariant = {
  slotId: string;
  label: string;
  mode: SlotMode;
  value: PromptBehaviorParams;
};

export type PromptBehaviorGroup = {
  primary: PromptBehaviorVariant;
  compares: PromptBehaviorVariant[];
};
```

将 Workspace schema 改为 `promptatelier.custom-workspace/v2`，并把：

```ts
promptBehavior: PromptBehaviorParams;
```

替换为：

```ts
promptBehaviorGroup: PromptBehaviorGroup;
activePromptBehaviorSlotId: string;
```

- [ ] **Step 4: 创建 Prompt Behavior 辅助模块**

`promptBehavior.ts` 提供：

```ts
export const PRIMARY_PROMPT_BEHAVIOR_SLOT_ID = "primary-prompt-behavior";

export function createDefaultPromptBehavior(): PromptBehaviorParams;
export function createDefaultPromptBehaviorGroup(): PromptBehaviorGroup;
export function promptBehaviorVariants(group: PromptBehaviorGroup): PromptBehaviorVariant[];
export function findPromptBehaviorVariant(
  group: PromptBehaviorGroup,
  slotId: string,
): PromptBehaviorVariant | null;
export function promptBehaviorFingerprint(value: PromptBehaviorParams): string;
```

`promptBehaviorFingerprint()` 递归排序对象 key 后计算稳定的非安全短 hash，仅用于结果识别，不作为安全签名。

- [ ] **Step 5: 实现 v1 到 v2 迁移**

保持 localStorage key `promptatelier.custom-workspace/v1` 不变，避免丢失现有浏览器数据；新增独立 schema 常量：

```ts
export const CUSTOM_WORKSPACE_STORAGE_KEY = "promptatelier.custom-workspace/v1";
export const CUSTOM_WORKSPACE_SCHEMA = "promptatelier.custom-workspace/v2";
```

加载时接受：

```text
v1 snapshot -> normalize promptBehavior -> primary variant -> v2 state
v2 snapshot -> normalize complete behavior group
```

保存时只写 v2 schema、`promptBehaviorGroup` 和 `activePromptBehaviorSlotId`。

- [ ] **Step 6: 运行迁移测试**

Run:

```powershell
cd web
npm test -- --run src/workspace/storage.test.ts
```

Expected: PASS。

- [ ] **Step 7: 提交 Task 1**

```powershell
git add web/src/workspace/types.ts web/src/workspace/promptBehavior.ts web/src/workspace/storage.ts web/src/workspace/storage.test.ts
git commit -m "feat: model prompt behavior variants"
```

---

### Task 2: Workspace Provider 管理完整 Behavior 方案

**Files:**
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Modify: `web/src/workspace/CustomWorkspaceProvider.test.tsx`
- Test: `web/src/workspace/CustomWorkspaceProvider.test.tsx`

**Interfaces:**
- Consumes: Task 1 的 `PromptBehaviorGroup` 和辅助函数。
- Produces: `addPromptBehaviorCompare()`、`removePromptBehaviorCompare()`、`selectPromptBehavior()`、`renamePromptBehavior()`、`setPromptBehavior()`。

- [ ] **Step 1: 增加 Provider 行为测试**

扩展测试 Probe，暴露：

```tsx
<span data-testid="behavior-count">
  {workspace.state.promptBehaviorGroup.compares.length}
</span>
<span data-testid="active-behavior">
  {workspace.state.activePromptBehaviorSlotId}
</span>
<button onClick={() => workspace.addPromptBehaviorCompare()}>add behavior</button>
<button onClick={() => workspace.setPromptBehavior({
  ...workspace.state.promptBehaviorGroup.compares[0].value,
  characterPrompts: { mode: "off", addMaleCaption: false },
})}>edit behavior</button>
```

测试必须证明：

- `+` 镜像 Primary 的完整值。
- 新方案自动成为 active。
- 修改 Compare 不影响 Primary。
- 删除 active Compare 后回到 Primary。
- label 修改和刷新恢复正常。

- [ ] **Step 2: 运行 Provider 测试确认失败**

Run:

```powershell
cd web
npm test -- --run src/workspace/CustomWorkspaceProvider.test.tsx
```

Expected: FAIL，缺少 Behavior 方案操作方法。

- [ ] **Step 3: 实现 Provider 操作接口**

Context 增加：

```ts
findPromptBehavior(slotId: string): PromptBehaviorVariant | null;
selectPromptBehavior(slotId: string): void;
addPromptBehaviorCompare(): string;
removePromptBehaviorCompare(slotId: string): void;
renamePromptBehavior(slotId: string, label: string): void;
setPromptBehavior(value: PromptBehaviorParams): void;
```

`setPromptBehavior()` 只更新 active variant。`addPromptBehaviorCompare()` 始终深拷贝 Primary，不从当前 Compare 派生，并使用 `Compare N` 作为默认名称。

- [ ] **Step 4: 运行 Provider 测试**

Run:

```powershell
cd web
npm test -- --run src/workspace/CustomWorkspaceProvider.test.tsx
```

Expected: PASS。

- [ ] **Step 5: 提交 Task 2**

```powershell
git add web/src/workspace/CustomWorkspaceProvider.tsx web/src/workspace/CustomWorkspaceProvider.test.tsx
git commit -m "feat: manage prompt behavior compare variants"
```

---

### Task 3: Prompt Behavior 方案组 UI

**Files:**
- Create: `web/src/components/PromptBehaviorGroupPanel.tsx`
- Create: `web/src/components/PromptBehaviorGroupPanel.test.tsx`
- Modify: `web/src/components/PromptBehaviorPanel.tsx`
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/components/PromptBehaviorGroupPanel.test.tsx`
- Test: `web/src/components/PromptBehaviorPanel.test.tsx`

**Interfaces:**
- Consumes: Task 2 Provider 接口。
- Produces: Primary/Compare 方案选择、镜像、改名、删除和单方案完整编辑界面。

- [ ] **Step 1: 增加 Group Panel 交互测试**

测试使用真实 `CustomWorkspaceProvider` 渲染组件，并验证：

```text
Default 标记为 Primary
点击 Add Prompt Behavior Compare 后出现 Compare 1
Compare 1 自动选中
Compare 1 可以改名
修改 Character Prompts Off 不影响 Default
Compare 方案可以删除
```

稳定 accessible names：

```text
Add Prompt Behavior Compare
Select Prompt Behavior Default
Prompt Behavior label
Remove Prompt Behavior Compare 1
```

- [ ] **Step 2: 运行组件测试确认失败**

Run:

```powershell
cd web
npm test -- --run src/components/PromptBehaviorGroupPanel.test.tsx
```

Expected: FAIL，组件尚不存在。

- [ ] **Step 3: 实现 Group Panel**

组件结构：

```tsx
<section className="prompt-behavior-group-panel">
  <header>
    <h3>Prompt Behavior</h3>
    <button aria-label="Add Prompt Behavior Compare"><Plus /></button>
  </header>
  <div className="prompt-behavior-variant-list">...</div>
  <label>
    <span>方案名称</span>
    <input aria-label="Prompt Behavior label" />
  </label>
  <PromptBehaviorPanel value={active.value} ... />
</section>
```

Primary 不显示删除按钮。删除 Compare 前使用确认框，删除后 Provider 自动选择 Primary。

- [ ] **Step 4: 让 PromptBehaviorPanel 只负责单份表单**

移除其重复的顶层 `Prompt Behavior` 标题，保留 Identity、Character Prompts 和 Policy Rules 三块表单。现有字段 accessible names 保持不变，避免破坏测试和用户操作习惯。

- [ ] **Step 5: 接入 CustomStudio 并补样式**

`CustomStudio` 用 `PromptBehaviorGroupPanel` 替换单值 Panel。样式要求：

- 方案选择横向排列，空间不足时换行。
- Primary/Compare 标记清晰但不使用大面积卡片。
- 选中方案有稳定边框和背景，不改变布局尺寸。
- 删除使用 `X` 图标，新增使用 `Plus` 图标。
- 名称和按钮在窄屏不重叠。

- [ ] **Step 6: 运行组件测试**

Run:

```powershell
cd web
npm test -- --run src/components/PromptBehaviorPanel.test.tsx src/components/PromptBehaviorGroupPanel.test.tsx
```

Expected: PASS。

- [ ] **Step 7: 提交 Task 3**

```powershell
git add web/src/components/PromptBehaviorPanel.tsx web/src/components/PromptBehaviorGroupPanel.tsx web/src/components/PromptBehaviorGroupPanel.test.tsx web/src/pages/CustomStudio.tsx web/src/styles.css
git commit -m "feat: add prompt behavior compare editor"
```

---

### Task 4: 扩展 Compare Matrix 和 Controller

**Files:**
- Modify: `web/src/compare/matrix.ts`
- Modify: `web/src/compare/matrix.test.ts`
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/compare/useCompareRunController.test.tsx`
- Test: `web/src/compare/matrix.test.ts`
- Test: `web/src/compare/useCompareRunController.test.tsx`

**Interfaces:**
- Consumes: `PromptBehaviorGroup`、`PromptBehaviorVariant` 和 `promptBehaviorFingerprint()`。
- Produces: `CompareCombination.promptBehavior` 和含 Behavior 标识的 Compare result。

- [ ] **Step 1: 增加矩阵失败测试**

构造 `Artist=2`、`Character=1`、`Action=2`、`Behavior=3`：

```ts
expect(compareCount(groups, behaviorGroup)).toBe(12);
expect(buildCompareMatrix(groups, behaviorGroup)).toHaveLength(12);
expect(new Set(matrix.map((item) => item.promptBehavior.slotId))).toEqual(
  new Set(["primary-prompt-behavior", "behavior-1", "behavior-2"]),
);
```

验证 `combinationId` 最后一段是 Behavior slot id。

- [ ] **Step 2: 增加 Controller 请求差异测试**

用相同节点和两个 Behavior 方案启动一次 Compare，断言：

```text
两个 /compose-preview 请求 seed 相同
Primary 请求包含 character_prompts.mode=auto
Compare 请求不包含 character_prompts
Compare 请求包含被禁用的 visibility_policy
结果中 behavior label/fingerprint 不同
```

- [ ] **Step 3: 运行 Compare 测试确认失败**

Run:

```powershell
cd web
npm test -- --run src/compare/matrix.test.ts src/compare/useCompareRunController.test.tsx
```

Expected: FAIL，Matrix 和 Controller 仍只接收单一 Behavior。

- [ ] **Step 4: 扩展 Matrix**

定义：

```ts
export type CompareDimensions = Record<NodeRole, number> & { behavior: number };

export type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
  promptBehavior: PromptBehaviorVariant;
};
```

更新：

```ts
buildCompareMatrix(groups, promptBehaviorGroup)
compareDimensions(groups, promptBehaviorGroup)
compareCount(groups, promptBehaviorGroup)
```

- [ ] **Step 5: 扩展 Controller**

`start()` 改为：

```ts
start(
  groups: Record<NodeRole, RoleNodeGroup>,
  params: RenderWorkspaceParams,
  promptBehaviorGroup: PromptBehaviorGroup,
)
```

每个任务使用：

```ts
buildComposeRenderRequest(item.combination, runParams, {
  compare: true,
  promptBehavior: item.combination.promptBehavior.value,
});
```

`CompareCombinationResult` 增加：

```ts
behavior: {
  slotId: string;
  label: string;
  fingerprint: string;
};
```

- [ ] **Step 6: 更新现有 runId 和数量断言并运行测试**

Run:

```powershell
cd web
npm test -- --run src/compare/matrix.test.ts src/compare/runPlan.test.ts src/compare/useCompareRunController.test.tsx
```

Expected: PASS，所有 runId 包含 Behavior slot id，原节点矩阵行为保持不变。

- [ ] **Step 7: 提交 Task 4**

```powershell
git add web/src/compare/matrix.ts web/src/compare/matrix.test.ts web/src/compare/useCompareRunController.ts web/src/compare/useCompareRunController.test.tsx
git commit -m "feat: compare complete prompt behavior profiles"
```

---

### Task 5: 普通 Preview/Generate 与 Compare Generate 集成

**Files:**
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/pages/CustomStudio.test.tsx`
- Test: `web/src/pages/CustomStudio.test.tsx`

**Interfaces:**
- Consumes: Task 2 的 active/primary Behavior 状态和 Task 4 的矩阵 Controller。
- Produces: active Behavior Preview、Primary 普通 Generate、Behavior 结果标签和正确矩阵数量。

- [ ] **Step 1: 增加集成失败测试**

扩展 `CustomStudio` Harness，创建一个 Character Prompts Off 的 Compare Behavior。测试：

```text
矩阵从 Artist 2 × Character 1 × Action 2 × Groups 2 = 8
变为 Artist 2 × Character 1 × Action 2 × Behavior 2 × Groups 2 = 16
```

再验证：

- 选中 Compare Behavior 后点击 Preview，Preview 请求使用 Off。
- 点击普通 Generate，Generate 前的 compose 请求仍使用 Primary Auto。
- Compare Generate 产生 16 个请求，并且每组 8 个请求共享 seed。
- 结果卡片显示两个 Behavior 名称。

- [ ] **Step 2: 运行页面测试确认失败**

Run:

```powershell
cd web
npm test -- --run src/pages/CustomStudio.test.tsx
```

Expected: FAIL，Generate Panel 尚未区分 active 和 Primary。

- [ ] **Step 3: 拆分 Preview 和 Primary 请求**

在 `CustomGeneratePanel` 中建立：

```ts
const primaryBehavior = behaviorGroup.primary;
const activeBehavior = findPromptBehaviorVariant(
  behaviorGroup,
  state.activePromptBehaviorSlotId,
) ?? primaryBehavior;

const previewRequest = buildComposeRenderRequest(primaryNodes, params, {
  compare: false,
  promptBehavior: activeBehavior.value,
});

const primaryRequest = buildComposeRenderRequest(primaryNodes, params, {
  compare: false,
  promptBehavior: primaryBehavior.value,
});
```

Preview signature 跟随 active，Generate 仅在当前 Preview 正好是 Primary 时复用，否则重新 compose Primary。

- [ ] **Step 4: 更新 Compare UI**

矩阵摘要加入 Behavior 数量，Compare 调用传入完整 Group：

```ts
await compare.start(groups, params, behaviorGroup);
```

结果卡片增加：

```tsx
<dt>Behavior</dt><dd>{result.behavior.label}</dd>
```

普通 Generate 状态显示 `Generating Primary`，避免当前编辑 Compare 时产生误解。

- [ ] **Step 5: 运行页面测试**

Run:

```powershell
cd web
npm test -- --run src/pages/CustomStudio.test.tsx
```

Expected: PASS。

- [ ] **Step 6: 提交 Task 5**

```powershell
git add web/src/components/CustomGeneratePanel.tsx web/src/pages/CustomStudio.test.tsx
git commit -m "feat: integrate prompt behavior compare generation"
```

---

### Task 6: 全链路验证和 NovelAI 真实出图

**Files:**
- Modify: `docs/web_control_console_readme.md`
- Create: `docs/web_prompt_behavior_compare_business_test_20260724.md`
- Test: Web 全量测试、前端构建、实际 Web 服务和 NovelAI 输出。

**Interfaces:**
- Consumes: Tasks 1-5 的完整实现。
- Produces: 用户使用说明和可复查的真实出图证据。

- [ ] **Step 1: 运行前端全量测试和构建**

Run:

```powershell
cd web
npm test
npm run build
```

Expected: 全部 PASS，TypeScript 和 Vite build 成功。

- [ ] **Step 2: 运行 Web 后端回归测试**

Run:

```powershell
uv run pytest tests/test_web_prompt_behavior.py
```

Expected: PASS，Web Prompt Behavior API 契约不变。

- [ ] **Step 3: 启动合并后的主目录 Web 服务**

Run:

```powershell
uv run python scripts/dev_web.py --no-install
```

Expected:

```text
Frontend: http://127.0.0.1:53173/
Backend:  http://127.0.0.1:8765/api
```

- [ ] **Step 4: 执行浏览器业务验证**

在 Custom 页面选择：

```text
Artist:
F:/my_project/new/tags_machine/design/画风/109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable

Character:
F:/my_project/new/tags_machine/design/角色/danbooru_mahou_shoujo_madoka_magica/danbooru_akemi_homura_暁美ほむら _魔法少女

Action:
F:/my_project/new/tags_machine/design/动作改2/new/20260526_standing_leglock
```

创建两个 Behavior：

```text
Default: Character Prompts Auto
No Character Prompts: Character Prompts Off
```

使用 `NT=1` 和固定 seed，先 Preview 两个方案，再执行 Compare Generate。

- [ ] **Step 5: 核对真实结果**

必须记录：

- 两个任务使用相同 seed。
- Auto 请求包含 `character_prompts`，Off 请求不包含。
- 两张 PNG 均存在且可读取参数。
- Auto 图片参数包含 Character Prompts/char captions，Off 图片不包含对应拆分。
- Web 结果卡片显示正确 Behavior 名称。
- 两张图片路径和所属 compare group 目录。

- [ ] **Step 6: 更新文档**

在 `web_control_console_readme.md` 增加 Prompt Behavior Compare 使用说明。在业务测试文档记录请求差异、图片路径、PNG 参数和视觉观察，不记录 NovelAI token。

- [ ] **Step 7: 提交 Task 6**

```powershell
git add docs/web_control_console_readme.md docs/web_prompt_behavior_compare_business_test_20260724.md
git commit -m "docs: verify prompt behavior compare workflow"
```

- [ ] **Step 8: 最终状态检查**

Run:

```powershell
git status --short --branch
git log -7 --oneline
```

Expected: 本功能文件均已提交；用户原有无关改动仍保持原状态。
