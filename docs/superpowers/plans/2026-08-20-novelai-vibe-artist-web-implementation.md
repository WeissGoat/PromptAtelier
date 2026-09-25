# NovelAI Vibe Artist Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Web Custom 的 Prompt Behavior 中增加默认关闭的 NovelAI Vibe Artist 配置，启用后可搜索并选择独立的 artist 作为 NovelAI vibe 来源。

**Architecture:** Web 使用用户友好的 `novelai_vibe_artist` 行为配置，但请求桥接层转换为现有 renderer policy 的 `novelai_vibe` 规则和 `source.type: artist` 结构。Vibe artist 只保存为独立 ref，不占用主 Artist 节点槽位；后端继续复用已经实现的 `NovelAIRenderPolicyPipeline`，不改变 PromptBundle、AgentComposer 或基础 artist 拼接。

**Tech Stack:** React、TypeScript、Vitest、现有 FastAPI `/api/nodes` 分页搜索接口、现有 `PromptBehaviorParams` 持久化结构。

## Global Constraints

- 只修改 `refactor` 子模块，不修改父项目旧 `tags_machine`。
- 默认关闭 `novelai_vibe_artist`，关闭时请求中不能出现启用的 `novelai_vibe` renderer rule。
- 启用但未选择 artist 时，Preview/Generate 在前端阻止提交并显示明确错误。
- artist 搜索复用 `/api/nodes?role=artist&q=...`，支持已有分页和模糊搜索行为。
- Vibe artist 与主 Artist 节点独立；选择 Vibe artist 不能替换或修改主 Artist。
- 不改变 AgentComposer 的 PromptPolicyPipeline bypass 语义。
- 注释使用中文；不回滚工作区中与本功能无关的已有改动。

---

### Task 1: 扩展 Prompt Behavior 状态和请求桥接

**Files:**
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/promptBehavior.ts`
- Modify: `web/src/workspace/requestBuilder.ts`
- Test: `web/src/workspace/requestBuilder.test.ts`
- Test: `web/src/workspace/storage.test.ts`

**Interfaces:**
- `PromptBehaviorParams.policyRules.novelai_vibe_artist` 使用 `{ state, options?: { artist_ref?: string } }`。
- 新增 `NOVELAI_VIBE_ARTIST_RULE_ID = "novelai_vibe_artist"` 常量，避免 UI、归一化和桥接层散落字符串。
- `buildComposeRenderRequest` 将启用的前端规则转换为后端 `novelai_vibe`：

```ts
{
  novelai_vibe: {
    enabled: true,
    options: { source: { type: "artist", ref: artistRef } },
  },
}
```

- Disabled/inherit/空 ref 均不生成 `novelai_vibe`；启用且空 ref 抛出 `NovelAI Vibe Artist 必须先选择 artist`。

- [ ] **Step 1: 添加状态归一化测试**

验证旧浏览器快照没有该字段时仍能加载；包含合法 artist ref 时保留；空字符串归一化为空字符串或缺省值，不自动启用。

- [ ] **Step 2: 添加请求桥接测试**

覆盖默认行为、启用后生成 `novelai_vibe`、关闭后不发送、启用空 ref 抛错，以及主 `render.artist` 与 vibe `source.ref` 可以不同。

- [ ] **Step 3: 实现类型、默认值和归一化**

`createDefaultPromptBehavior` 不添加 enabled 状态，或显式使用 disabled；最终 UI 状态必须显示为关闭，且行为 fingerprint 对 ref 和 enabled 状态敏感。

- [ ] **Step 4: 实现 requestBuilder 的专用桥接**

先构造现有 prompt policy rules，再读取 `novelai_vibe_artist`。只有 `state === "enabled"` 时校验 ref 并写入后端规则；不要把前端专用 rule id 直接传给后端 registry。

- [ ] **Step 5: 运行前端 workspace 测试**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run src/workspace/requestBuilder.test.ts src/workspace/storage.test.ts
```

Expected: 新增用例和原有 workspace 用例全部通过。

### Task 2: 增加可复用的 artist 搜索选择控件

**Files:**
- Create: `web/src/components/ArtistRefPicker.tsx`
- Test: `web/src/components/ArtistRefPicker.test.tsx`
- Modify: `web/src/components/PromptBehaviorPanel.tsx`
- Modify: `web/src/components/PromptBehaviorPanel.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- `ArtistRefPicker` 接收 `value: string`、`onChange(ref: string, label?: string)`、`disabled?: boolean`。
- 通过 `/nodes?role=artist&limit=20&offset=...&q=...` 搜索，复用 NodePicker 的 300ms debounce、分页、滚动加载、取消和错误显示约定。
- 选择结果只回调 `node.ref`，不写入 workspace 的 `groups.artist`。

- [ ] **Step 1: 添加控件行为测试**

使用 mock `apiGet` 验证聚焦加载、输入 q、渲染结果、选择 ref、清空 ref、加载下一页和请求错误提示。

- [ ] **Step 2: 实现 ArtistRefPicker**

提取或复用现有 NodePicker 的搜索请求逻辑；控件显示文件名/节点名称，不显示路径；结果面板支持滚动分页。不要复制一套节点读取或 artist 解析逻辑。

- [ ] **Step 3: 在 PromptBehaviorPanel 增加 NovelAI Vibe Artist 区域**

将其作为 renderer-specific behavior 单独展示：关闭时只显示开关；启用时显示搜索选择器和当前选择。切换关闭保留已选 ref，但请求桥接不生效。

- [ ] **Step 4: 增加面板测试**

验证默认关闭；切换 enabled 后出现 artist 搜索；选择结果写入 `policyRules.novelai_vibe_artist.options.artist_ref`；disabled 状态不显示或不要求选择；已有 ref 能恢复显示。

- [ ] **Step 5: 运行组件测试**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run src/components/ArtistRefPicker.test.tsx src/components/PromptBehaviorPanel.test.tsx
```

