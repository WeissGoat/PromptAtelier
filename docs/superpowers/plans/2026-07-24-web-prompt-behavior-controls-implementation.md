# Web 提示词行为配置实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Web Custom 工作台支持 `identity_minimal_sections`、NovelAI Character Prompts 和基于项目 `legacy_compat` 的单条 Policy 规则覆盖，并保证 Preview、Generate、Compare 使用同一份配置。

**Architecture:** 后端由 Web 应用配置构造项目级 `PromptPolicyProvider`，JSON API 只接收局部规则覆盖并将 `identity_minimal_sections` 传给 ScriptComposer。前端新增独立的 Prompt Behavior 状态和面板，Request Builder 将提示词行为分别写入 `compose` 与 `render.params`，Compare 复用同一份行为配置。

**Tech Stack:** Python 3、FastAPI、Pydantic、uv、TypeScript、React、Vitest、Vite。

## Global Constraints

- 不提供 Policy 模板选择，Web 始终继承当前项目配置的 Policy 基线。
- Policy 单条规则必须支持 `inherit`、`enabled`、`disabled` 三态；`inherit` 不进入请求。
- `identity_minimal_sections` 覆盖模式至少保留一个 section，不允许空数组。
- Character Prompts 只提供 `auto` 和 `off`，工作区默认 `auto`。
- AgentComposer 不经过这套 Script Policy 链路。
- 不修改或还原工作区中与本功能无关的 action resolver、batch、NovelAI gateway 改动。
- 运行验证以 Web 业务链路和前后端测试为主，不调用真实 NovelAI 生成以避免无关 Anlas 消耗。

---

### Task 1: 注入项目 Policy 基线并扩展 JSON API

**Files:**
- Modify: `src/tags_machine_core/web/app.py`
- Modify: `src/tags_machine_core/services/json_api.py`
- Test: `tests/test_web_prompt_behavior.py`

**Interfaces:**
- `create_app()` 使用 `build_prompt_policy_provider(config, config_path=resolved_config_path)` 创建 `GenerationService(policy_provider=...)`，再注入 `GenerationJsonApi`。
- `GenerationJsonApi.compose()` 从 compose payload 读取 `identity_minimal_sections`，校验为非空字符串列表后传入 `GenerationService.compose_resolved_nodes()`。
- `GenerationJsonApi.compose()` 保持 `prompt_policy` 为局部映射；不允许通过 Web 请求替换 `require`。

- [ ] **Step 1: 写后端失败测试**

在 `tests/test_web_prompt_behavior.py` 增加：

```python
def test_compose_preview_passes_identity_minimal_sections_to_script_composer():
    response = client.post(
        "/api/compose-preview",
        json={
            "compose": {
                "nodes": [{"role": "character", "ref": str(character_dir)}],
                "identity_minimal_sections": ["character", "role"],
            },
            "render": {"backend": "novelai", "width": 1024, "height": 1024},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_bundle"]["meta"]["composition"]["included_character_sections"] == [
        "character",
        "role",
    ]


def test_compose_preview_rejects_empty_identity_override():
    response = client.post(
        "/api/compose-preview",
        json={
            "compose": {
                "nodes": [{"role": "character", "ref": str(character_dir)}],
                "identity_minimal_sections": [],
            },
            "render": {},
        },
    )
    assert response.status_code == 400


def test_web_policy_override_inherits_project_legacy_compat():
    response = client.post(
        "/api/compose-preview",
        json={
            "compose": {
                "nodes": [{"role": "character", "ref": str(character_dir)}],
                "prompt_policy": {
                    "rules": {"visibility_policy": {"enabled": False}},
                },
            },
            "render": {},
        },
    )
    assert response.status_code == 200
    policy = response.json()["prompt_bundle"]["meta"]["extra"]["policy"]
    assert "legacy_compat" in policy["template"]
```

- [ ] **Step 2: 运行失败测试**

运行：

```powershell
uv run python -m unittest tests.test_web_prompt_behavior -v
```

预期：新测试因 JSON API 尚未透传字段或 Web 未注入项目 Provider 而失败。

- [ ] **Step 3: 实现后端链路**

在 `app.py` 中构造：

```python
policy_provider = build_prompt_policy_provider(
    config,
    config_path=resolved_config_path,
)
generation_service = GenerationService(policy_provider=policy_provider)
app.state.generation_api = GenerationJsonApi(
    service=generation_service,
    artist_loader=NovelAIArtistRepository(config.legacy.design_root).load_node,
    generation_executor=generation_executor or _default_generation_executor(config),
)
```

在 `json_api.py` 中：

