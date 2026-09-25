# NovelAI Vibe Artist Web Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Web Custom 的 `novelai_vibe_artist` 配置完整支持后端已经实现的 Artist Vibe 扩展。

**Architecture:** Web 继续保存用户友好的 `novelai_vibe_artist` 配置，包含 `artist_ref`、`mode`、`strength` 和 `information_extracted`。请求构建器把它转换为后端统一的 `novelai_vibe` renderer rule；后端 Renderer 和 NovelAI client 不修改。Compare 的每个 Prompt Behavior variant 使用自己的配置对象，因此互不污染。

**Tech Stack:** React 18、TypeScript、Vitest、Testing Library、现有 `NodePicker` 和 `PromptBehavior` 状态结构。

## Global Constraints

- 只修改 `refactor` 子模块。
- 不改变 AgentComposer、PromptBundle 和 NovelAI client。
- 关闭 `novelai_vibe_artist` 时请求中不得出现启用的 `novelai_vibe`。
- Artist ref 必须通过现有 Artist 搜索控件选择。
- Vibe 参数留空时由后端从来源 Artist 节点读取默认值。
- 单值和逗号分隔数组都要转换为后端接受的 number 或 number[]。
- 注释使用中文；不写入真实 token。

---

### Task 1: 扩展 Web Vibe Artist 状态到请求桥接

**Files:**
- Modify: `web/src/workspace/requestBuilder.ts`
- Test: `web/src/workspace/requestBuilder.test.ts`

**Interfaces:**
- 输入：`PromptBehaviorParams.policyRules.novelai_vibe_artist`，其 options 为 `{ artist_ref?: string; mode?: "replace" | "merge"; strength?: number | number[]; information_extracted?: number | number[] }`。
- 输出：后端 `compose.prompt_policy.rules.novelai_vibe`，只包含 `source`、可选 `mode`、可选 `strength` 和可选 `information_extracted`。

- [x] **Step 1: 添加失败测试**

在 `requestBuilder.test.ts` 增加以下断言：启用规则并传入 `mode: "merge"`、`strength: [0.2, 0.3]`、`information_extracted: 0.85` 时，生成后端 options，且不包含 `artist_ref`。

```ts
expect(request.compose.prompt_policy?.rules.novelai_vibe).toEqual({
  enabled: true,
  options: {
    mode: "merge",
    source: { type: "artist", ref: "F:/artists/vibe" },
    strength: [0.2, 0.3],
    information_extracted: 0.85,
  },
});
```

- [x] **Step 2: 运行测试确认失败**

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run src/workspace/requestBuilder.test.ts
```

预期：新增断言失败，因为当前桥接只发送 `source`。

- [x] **Step 3: 实现专用 options 桥接**

在 `buildComposeRenderRequest` 的 Vibe Artist 分支中，只复制后端支持字段：

```ts
const sourceOptions = vibeArtistRule.options ?? {};
const vibeOptions: Record<string, unknown> = {
  source: { type: "artist", ref: artistRef },
};
if (sourceOptions.mode === "replace" || sourceOptions.mode === "merge") {
  vibeOptions.mode = sourceOptions.mode;
}
if (typeof sourceOptions.strength === "number" || Array.isArray(sourceOptions.strength)) {
  vibeOptions.strength = structuredClone(sourceOptions.strength);
}
if (typeof sourceOptions.information_extracted === "number" || Array.isArray(sourceOptions.information_extracted)) {
  vibeOptions.information_extracted = structuredClone(sourceOptions.information_extracted);
}
rules.novelai_vibe = { enabled: true, options: vibeOptions };
```

不要把整个 Web options 直接复制给后端，避免 `artist_ref` 或未来 UI 字段进入 Pydantic 的 `extra="forbid"` 校验。

- [x] **Step 4: 运行桥接测试确认通过**

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run src/workspace/requestBuilder.test.ts
```

预期：该文件全部通过。

### Task 2: 为 Vibe Artist 表单增加扩展选项

**Files:**
- Modify: `web/src/components/PromptBehaviorPanel.tsx`
- Modify: `web/src/workspace/promptBehavior.ts`
- Test: `web/src/components/PromptBehaviorPanel.test.tsx`

**Interfaces:**
- `mode` 使用下拉选项 `replace` / `merge`，默认 `replace`。
- `strength` 与 `information_extracted` 使用文本框，空值代表沿用来源节点，多个值使用逗号分隔。
- 状态中保存归一化后的 `number` 或 `number[]`，不保存带逗号的原始字符串。

