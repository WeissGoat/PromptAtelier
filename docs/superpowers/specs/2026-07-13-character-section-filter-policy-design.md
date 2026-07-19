# Character Section Filter Policy 设计

## 目标

新增 `character_section_filter` Prompt Policy，默认屏蔽 character 节点的
`copyright` section。规则只影响 ScriptComposer 产出的 PromptBundle，
AgentComposer 继续绕过 PromptPolicyPipeline。

## 配置

```yaml
rules:
  character_section_filter:
    enabled: true
    options:
      blocked_sections:
        - copyright
```

默认模板启用该规则。下层配置可以替换 `blocked_sections`，也可以显式关闭规则。

## 处理方式

规则运行在 `compose_selection` 阶段，位于 `character_extension` 之后、
`clothing_policy` 之前。

规则结合 `resolved_nodes.characters()` 和
`PromptBundle.meta.extra.character_materials` 判断每个角色实际使用的 section，
只删除被屏蔽 section 贡献的 token 次数。它不使用全局 token 黑名单，因此不会
误删 action、background 或其他来源中的同名 token。

## 元数据同步

过滤后同步更新：

- `PromptBundle.meta.composition.included_character_sections`
- `PromptBundle.meta.composition.suppressed_character_sections`
- `character_materials[].used_sections`
- `character_materials[].suppressed_sections`
- `character_materials[].positive_tags`
- `character_materials[].blocked_sections`

`selected_keys` 保留 action 原始请求，不改写，以便区分“请求选择”和“最终生效”。

## NovelAI

NovelAI Renderer 使用 `character_materials[].positive_tags` 构造 Character
Prompts。规则必须在同步元数据时移除被屏蔽 section 的 tags，避免 copyright 从
base prompt 删除后又进入 character captions。

## 验收

1. 默认 Policy 从 character 贡献中删除 `copyright`。
2. action 中同名 token 不被误删。
3. 多角色分别按各自 material 更新。
4. Policy Trace 记录 section、token 和删除原因。
5. 显式关闭规则后恢复原行为。
6. AgentComposer 链路不受影响。
7. Blackboard Mock Batch 的 base prompt 和 NovelAI character captions 均不含
   character `copyright` token。

