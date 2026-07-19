# PromptPolicy 配置与使用

## 1. 定位

`PromptPolicyPipeline` 位于 Composer 之后、Renderer 之前，用于执行可配置的通用提示词规则：

```text
节点读取
  -> ScriptComposer / FullPrompt
  -> PromptPolicyProvider
  -> PromptPolicyPipeline
  -> Renderer
  -> RenderRequest
```

AgentComposer 默认绕过 PromptPolicyPipeline，不受本配置影响。

## 2. 默认行为

调用方不传 `prompt_policy` 时，`GenerationService` 自动使用内置 `default` 模板：

```python
service = GenerationService()
bundle = service.compose_resolved_nodes(resolved_nodes)
```

当前内置模板继承关系：

```text
off
  -> balanced
  -> legacy_compat
  -> default
```

默认启用：

- `tag_normalize`
- `character_extension`
- `character_section_filter`（默认屏蔽 character `copyright` section）
- `clothing_policy`
- `visibility_policy`
- `dedupe`
- `tag_conflict`
- `character_count`

`character_weight` 与其他默认 Policy 一起启用。

## 3. 内置模板

模板位于：

```text
src/tags_machine_core/policies/templates/
```

当前提供：

| 模板 | 用途 |
| --- | --- |
| `off` | 关闭整个 PolicyPipeline |
| `normalize_only` | 只做标准化和去重 |
| `balanced` | 通用规则集合 |
| `strict` | 当前继承 balanced，保留后续严格参数扩展位置 |
| `legacy_compat` | balanced 加角色扩展规则 |
| `default` | 系统默认模板 |

## 4. 项目级配置

应用配置可以声明项目模板目录和项目默认 Policy：

```yaml
prompt_policy_template_root: configs/prompt_policies

prompt_policy:
  require: default
```

`prompt_policy_template_root` 相对配置文件所在目录解析。

项目默认配置也可以覆盖内置模板：

```yaml
prompt_policy:
  require: default
  rules:
    visibility_policy:
      enabled: false
```

## 5. 自定义模板

例如创建：

```text
configs/prompt_policies/character_weight.yaml
```

内容：

```yaml
schema: tags-machine-core.prompt-policy-template/v1
name: character_weight
require: default

rules:
  character_weight:
    enabled: true
    options:
      style: numeric
      level: 2
      numeric_weight: 2.0
      existing_weight: replace
      missing_identity: ignore
    order:
      after:
        - dedupe
```

项目内示例位于：

```text
examples/prompt_policies/character_weight.yaml
```

## 6. Batch 使用

Batch 在 `defaults.prompt_policy` 中 require 模板：

```yaml
defaults:
  backend: novelai
  composer: script
  artist: 20260412
  model: nai-diffusion-4-5-full
  character_prompts: auto

  prompt_policy:
    require: ../prompt_policies/character_weight.yaml
```

相对路径以 Batch YAML 所在目录为基准。

如果配置了 `prompt_policy_template_root`，也可以使用模板名称：

```yaml
defaults:
  prompt_policy:
    require: character_weight
```

完整示例：

- `examples/batches/character_weight_mock.yaml`
- `examples/batches/character_weight_real.yaml`

ScriptComposer 的最小角色 section 也可以在 Batch 中覆盖：

```yaml
defaults:
  composer: script
  identity_minimal_sections:
    - character
    - copyright
    - role
```

优先级：

```text
Batch identity_minimal_sections
  > character meta.yaml identity_minimal
  > 内置默认 [character, role]
```

该字段只影响 ScriptComposer，不影响 AgentComposer，也不属于 NovelAI Renderer 参数。

运行 mock 参数验收：

```powershell
uv run python -m tags_machine_core run-batch `
  examples\batches\character_weight_mock.yaml `
  --fresh `
  --log-level info `
  --full
```

运行单图真实验收：

```powershell
uv run python -m tags_machine_core run-batch `
  examples\batches\character_weight_real.yaml `
  --fresh `
  --log-level info `
  --full
```

## 7. 局部覆盖

传入 Policy 配置时，不会整份替换默认模板，而是递归覆盖明确配置的字段：

```yaml
prompt_policy:
  rules:
    character_weight:
      enabled: true
      options:
        level: 3
```

最终结果：

- 其他默认规则保持不变；
- `character_weight` 被开启；
- 角色身份使用三层 braces。

关闭某条默认规则：

```yaml
prompt_policy:
  rules:
    visibility_policy:
      enabled: false
```

关闭整个 Pipeline：

```yaml
prompt_policy:
  enabled: false
```

