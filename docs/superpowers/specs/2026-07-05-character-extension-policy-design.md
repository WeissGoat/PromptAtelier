# Character Extension Policy 设计方案

## 背景

旧版 `formula.py` 里的 `extend_character_in_the_end` 发生在角色、动作已经拼接之后，质量词和后续清理之前。它不是单纯把角色提示词追加到末尾，而是读取角色节点和动作节点的旧元数据，对已经组合好的 prompt 做二次修正。

新架构里，AgentComposer 和 full prompt 链路已经稳定，不能为了复刻旧 formula 规则影响这两条主链路。因此该能力应作为 ScriptComposer 的可选兼容规则接入 PromptPolicyPipeline，而不是写入 Renderer，也不直接塞进 ScriptComposer 主体。

## 目标

- 复刻旧版 `extend_character_in_the_end` 中稳定、通用、可解释的角色扩展行为。
- 默认只作用于 `script` composer 目标，不影响 `agent` 和 `full_prompt`。
- 直接兼容旧 `tags.txt` 里的 `type` 和 `=` 后 extension 信息，不要求先迁移 character meta.yaml。
- 每次修改 prompt 都写入 `PromptBundle.meta.extra.policy.trace`，方便排查真实出图差异。
- 支持按配置开启、关闭，并能在 batch 业务测试里验证真实 NovelAI 出图。

## 非目标

- 不复刻旧 formula 的全局状态，例如 `sys_dress_switch`、`CONST_STATE` 这类隐式状态。
- 不把通用规则写进每个 character 的 YAML。
- 不在 NovelAI Renderer 里实现该逻辑。Renderer 只负责把 PromptBundle 转成后端请求。
- 不默认影响 AgentComposer。若未来需要 agent prompt 也走该规则，必须单独设计并显式开启。
- 不追求和旧 formula 每一个历史 hardcode 完全一致。第一版只复刻可稳定解释的规则。

## 推荐接入方式

新增 PromptPolicyPipeline 规则：

```text
CharacterExtensionPolicyRule
id: character_extension
version: v1
phase: compose_selection
default_enabled: false
```

建议执行顺序：

```text
ScriptComposer
-> PromptBundle
-> PromptPolicyPipeline
   -> tag_normalize
   -> character_extension
   -> dedupe
   -> tag_conflict
   -> character_count
   -> clothing
   -> visibility
-> Renderer
-> NovelAI
```

`character_extension` 放在 `tag_conflict` 之前，原因是它可能补充鞋袜、衣服、武器等 tag，后续仍需要冲突规则处理 `barefoot` 与 `socks/high_heels/legwear` 等互斥关系。

## 输入与依赖

规则输入来自 `PromptRuleContext`：

- `context.positive_tokens`：当前正向 prompt token。
- `context.resolved_nodes`：已解析节点集合。
- `context.config`：PromptPolicy 配置。
- `context.target`：当前应用目标。

规则需要从 `resolved_nodes` 中读取：

- 所有 character 节点。
- 第一个 action 节点作为 primary action。
- 可选 artist 节点，仅用于 trace 和后续扩展，不作为第一版规则判断核心。

如果 `resolved_nodes` 为空、没有 character、没有 action，规则直接跳过并写 trace。

## 旧节点数据来源

第一版优先读取 NodeReader 已经保留的 legacy sections：

```python
node.legacy.raw_sections["type"]
node.legacy.raw_sections["extension"]
```

这些内容来自旧 `tags.txt`：

- `type...` 行进入 `type` section。
- `=` 开头或包含 legacy extension marker 的行进入 `extension` section。

这样可以直接复用旧提示词库，不需要改 character meta.yaml，也不会把通用规则写进 YAML。

## 规则行为

### Action Guard

如果 primary action 的 legacy `type` section 中包含：

```text
not_extend_tags
```

则整条规则跳过，等价于旧版 `action.check_can_extend_tags()` 返回 false。

跳过时写 trace：

```json
{
  "rule": "character_extension@v1",
  "action": "skip",
  "reason": "action has not_extend_tags"
}
```

### Replace

兼容旧格式：

```text
type replace|old_tag=new_tag|old_tag_2=new_tag_2
```

行为：

- 遍历当前 positive tokens。
- token canonical 与 `old_tag` canonical 完全一致时替换成 `new_tag`。
- 保留原 token 权重包装。
- 每次替换写 trace。

