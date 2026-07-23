# Web 提示词行为配置设计

## 1. 目标

在 Web Custom 工作台中增加三类提示词行为配置：

- `identity_minimal_sections`
- NovelAI Character Prompts
- PromptPolicy 单条规则覆盖

本次不提供 PromptPolicy 模板选择。Web 始终继承当前项目配置中的 Policy 基线，当前基线为 `legacy_compat`，只发送用户明确修改的单条规则配置。

## 2. 设计原则

### 2.1 配置分层

新增独立的“提示词行为”面板，与 Width、Height、Seed、NT 等“生图参数”分开。

提示词行为面板负责：

- ScriptComposer 的角色最小身份 section
- PromptPolicy 局部覆盖
- NovelAI Renderer 的 Character Prompts 行为

现有生图参数面板继续负责：

- Width
- Height
- NT
- Seed

### 2.2 继承优先

Web 不复制项目默认配置。没有被用户修改的设置不进入请求，由后端使用当前项目配置解析有效值。

这样修改 `configs/local.yaml` 或项目 Policy 基线后，旧的 Web 工作区不会用历史布尔值覆盖新默认配置。

### 2.3 Compare 一致性

普通 Generate 和 Compare Generate 共用同一份提示词行为配置。

Compare Matrix 只展开节点组合和 NT 轮次，不为每个组合生成不同的 Policy、Identity 或 Character Prompts 设置。组内继续共享相同的非画师参数和 seed。

## 3. Workspace 状态

`RenderWorkspaceParams` 扩展为包含提示词行为配置，或者增加独立的 `PromptBehaviorParams` 后由 `CustomWorkspaceState` 持有。

推荐结构：

```ts
type InheritMode = "inherit" | "override";
type TriState = "inherit" | "enabled" | "disabled";
type CharacterPromptsMode = "auto" | "off";

type IdentityMinimalConfig = {
  mode: InheritMode;
  sections: string[];
};

type CharacterPromptsConfig = {
  mode: CharacterPromptsMode;
  addMaleCaption: boolean;
};

type PolicyRuleOverride = {
  state: TriState;
  options?: Record<string, unknown>;
};

type PromptBehaviorParams = {
  identityMinimal: IdentityMinimalConfig;
  characterPrompts: CharacterPromptsConfig;
  policyRules: Record<string, PolicyRuleOverride>;
};
```

工作区数据继续存入浏览器存储。恢复旧版本工作区时为新字段补默认值，不让已有节点选择和临时节点草稿失效。

## 4. Identity Minimal Sections

### 4.1 继承模式

默认使用 `inherit`，请求中不发送 `identity_minimal_sections`。

后端使用现有优先级：

```text
本次请求覆盖
  > character meta.yaml identity_minimal
  > 系统默认 [character, role]
```

### 4.2 覆盖模式

启用“本次覆盖”后：

- 从当前 Character 节点的 `tags` key 收集可选 section。
- 对使用结构化 Prompt Fragment 的节点，从 `prompt.positive[].role` 收集可选 section。
- 多角色时取所有角色 section 的并集并去重。
- 允许输入当前节点中不存在的自定义 section。
- 至少选择一个 section，不允许空数组。
- 没有选择 Character 节点时，默认提供 `character`、`role`，并允许增加自定义 section。

删除最后一个 section 时，前端阻止操作并显示明确提示。请求构建阶段再次校验，避免绕过 UI 产生空覆盖。

### 4.3 后端透传

Web JSON API 的 `compose` 请求增加：

```json
{
  "identity_minimal_sections": ["character", "role", "topic"]
}
```

`GenerationJsonApi.compose()` 将其传给 `GenerationService.compose_resolved_nodes()`。该字段只影响 ScriptComposer，不改变 AgentComposer 行为。

## 5. Character Prompts

### 5.1 模式

提供两个值：

- `auto`：启用 NovelAI v4+ Character Prompts 自动拆分。
- `off`：关闭 Character Prompts，不发送 `character_prompts` 配置。

当前 Web Custom 链路不经过 Batch defaults，因此不能通过省略字段表达“继承 Batch 默认值”。工作区初始值固定使用 `auto`，与 `examples/project/base.yaml` 当前默认保持一致。

### 5.2 自动模式参数

首期仅开放：

- `add_male_caption`，默认 `true`

请求写入 Renderer 参数：

```json
{
  "character_prompts": {
    "mode": "auto",
    "add_male_caption": true
  }
}
```

本期不开放：

- `default_caption_prefix`
- `max_characters`
- 手工编辑 `characterPrompts`
- 手工编辑 `v4_prompt.char_captions`

这些字段继续由 NovelAI Renderer 根据节点和最终 Prompt 自动计算。

## 6. PromptPolicy 单条规则

### 6.1 基线

Web 应用创建 `GenerationJsonApi` 时，使用当前 Web 配置文件构造 `PromptPolicyProvider` 并注入 `GenerationService`。

不再让 Web Custom 链路单独使用 `PromptPolicyProvider.with_builtin_defaults()`。这样 Custom 与 Batch 都遵循项目配置中的 Policy 基线，当前为 `legacy_compat`。

### 6.2 三态覆盖

每条规则提供：