完全不继承默认规则：

```yaml
prompt_policy:
  require: off
  enabled: true
  rules:
    character_weight:
      enabled: true
```

## 8. 调整执行顺序

不配置顺序时，使用代码 Registry 中的默认顺序。

使用 `before/after` 做局部调整：

```yaml
prompt_policy:
  rules:
    clothing_policy:
      order:
        after:
          - visibility_policy
```

规则：

- 未涉及的 Policy 保持代码默认顺序；
- 同一 phase 内支持重新排序；
- 不允许逆转固定 phase 顺序；
- 未知规则、循环依赖会在 Batch 规划或生成前报错。

固定 phase：

```text
normalize_input
compose_selection
post_compose_cleanup
bundle_finalize
```

## 9. CharacterWeightPolicy

默认效果：

```text
akemi_homura
  -> 2.0::akemi_homura::
```

角色身份来源：

1. character node 中 `prompt.positive[].role: character`；
2. `tags.character`；
3. `character_id`。

不会默认给以下特征提权：

```text
black_hair
purple_eyes
school_uniform
mahou_shoujo_madoka_magica
```

配置字段：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `style` | `numeric` | `braces` 或 `numeric` |
| `level` | `2` | braces 最终层数 |
| `numeric_weight` | `2.0` | numeric 权重值 |
| `existing_weight` | `replace` | `replace`、`keep`、`increase` |
| `missing_identity` | `ignore` | 找不到角色身份时忽略或报错 |
| `identities` | `[]` | 没有 character node 时显式指定身份 |

## 10. NovelAI Character Prompts

NovelAI v4 使用 `character_prompts: auto` 时，Renderer 会忽略权重进行匹配、保留权重进行输出。

输入：

```text
2.0::akemi_homura::, black_hair, standing
```

输出参数：

```yaml
v4_prompt:
  caption:
    base_caption: standing
    char_captions:
      - char_caption: girl, 2.0::akemi_homura::, black_hair
```

多角色示例：

```yaml
characterPrompts:
  - prompt: girl, 2.0::akemi_homura::, black_hair, purple_eyes
  - prompt: girl, 2.0::kaname_madoka::, pink_hair, pink_eyes
```

共享特征会先匹配给所有相关角色，所有角色匹配完成后再从 base prompt 删除。

## 11. Python 调用

使用默认 Policy：

```python
service = GenerationService()
bundle = service.compose_resolved_nodes(resolved_nodes)
```

局部覆盖：

```python
bundle = service.compose_resolved_nodes(
    resolved_nodes,
    prompt_policy={
        "rules": {
            "character_weight": {
                "enabled": True,
                "options": {
                    "level": 2,
                },
            }
        }
    },
)
```

使用指定模板：

```python
bundle = service.compose_resolved_nodes(
    resolved_nodes,
    prompt_policy={
        "require": "character_weight",
    },
)
```

自定义模板目录时，通过项目配置构造 Provider，再注入 `GenerationService`。

## 12. 输出与排查

`PromptBundle.meta.extra.policy` 会记录：

```yaml
template: off -> balanced -> legacy_compat -> default -> character_weight
template_hash: sha256:...
default_rule_order: []
effective_rule_order: []
order_overrides: {}
```

`PromptBundle.meta.extra.policy_trace` 记录每次增删、替换和权重变化：

```yaml
rule: character_weight@v1
action: replace_weight
token: akemi_homura
from: akemi_homura
to: "2.0::akemi_homura::"
reason: "matched character identity: akemi_homura"
```

最终 effective 配置、规则版本和执行顺序进入 cache key。模板路径和模板 hash 只用于追踪，不单独制造缓存差异。

## 13. CharacterSectionFilterPolicy

`character_section_filter` 根据 character section 的来源删除角色贡献的提示词，默认屏蔽：

```yaml
blocked_sections:
  - copyright
```

即使 action 的 `selected_keys` 或 character 的 `identity_minimal` 选择了 `copyright`，最终 ScriptComposer 结果也不会保留该 section。规则会同步更新 `character_materials`，因此 NovelAI Character Prompts 不会再次加入被屏蔽内容。

Batch 局部替换屏蔽列表：

```yaml
prompt_policy:
  rules:
    character_section_filter:
      options:
        blocked_sections:
          - copyright
          - role
```

关闭规则：

```yaml
prompt_policy:
  rules:
    character_section_filter:
      enabled: false
```

`selected_keys` 继续记录 action 请求的原始 section；最终结果记录在 `used_sections`、`suppressed_sections` 和 `blocked_sections` 中。AgentComposer 不经过该规则。