```python
identity_sections = _optional_non_empty_string_list(
    data.get("identity_minimal_sections"),
    "identity_minimal_sections",
)
bundle = self.service.compose_resolved_nodes(
    resolved_nodes,
    extra_prompt=str(data.get("extra_prompt") or data.get("prompt") or ""),
    negative=str(data.get("negative") or ""),
    identity_minimal_sections=identity_sections,
    prompt_policy=_optional_mapping(data.get("prompt_policy")),
)
```

`prompt_policy.require` 在 Web 请求中出现时返回 400，防止 Web 绕过项目基线切换模板。新增辅助函数统一校验字符串列表：输入必须是非空 list，元素必须是非空字符串。

- [ ] **Step 4: 运行后端测试**

运行：

```powershell
uv run python -m unittest tests.test_web_prompt_behavior tests.test_web_nodes tests.test_web_results tests.test_web_node_save -v
```

预期：全部通过。

- [ ] **Step 5: 提交后端链路**

```powershell
git add src/tags_machine_core/web/app.py src/tags_machine_core/services/json_api.py tests/test_web_prompt_behavior.py
git commit -m "feat: expose prompt behavior through web api"
```

### Task 2: 扩展前端工作区状态与请求构建

**Files:**
- Modify: `web/src/workspace/types.ts`
- Modify: `web/src/workspace/storage.ts`
- Modify: `web/src/workspace/CustomWorkspaceProvider.tsx`
- Modify: `web/src/workspace/requestBuilder.ts`
- Test: `web/src/workspace/storage.test.ts`
- Test: `web/src/workspace/requestBuilder.test.ts`

**Interfaces:**

```ts
export type PolicyRuleState = "inherit" | "enabled" | "disabled";

export type PromptBehaviorParams = {
  identityMinimal: {
    mode: "inherit" | "override";
    sections: string[];
  };
  characterPrompts: {
    mode: "auto" | "off";
    addMaleCaption: boolean;
  };
  policyRules: Record<string, {
    state: PolicyRuleState;
    options?: Record<string, unknown>;
  }>;
};
```

`CustomWorkspaceState` 增加 `promptBehavior: PromptBehaviorParams`。旧 localStorage 数据恢复时使用：

```ts
{
  identityMinimal: { mode: "inherit", sections: [] },
  characterPrompts: { mode: "auto", addMaleCaption: true },
  policyRules: {}
}
```

- [ ] **Step 1: 写状态迁移和请求构建失败测试**

覆盖：

```ts
it("migrates old workspace state with prompt behavior defaults", () => {
  const restored = restoreWorkspace(oldState);
  expect(restored.promptBehavior.characterPrompts.mode).toBe("auto");
  expect(restored.promptBehavior.policyRules).toEqual({});
});

it("omits inherited prompt behavior from compose request", () => {
  const request = buildComposeRenderRequest(selected, params, {
    compare: false,
    promptBehavior: inheritedPromptBehavior,
  });
  expect(request.compose).not.toHaveProperty("identity_minimal_sections");
  expect(request.compose).not.toHaveProperty("prompt_policy");
});

it("serializes identity, policy overrides, and character prompts", () => {
  const request = buildComposeRenderRequest(selected, params, {
    compare: false,
    promptBehavior: {
      identityMinimal: { mode: "override", sections: ["character", "role"] },
      characterPrompts: { mode: "auto", addMaleCaption: true },
      policyRules: {
        visibility_policy: { state: "disabled" },
      },
    },
  });
  expect(request.compose.identity_minimal_sections).toEqual(["character", "role"]);
  expect(request.compose.prompt_policy.rules.visibility_policy.enabled).toBe(false);
  expect(request.render.params.character_prompts).toEqual({
    mode: "auto",
    add_male_caption: true,
  });
});
```

- [ ] **Step 2: 运行失败测试**

```powershell
cd web
npm run test -- src/workspace/storage.test.ts src/workspace/requestBuilder.test.ts
```

预期：类型和序列化逻辑尚未存在，测试失败。

- [ ] **Step 3: 实现类型、迁移和请求构建**

`buildComposeRenderRequest` 的 options 扩展为：

```ts
options: {
  compare: boolean;
  promptBehavior: PromptBehaviorParams;
}
```

构建规则：

- Identity `mode === "override"` 时写入 `compose.identity_minimal_sections`，并在构建时拒绝空数组。
- Policy 只序列化 state 不是 `inherit` 的规则。
- Policy 选项只有规则 `enabled` 时才序列化。
- Character Prompts `auto` 写入 snake_case 参数；`off` 不写入。
- Compare 仍将 `n_samples` 固定为 1，但不改变上述提示词行为配置。