Expected: 控件和面板测试通过。

### Task 3: 完成 Web/API 端到端参数验证

**Files:**
- Modify: `web/src/components/PromptBehaviorPanel.test.tsx` if integration assertions need adjustment
- Modify: `web/src/workspace/requestBuilder.test.ts`
- Test/Inspect: `src/tags_machine_core/web/routes/compose.py`, `src/tags_machine_core/services/json_api.py`, `src/tags_machine_core/policies/rendering/novelai.py`

**Interfaces:**
- Web `compose_render_plan` 请求中的 `compose.prompt_policy.rules.novelai_vibe` 必须被现有 API 复制到 render 阶段。
- `NovelAIRenderPolicyPipeline` 接收 `source.type: artist` 后，只替换 `reference_image_multiple`、`reference_strength_multiple`、`reference_information_extracted_multiple`。

- [ ] **Step 1: 用前端请求 fixture 验证 JSON 形状**

断言 `buildComposeRenderRequest` 输出的 `compose.prompt_policy` 使用 backend rule id `novelai_vibe`，并且 `render.artist` 仍等于主 artist ref。

- [ ] **Step 2: 执行后端现有 renderer policy 集成测试**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run pytest tests/test_novelai_render_policy.py tests/test_novelai_vibe_integration.py -q
```

Expected: 现有 artist source policy 测试通过，确认不需要新增后端规则或修改 AgentComposer。

- [ ] **Step 3: 执行 Web 构建和全量前端测试**

Run:

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm run test -- --run
npm run build
```

Expected: Vitest 无失败，Vite build 成功。

- [ ] **Step 4: 记录业务验收结果**

用 Web Custom 完成两次 compose-preview：

1. 关闭 Vibe Artist：请求不含启用的 `novelai_vibe`，基础预览与改动前一致。
2. 启用并选择一个不同于主 Artist 的 artist：preview 的 `render_request.parameters.reference_image_multiple` 来自所选 Vibe artist，`render_request.artist_payload` 仍来自主 Artist。

记录请求 JSON 和 UI 错误提示；本任务不要求真实 NovelAI 出图，因为后端 renderer policy 已有独立业务验证，但必须确认 compose-preview 参数链路正确。

### Task 4: 文档与变更提交

**Files:**
- Modify: `docs/prompt_policy_configuration.md`
- Modify: `README.md` if Web option list is documented there

- [ ] **Step 1: 补充 Web 配置说明**

写明 `novelai_vibe_artist` 是 Web 层行为名，默认关闭；启用后通过 artist 搜索选择 vibe 来源；主 Artist 与 Vibe Artist 可不同；关闭后已选 ref 保留但不参与请求。

- [ ] **Step 2: 检查文档与实现一致性**

确认文档没有声称 AgentComposer 经过 PromptPolicyPipeline，也没有把 `novelai_vibe_artist` 错写成后端 registry rule id。

- [ ] **Step 3: 检查 diff 并提交本功能变更**

```powershell
cd F:\my_project\new\tags_machine\refactor
git diff --check
git add web/src/components/ArtistRefPicker.tsx web/src/components/ArtistRefPicker.test.tsx web/src/components/PromptBehaviorPanel.tsx web/src/components/PromptBehaviorPanel.test.tsx web/src/workspace/types.ts web/src/workspace/promptBehavior.ts web/src/workspace/requestBuilder.ts web/src/workspace/requestBuilder.test.ts web/src/workspace/storage.test.ts web/src/styles.css docs/prompt_policy_configuration.md README.md
git commit -m "feat: configure NovelAI vibe artist in web"
```

## Self-Review Checklist

- `novelai_vibe_artist` 默认关闭是否同时满足 UI、持久化和请求三层？
- 启用空 ref 是否在请求前失败，而不是让后端返回模糊的 source 错误？
- Vibe artist 是否始终与主 Artist 槽位分离？
- 搜索是否复用现有 artist 根目录和分页接口？
- 前端专用名称是否正确桥接为后端已有 `novelai_vibe`？
- AgentComposer 和其他 policy 是否保持原行为？