- [x] **Step 1: 添加失败的交互测试**

测试启用 Vibe Artist 后显示三个控件；选择 merge 并填写值后，`onChange` 收到：

```ts
expect(lastValue.policyRules.novelai_vibe_artist).toEqual({
  state: "enabled",
  options: {
    mode: "merge",
    strength: [0.2, 0.3],
    information_extracted: 0.85,
  },
});
```

- [x] **Step 2: 实现数值输入归一化**

在 `PromptBehaviorPanel.tsx` 增加纯函数：

```ts
function parseNumberOption(value: string): number | number[] | undefined {
  const items = value.split(",").map((item) => item.trim()).filter(Boolean);
  if (!items.length) return undefined;
  const numbers = items.map(Number);
  if (numbers.some((item) => !Number.isFinite(item))) return undefined;
  return numbers.length === 1 ? numbers[0] : numbers;
}
```

输入无效或为空时不把非法字符串传给后端；空值应删除对应 option。UI 的 `value` 由 number/number[] 格式化为文本。

- [x] **Step 3: 在 Vibe Artist 区域渲染控件**

在 ArtistPicker 下方增加：

```tsx
<label className="field">
  <span>Vibe mode</span>
  <select aria-label="Vibe mode" value={String(options.mode ?? "replace")} onChange={(event) => setRuleOption(NOVELAI_VIBE_ARTIST_RULE_ID, "mode", event.target.value)}>
    <option value="replace">Replace</option>
    <option value="merge">Merge</option>
  </select>
</label>
<label className="field">
  <span>Strength</span>
  <input aria-label="Vibe strength" placeholder="留空沿用节点；多个值用逗号分隔" value={formatNumberOption(options.strength)} onChange={...} />
</label>
<label className="field">
  <span>Information extracted</span>
  <input aria-label="Vibe information extracted" placeholder="留空沿用节点；多个值用逗号分隔" value={formatNumberOption(options.information_extracted)} onChange={...} />
</label>
```

使用局部文本状态允许用户输入 `0.2, 0.3`，在输入能解析时更新持久状态；切换到其他行为槽位后再切回来，显示归一化结果。

- [x] **Step 4: 补充状态归一化**

在 `normalizePromptBehavior` 中对 Vibe Artist options 只保留 `artist_ref`、`mode`、`strength`、`information_extracted`。非法 mode 归一化为 `replace`，数字数组中的非法值丢弃；不自动启用规则。

- [x] **Step 5: 运行组件测试**

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run src/components/PromptBehaviorPanel.test.tsx src/components/ArtistRefPicker.test.tsx
```

预期：新增交互测试和原有测试全部通过。

### Task 3: 完成 Web 构建和业务链路验证

**Files:**
- Modify: `web/src/workspace/requestBuilder.test.ts` only if a discovered type mismatch needs a focused regression test.
- Modify: `web/src/components/PromptBehaviorPanel.test.tsx` only if a discovered UI regression needs a focused regression test.

- [x] **Step 1: 运行完整 Web 测试**

运行：

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run
npm run build
```

预期：Vitest 和 TypeScript/Vite 构建均成功。

- [x] **Step 2: 验证请求形状**

确认以下三种情况：

```text
关闭：没有 compose.prompt_policy.rules.novelai_vibe
replace：source + 可选覆盖参数，mode 默认可省略
merge：source + mode=merge + 可选覆盖参数
```

- [x] **Step 3: 进行 Web 业务验证**

启动现有 Web 服务，选择主 Artist 和 Vibe Artist，分别使用 replace 与 merge 做一次 Preview。检查 Preview/最终 RenderRequest 中：

- 主 Artist ref 与 Vibe Artist ref 可以不同；
- `reference_image_multiple`、strength、information 数组由后端正确生成；
- 主 Artist 的 prompt、negative、model、采样参数未被 Vibe Artist 覆盖；
- 关闭开关后重新 Preview，Vibe 参数恢复为未启用状态；
- Compare 中不同 Behavior variant 的 mode/strength 不互相污染。

- [x] **Step 4: 检查 AgentComposer 不受影响**

通过现有 AgentComposer 请求路径检查该 Web 配置不会改变 AgentComposer 的绕过语义；不向 AgentComposer 增加 `novelai_vibe_artist` 默认规则。
