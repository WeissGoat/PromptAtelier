# Web Prompt Behavior 业务验收

## 验收范围

- Identity Minimal Sections
- NovelAI v4/v4.5 Character Prompts
- PromptPolicy 单条规则覆盖
- Preview、Generate、Compare 参数一致性

## 自动化业务链路

后端通过真实 `/api/compose-preview` 链路验证，不直接调用 Composer 或 Renderer 私有方法：

```powershell
uv run python -m unittest tests.test_web_prompt_behavior -v
```

覆盖场景：

1. `identity_minimal_sections` 覆盖进入 ScriptComposer。
2. Identity 空覆盖返回 HTTP 400。
3. Policy 局部覆盖仍继承项目 `legacy_compat`。
4. Web 请求不能通过 `prompt_policy.require` 替换项目模板。
5. Character Prompts Auto 在 v4.5 RenderRequest 中生成 `characterPrompts`。
6. Character Prompts Off 不拆分角色提示词。

前端验证：

```powershell
cd web
npm run test
npm run build
```

重点覆盖：

- 旧 localStorage 工作区自动补齐 Prompt Behavior 默认值。
- Identity 覆盖至少保留一个 section。
- Policy 三态只发送非 Inherit 规则。
- Character Prompts Auto/Off 请求结构正确。
- Compare Matrix 每个组合共享相同 Prompt Behavior。
- TypeScript 编译和 Vite 生产构建成功。

## 手工页面检查

启动：

```powershell
uv run python scripts\dev_web.py --backend-port 8877
```

在 Custom 页检查：

1. Prompt Behavior 显示在生图参数下方。
2. Character Prompts 默认选择 Auto。
3. Identity 切换到 Override 后自动选择 `character` 和 `role`。
4. 最后一个 Identity section 不能取消。
5. Policy Rules 默认显示 Inherit，切换 Enabled 后出现对应高级选项。
6. Preview 摘要显示后端实际 Policy baseline、Identity section 和 Character Prompts 状态。
7. 普通 Generate 和 Compare Generate 使用同一份 Prompt Behavior。

本功能的核心产物是 PromptBundle 和 RenderRequest，自动验收不提交真实 NovelAI 生图，避免对与 UI 配置无关的网络状态和 Anlas 余额形成依赖。
