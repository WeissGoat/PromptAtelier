# Action Selected Keys Spec 2026-06-26

## 定位

`selected_keys` 是 ScriptComposer 的角色字段选择规则，用来表达“当前 action 需要从每个 character 节点取哪些 tags section”。

它只影响 ScriptComposer，不影响 AgentComposer。

## action_profile.yaml

正式入口：

```yaml
schema: tags-machine.action-profile/v1

character_selection:
  source: action_profile.yaml
  default_selected_keys:
    - character
    - copyright
  characters:
    - selected_keys:
        - character
        - copyright
        - hair
    - selected_keys:
        - character
        - copyright
        - feet
```

字段含义：

- `character_selection.default_selected_keys`：未给某个角色单独声明时使用的 character tags section。
- `character_selection.characters[].selected_keys`：按角色 index 指定要取的 character tags section。
- `source`：由读取器写入或显式声明，用于调试和验收。

## run-prompt-prompt.md 兼容

短期兼容读取 `run-prompt-prompt.md` 的 YAML front matter：

```yaml
---
characters:
  - selected_keys:
      - character
      - copyright
      - hair
---
```

该兼容入口只读取 `characters[].selected_keys`，正文不参与拼接规则。

## 优先级

ScriptComposer 的 character section 选择优先级：

```text
characters[index].selected_keys
> default_selected_keys
> character_scope policy
> default all character tags
```

`character_scope` 保留为兼容字段，不继续作为新规则扩展入口。

## PromptBundle 记录

ScriptComposer 会继续在 `PromptBundle.meta.composition` 里记录：

- `character_scope`
- `included_character_sections`
- `suppressed_character_sections`

同时在 `PromptBundle.meta.extra` 里记录：

- `character_selection`
- `character_materials[].selected_keys`
- `character_materials[].used_sections`
- `character_materials[].suppressed_sections`

这些字段用于调试、验收、PNG 参数追踪和后续 character captions 处理。

## AgentComposer

AgentComposer 不经过 selected_keys 过滤规则。

原因：

- 当前 AgentComposer 链路已经稳定。
- AgentComposer 的输入、cache key、外部 agent 结果不应被 ScriptComposer 的字段过滤规则影响。
- 如果未来希望 agent 参考 selected_keys，应单独设计 agent task material，而不是复用 ScriptComposer 的执行逻辑。