示例：

```text
type replace|school uniform=magical girl outfit
```

当前 prompt:

```text
akemi_homura, school_uniform, standing
```

输出：

```text
akemi_homura, magical_girl_outfit, standing
```

### Add

兼容旧格式：

```text
type add|trigger+extra_tag+extra_tag_2
```

行为：

- 如果当前 prompt 中存在 `trigger`，则追加后续 `extra_tag`。
- 已存在的 extra tag 不重复追加。
- 追加位置在当前 prompt token 列表末尾。
- 每个追加写 trace。

示例：

```text
type add|weapon+holding weapon+combat pose
```

当前 prompt:

```text
akemi_homura, weapon, standing
```

输出：

```text
akemi_homura, weapon, standing, holding_weapon, combat_pose
```

### Extension Type

第一版支持旧版中稳定的 extension 类型：

```text
leg_wear
barefoot
shoes
weapon
clothes
extend_func
```

格式：

```text
leg_wear, trigger_a|trigger_b, operation|...
```

行为：

- 第二段是触发词列表，用 `|` 分隔。
- 触发词以 `!` 开头时表示否定触发：如果 prompt 中存在该 tag，则本条 extension 不触发。
- `leg_wear` 自动补充旧版默认匹配词：`pantyhose`、`thighhighs`、`socks`、`sock`。
- 命中后执行后续 operation。

### Extend Func Operation

第一版支持以下 operation：

```text
exact_replace|old|new
fuzzy_replace|match|new
add_after|match|target
add_if_not_exist|target|match_a|match_b
```

语义：

- `exact_replace`：canonical 完全匹配时替换。
- `fuzzy_replace`：token canonical 包含 match canonical 时替换。
- `add_after`：命中 match 后，在命中 token 后插入 target。
- `add_if_not_exist`：target 不存在，且 match 列表也没有命中时追加 target。

所有 operation 都必须写 trace，包含原 token、新 token、触发原因。

### 默认 Extension

旧版默认内置：

```text
extend_func_breasts: extend_func, breast, exact_replace|breasts?|medium breasts
extend_func_bra: extend_func, bra, fuzzy_replace|bra|
extend_func_barefoot: extend_func, barefoot, add_after|bare leg|barefoot
```

第一版保留这些默认项，但通过配置允许关闭：

```yaml
rules:
  character_extension:
    enabled: true
    include_default_extensions: true
```

如果 character legacy extension 中显式覆盖同名默认项，则使用 character 自身定义。

## 配置

推荐 profile：

```yaml
prompt_policy:
  enabled: true
  profile: script_legacy_formula
  apply_to:
    script: true
    agent: false
    full_prompt: false
  rules:
    character_extension:
      enabled: true
      source: legacy_tags_txt
      include_default_extensions: true
      action_guard: true
```

字段含义：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `false` | 是否启用规则 |
| `source` | `legacy_tags_txt` | 第一版只支持读取旧 tags.txt legacy sections |
| `include_default_extensions` | `true` | 是否启用旧版默认 extension |
| `action_guard` | `true` | 是否尊重 action 的 `not_extend_tags` |

## PromptBundle 元数据

规则执行后，PromptPolicyPipeline 已经会更新 cache key。新增规则只需要在 trace 中记录修改，不新增 PromptBundle 顶层字段。

建议 trace 示例：

```json
{
  "rule": "character_extension@v1",
  "action": "replace",
  "from": "school_uniform",
  "to": "magical_girl_outfit",
  "reason": "character type replace",
  "mode": "exact"
}
```

追加示例：

```json
{
  "rule": "character_extension@v1",
  "action": "add",
  "token": "barefoot",
  "reason": "extend_func_barefoot matched bare_leg"
}
```

## 多角色行为

多角色时按角色节点顺序逐个应用：

```text
character[0] extension
-> character[1] extension
-> character[2] extension
```

每个角色只读取自己的 legacy sections。所有角色共享同一份 positive token 列表。

如果两个角色 extension 都命中同一个共享特征：

- 替换类操作按顺序执行。
- 追加类操作会去重。
- trace 中记录对应 character ref 和 character index。

## 与 AgentComposer 的关系

默认不影响 AgentComposer：

```yaml
apply_to:
  agent: false
```

原因：