- [ ] **Step 4: 运行前端工作区测试**

```powershell
npm run test -- src/workspace/storage.test.ts src/workspace/requestBuilder.test.ts
```

预期：相关测试全部通过。

- [ ] **Step 5: 提交工作区请求状态**

```powershell
git add web/src/workspace/types.ts web/src/workspace/storage.ts web/src/workspace/CustomWorkspaceProvider.tsx web/src/workspace/requestBuilder.ts web/src/workspace/storage.test.ts web/src/workspace/requestBuilder.test.ts
git commit -m "feat: persist web prompt behavior settings"
```

### Task 3: 实现提示词行为面板

**Files:**
- Create: `web/src/components/PromptBehaviorPanel.tsx`
- Create: `web/src/components/PromptBehaviorPanel.test.tsx`
- Modify: `web/src/components/CustomGeneratePanel.tsx`
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**

```tsx
type PromptBehaviorPanelProps = {
  value: PromptBehaviorParams;
  characterSections: string[];
  onChange: (value: PromptBehaviorParams) => void;
};
```

- [ ] **Step 1: 写面板行为测试**

测试以下用户行为：

```tsx
it("defaults to auto character prompts and inherited policy rules", () => {
  render(<PromptBehaviorPanel value={defaultPromptBehavior} ... />);
  expect(screen.getByLabelText("Character Prompts Auto")).toBeChecked();
  expect(screen.getByText("Inherited")).toBeInTheDocument();
});

it("does not allow removing the last identity section", async () => {
  render(<PromptBehaviorPanel value={overrideWithOneSection} ... />);
  await user.click(screen.getByRole("button", { name: "Remove character" }));
  expect(screen.getByText(/至少选择一个/)).toBeInTheDocument();
});

it("renders advanced options only for enabled rules", async () => {
  render(<PromptBehaviorPanel value={defaultPromptBehavior} ... />);
  expect(screen.queryByLabelText("Visibility mode")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Visibility Policy/ }));
  await user.click(screen.getByRole("radio", { name: "Enabled" }));
  expect(screen.getByLabelText("Visibility mode")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行失败测试**

```powershell
npm run test -- src/components/PromptBehaviorPanel.test.tsx
```

预期：组件尚未创建，测试失败。

- [ ] **Step 3: 实现面板**

界面分为三个区域：

1. Identity Minimal Sections：继承/覆盖切换、section 多选、section 自定义输入。
2. Character Prompts：Auto/Off、男性 caption 开关。
3. Policy Rules：规则名称、三态选择、规则 options 折叠区。

规则 ID 使用固定列表，避免服务端返回任意规则导致 UI 不可控：

```ts
const POLICY_RULES = [
  "tag_normalize",
  "dedupe",
  "character_section_filter",
  "tag_conflict",
  "character_count",
  "clothing_policy",
  "visibility_policy",
  "character_extension",
  "character_weight",
] as const;
```

Identity section 至少保留一个的校验必须在删除按钮和 `onChange` 两处执行。Policy 三态使用 segmented control，不使用 JSON 编辑器。

- [ ] **Step 4: 接入 Custom 页面并运行测试**

从当前已选角色节点收集 section 并传给面板；面板变更更新 `CustomWorkspaceProvider`，随后传给 Preview 和 Generate 的同一个 request builder。

```powershell
npm run test -- src/components/PromptBehaviorPanel.test.tsx src/pages/CustomStudio.test.tsx src/components/CustomGeneratePanel.test.tsx
```

预期：新旧 Custom 测试全部通过。

- [ ] **Step 5: 提交 UI**

```powershell
git add web/src/components/PromptBehaviorPanel.tsx web/src/components/PromptBehaviorPanel.test.tsx web/src/components/CustomGeneratePanel.tsx web/src/pages/CustomStudio.tsx web/src/styles.css
git commit -m "feat: add web prompt behavior panel"
```

### Task 4: 接入 Compare 和 Preview 展示

**Files:**
- Modify: `web/src/compare/useCompareRunController.ts`
- Modify: `web/src/compare/runPlan.ts`
- Modify: `web/src/pages/CustomStudio.tsx`
- Modify: `web/src/components/PromptPreview.tsx`
- Test: `web/src/compare/useCompareRunController.test.tsx`
- Test: `web/src/pages/CustomStudio.test.tsx`

**Interfaces:**

- Compare controller 接收 `PromptBehaviorParams`。
- 每个 compare task 使用同一份 prompt behavior 对象，只替换 compare node。
- Preview 只读展示：
  - effective Policy template
  - identity included/suppressed sections
  - Character Prompts status

- [ ] **Step 1: 增加 Compare 一致性测试**

```tsx
it("uses the same prompt behavior for every compare matrix task", async () => {
  const requests = await runCompareWithPromptBehavior(promptBehavior);
  expect(new Set(requests.map((item) => JSON.stringify(item.compose.prompt_policy)))).toHaveSize(1);
  expect(new Set(requests.map((item) => JSON.stringify(item.render.params.character_prompts)))).toHaveSize(1);
  expect(requests.every((item) => item.compose.identity_minimal_sections?.length === 2)).toBe(true);
});
```

- [ ] **Step 2: 实现 Compare 传播**

让 `useCompareRunController` 和 `runPlan` 从 workspace 获取 prompt behavior，生成每个组合请求时保持同一份对象。禁止在 compare 分支重新创建默认配置。

- [ ] **Step 3: 实现 Preview 摘要**

从后端 `PromptBundle.meta` 和 `RenderRequest.meta.character_prompts` 读取实际结果，显示有效结果而不是只显示前端表单值。

- [ ] **Step 4: 运行测试**

```powershell
npm run test -- src/compare/useCompareRunController.test.tsx src/pages/CustomStudio.test.tsx
```

预期：Compare Matrix、NT 分组和 Preview 摘要测试全部通过。

- [ ] **Step 5: 提交 Compare 集成**

```powershell
git add web/src/compare/useCompareRunController.ts web/src/compare/runPlan.ts web/src/pages/CustomStudio.tsx web/src/components/PromptPreview.tsx web/src/compare/useCompareRunController.test.tsx web/src/pages/CustomStudio.test.tsx
git commit -m "feat: keep prompt behavior consistent in compare runs"
```

### Task 5: 业务链路验收与文档更新

**Files:**
- Modify: `docs/web_control_console_readme.md`
- Modify: `docs/web_control_console_business_test_20260710.md`
- Test: `tests/test_web_prompt_behavior.py`
- Test: `web/src/pages/CustomStudio.test.tsx`

- [ ] **Step 1: 增加后端完整链路验收**

通过 `/api/compose-preview` 验证：

1. 默认 legacy_compat 的角色权重/规则结果。
2. 关闭 visibility_policy 后脚部特写相关角色特征不再被该规则删除。
3. `identity_minimal_sections` 覆盖后 included/suppressed sections 正确。
4. Character Prompts auto 进入 RenderRequest，并生成 `characterPrompts` 或 v4 caption。
5. Character Prompts off 不进行拆分。
6. Agent 请求仍返回 Agent task，不进入 Script Policy。

- [ ] **Step 2: 运行完整后端 Web 测试**

```powershell
uv run python -m unittest tests.test_web_prompt_behavior tests.test_web_nodes tests.test_web_results tests.test_web_node_save -v
```

预期：全部通过。

- [ ] **Step 3: 运行完整前端测试和构建**

```powershell
cd web
npm run test
npm run build
```

预期：所有 Vitest 测试通过，TypeScript 编译和 Vite 构建成功。

- [ ] **Step 4: 手工启动 Web 业务验证**

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python scripts/dev_web.py
```