- `inherit`：不发送该规则。
- `enabled`：发送 `enabled: true`。
- `disabled`：发送 `enabled: false`。

请求中不允许发送 `require`，因此 Web 无法切换或替换 Policy 模板。

示例：

```json
{
  "prompt_policy": {
    "rules": {
      "visibility_policy": {
        "enabled": false
      },
      "clothing_policy": {
        "enabled": true,
        "options": {
          "mode": "enforce"
        }
      }
    }
  }
}
```

只有非 `inherit` 的规则进入请求。规则处于 `inherit` 时，其临时 options 不进入请求。

### 6.3 首批规则

- `tag_normalize`
- `dedupe`
- `character_section_filter`
- `tag_conflict`
- `character_count`
- `clothing_policy`
- `visibility_policy`
- `character_extension`
- `character_weight`

### 6.4 高级选项

以下规则支持展开高级选项：

| 规则 | 选项 |
| --- | --- |
| `character_section_filter` | `blocked_sections` |
| `clothing_policy` | `mode: enforce/advisory` |
| `visibility_policy` | `mode: enforce/advisory` |
| `character_extension` | `trigger_mode`、`enabled_slots`、`include_declaration_materials`、`ignore_disabled_lines` |
| `character_weight` | `style`、`level`、`numeric_weight`、`existing_weight`、`missing_identity` |
| `tag_conflict` | 暂不在 Web 开放 `masks_file`，避免浏览器输入任意本地路径 |

高级选项只在规则状态为 `enabled` 时生效。规则为 `disabled` 或 `inherit` 时可以保留表单草稿，但请求不发送 options。

## 7. 请求数据流

```text
CustomWorkspaceState
  -> buildComposeRenderRequest
  -> POST /api/compose-preview
  -> GenerationJsonApi.compose
  -> ScriptComposer
  -> PromptPolicyProvider(project config)
  -> PromptPolicyPipeline
  -> NovelAIRenderAdapter
  -> RenderRequest
```

请求结构：

```json
{
  "compose": {
    "nodes": [],
    "negative": "",
    "identity_minimal_sections": ["character", "role"],
    "prompt_policy": {
      "rules": {
        "visibility_policy": {
          "enabled": false
        }
      }
    }
  },
  "render": {
    "backend": "novelai",
    "width": 1024,
    "height": 1024,
    "params": {
      "n_samples": 1,
      "character_prompts": {
        "mode": "auto",
        "add_male_caption": true
      }
    }
  }
}
```

Preview 与 Generate 使用同一个 Request Builder，禁止出现预览和真实生成参数不一致。

## 8. UI 结构

Custom 页参数区域拆为：

```text
生图参数
  Width / Height / NT / Seed

提示词行为
  Identity Minimal Sections
  Character Prompts
  Policy Rules
```

Policy Rules 默认折叠，只显示规则名称和三态控件。只有支持 options 的规则提供二级展开入口。

界面不显示 Policy 模板名选择器，但 Preview 可以在只读摘要中展示后端返回的 effective template，便于确认当前继承的是 `legacy_compat`。

## 9. 错误处理

- Identity 覆盖为空：前端阻止请求并显示“至少选择一个 identity section”。
- 未知 Policy 规则：后端返回 `400 compose_preview_failed`，前端显示 API 错误。
- 非法 Policy option：Pydantic 或规则 options 校验失败，前端显示具体字段错误。
- Character Prompts 用于不支持的模型：不阻止生成，Renderer 在 `RenderRequest.meta.character_prompts` 中记录 `unsupported_model`。
- 没有角色节点：不阻止生成，Renderer 记录 `no_characters`。

## 10. 验收标准

### 10.1 Identity

- 继承模式不发送 `identity_minimal_sections`。
- 覆盖模式把非空 section 数组传到 ScriptComposer。
- 多角色节点的 section 候选正确合并。
- 删除到最后一个 section 时 UI 阻止操作。
- Preview 的 `included_character_sections` 与覆盖结果一致。

### 10.2 Character Prompts

- `auto` 生成 `render_request.params.characterPrompts` 或对应的 v4 char captions。
- `add_male_caption` 能进入 Renderer 配置。
- `off` 不执行 Character Prompts 拆分。
- 不支持模型和无角色节点时显示可理解的状态，而不是静默失败。

### 10.3 Policy

- 所有规则为 `inherit` 时，使用项目 `legacy_compat` 基线。
- 关闭一条规则只影响该规则。
- 开启一条规则并修改 options 后，Preview 的 Policy trace 体现变化。
- 请求不包含 Policy `require`。
- AgentComposer 不经过 Script Policy 链路。

### 10.4 工作区与 Compare

- 刷新页面后新配置可以恢复。
- 旧工作区数据可以自动迁移到新默认结构。
- 普通 Generate 与 Preview 使用相同配置。
- Compare Matrix 同一轮所有组合共享相同 Policy、Identity、Character Prompts 和非画师参数。

## 11. 非目标

本期不处理：

- Policy 模板切换
- 自定义 Policy 文件路径
- 新建或删除 Policy 规则
- AgentComposer Policy
- 手工 Character Prompt 编辑器
- Character Prompt 空间坐标编辑
- NovelAI Reference/Vibe 参数编辑
- Batch Studio 全量参数表单化