- AgentComposer 由外部 agent 或 cache 给出完整 prompt。
- 当前 agent 链路已经稳定。
- 该规则依赖旧 formula 的节点扩展语义，直接作用 agent prompt 可能让 cache 结果不可预测。

未来如果需要 agent prompt 也应用规则，应新开设计，明确 cache key、外部 agent 任务描述和 policy trace 之间的关系。

## 与 full prompt 的关系

默认不影响 full prompt：

```yaml
apply_to:
  full_prompt: false
```

原因：

- full prompt 通常代表用户或 agent 已经拼好的完整提示词。
- run-prompt 当前是稳定主链路，不应被旧 formula 兼容规则改变。

## 与 NovelAI Character Prompts 的关系

执行顺序保持：

```text
ScriptComposer
-> character_extension policy
-> NovelAI Renderer
-> characterPrompts auto split
```

也就是说，角色扩展先改 PromptBundle 的 positive prompt，NovelAI Renderer 再根据最终 prompt 和 character nodes 尝试迁移角色特征到 `characterPrompts`。

这样 renderer 不需要知道旧 formula 规则，仍然保持“后端请求适配层”的职责。

## 错误处理

规则应尽量宽容读取旧格式：

- 格式无法解析的 legacy 行不抛异常，写 warning trace。
- 单条 operation 失败不影响整条 prompt，跳过该 operation。
- 配置非法时在 PromptPolicyConfig 或规则初始化阶段报错。

业务运行时不能因为某个旧 character 的扩展行写坏导致整批失败。

## 日志

Info 级别：

- 规则启用状态。
- 处理了多少 character。
- 产生了多少 replace/add/remove。

Trace 级别：

- 每条 legacy line 的解析结果。
- 每个 trigger 的命中结果。
- 每个 operation 的执行前后 token。

Warning 级别：

- 无法解析的 legacy 行。
- 缺少 action 或 character 导致规则跳过。

Error 级别：

- 配置非法或内部不可恢复错误。

## 验收标准

### 结构验收

- AgentComposer 链路不启用该规则。
- full prompt 链路默认不启用该规则。
- ScriptComposer 在启用 `character_extension` 后，PromptBundle positive prompt 出现预期替换和追加。
- PromptBundle cache key 在规则启用后发生变化。
- `PromptBundle.meta.extra.policy.trace` 能看到每条修改记录。

### 业务验收

必须真实跑 NovelAI 出图，优先级高于单元测试。

建议选一个稳定 artist，例如 `20260412` 或 `动画_电影感_nai4_改3`，设计三组 prompt：

1. `replace` case：角色 type 中定义替换，动作普通站姿。
2. `add` case：角色 type 中定义触发追加，动作中包含 trigger。
3. `extension` case：动作含 `bare leg`、`barefoot`、`pantyhose`、`shoes` 等触发词，观察鞋袜/赤脚相关 prompt 是否合理。

每组至少保存：

- policy off 生成图。
- policy on 生成图。
- 两边 `PromptBundle`。
- 两边 `RenderRequest`。
- 两边 PNG 参数。
- 视觉说明：角色身份、动作、镜头、鞋袜/衣服相关特征是否符合预期。

通过条件：

- policy on 的 PromptBundle trace 解释了所有新增或替换 tag。
- policy off/on 的差异集中在角色扩展相关 tag，不出现 unrelated prompt 变化。
- NovelAI 出图能正常完成。
- 人工视觉检查没有明显破坏角色身份和动作主体。

## 实现边界

建议新增文件：

```text
src/tags_machine_core/policies/rules/character_extension.py
```

建议修改文件：

```text
src/tags_machine_core/policies/rules/__init__.py
src/tags_machine_core/policies/config.py
tests/test_prompt_policy_character_extension.py
docs/prompt_policy_character_extension.md
```

不建议修改：

```text
src/tags_machine_core/composers/agent.py
src/tags_machine_core/renderers/novelai.py
prompt_preset_service.py
```

## 后续演进

第一版稳定后，可以考虑增加结构化 character meta 支持，但字段应表达“角色扩展素材”，而不是把规则写进角色节点。例如：

```yaml
composition:
  character_extensions:
    replace:
      school_uniform: magical_girl_outfit
    add:
      weapon:
        - holding_weapon
        - combat_pose
```

该结构只是角色素材声明，规则仍然由 PromptPolicyPipeline 统一解释。