在 Custom 页确认：

- 默认 Character Prompts 为 Auto。
- Identity 继承/覆盖切换有效。
- 覆盖模式不能删除最后一个 section。
- Policy 规则三态切换有效。
- Preview 的实际 Prompt、Policy trace、Character Prompts 状态与表单一致。
- Generate 成功后结果页仍能读取图片元数据。
- Compare Generate 每个组合使用相同的提示词行为和非画师参数。

- [ ] **Step 5: 更新 README**

补充 Web 请求字段、三态 Policy 语义、Identity 覆盖限制、Character Prompts 参数和 Preview/Compare 验收说明。

- [ ] **Step 6: 提交文档与最终验收**

```powershell
git add docs/web_control_console_readme.md docs/web_control_console_business_test_20260710.md
git commit -m "docs: document web prompt behavior controls"
git status --short
```

## 自审结果

- `identity_minimal_sections` 的非空约束覆盖了 UI 删除、请求构建和后端 API 三层。
- Character Prompts 明确为 `auto/off`，避免把 Batch defaults 错当成 Web Custom 的运行时继承来源。
- Policy 模板不可由 Web 请求替换，单条规则通过三态覆盖，满足项目配置可持续继承要求。
- Preview、Generate、Compare 均复用同一 Request Builder 和 Prompt Behavior 状态。
- AgentComposer 未增加 Policy 参数，仍保持现有链路隔离。
