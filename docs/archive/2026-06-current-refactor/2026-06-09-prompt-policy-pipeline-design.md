# PromptPolicyPipeline 设计规格

## 1. 背景

旧 `tags_machine` 的 `formula.py` 里沉淀了不少有价值的提示词规则，例如衣着判断、鞋袜冲突过滤、局部镜头过滤、人数标签前置等。但这些规则混在大量旧 formula 分支里，直接复刻会把新 `tags_machine_core` 重新拖回硬编码结构。

本规格定义一个新的 `PromptPolicyPipeline`，用于承载可开关、可追踪、可扩展的提示词规则。该能力只在 `refactor` 子模块开发，不修改父项目 `tags_machine`，也不影响当前稳定的 `AgentComposer` 链路。

## 2. 目标

- 把旧 formula 中通用、有业务价值的规则抽象为独立规则。
- 每条规则支持开启、关闭、版本记录和 trace 输出。
- 规则可以按 profile 组合，便于未来在不同入口中渐进启用。
- 规则处理前先做 tag canonical 归一化，让空格分隔和下划线分隔在规则匹配时等价。
- `AgentComposer` 默认完全绕过规则管线，保持现有 cache 和出图链路稳定。
- 第一阶段优先服务 `ScriptComposer` / `run-action` / 显式 opt-in 的完整 prompt，不默认改写 `run-prompt --composer agent` 输出。

硬性约束摘要：

- AgentComposer 默认不经过 PromptPolicyPipeline。
- PromptPolicyPipeline 不生成后端专属字段。
- 规则开关必须同时支持 enabled_rules 和 disabled_rules。
- 当 policy 未启用时，AgentComposer cache key 和 PromptBundle 输出必须保持现状。
- 空格分隔和下划线分隔必须在规则匹配中等价。

## 3. 非目标

- 不在本阶段重写 `AgentComposer`。
- 不在本阶段修改父项目 `prompt_preset_service.py`。
- 不把规则写进每个 character/action YAML，避免节点元数据重复。
- 不复刻旧 `formula.py` 的全部 DSL 和 topic 分支。
- 不把 NovelAI 的 quality、negative、vibe、reference、character_prompts 参数下沉到 PromptBundle。
- 不要求新 composer 输出和旧 `run_action` 逐字一致。

## 4. 现有边界

当前主链路边界是：

```text
NodeDocument / full prompt
-> ScriptComposer 或 AgentComposer
-> PromptBundle
-> Renderer / Adapter
-> RenderRequest
-> GenerationResult
```

`PromptBundle` 是提示词生成层和生图业务层的边界。它保存完整 positive / negative prompt、节点引用、composer 类型、composition 元数据和 cache 信息。

`Renderer` 可以消费 `PromptBundle` 和 `ResolvedNodeSet`，负责 NovelAI / ComfyUI / SD 等后端适配。NovelAI 的画风拼接、quality、negative、gen_json、reference/vibe、V4 character prompts 仍属于 Renderer 责任。

## 5. 新增位置

`PromptPolicyPipeline` 位于 composer 输出 `PromptBundle` 之后、返回给调用方之前。

硬性边界：AgentComposer 默认不经过 PromptPolicyPipeline；PromptPolicyPipeline 不生成后端专属字段。

推荐结构：

```text
src/tags_machine_core/policies/
  __init__.py
  config.py
  context.py
  pipeline.py
  tokens.py
  rules/
    tag_normalize.py
    dedupe.py
    tag_conflict.py
    character_count.py
    clothing.py
    visibility.py
```

接入顺序：

```text
ScriptComposer.compose_nodes()
-> PromptBundle
-> PromptPolicyPipeline.apply(bundle, context)
-> PromptBundle
```

`AgentComposer` 默认不接入。未来如需启用，只能通过显式参数或 profile opt-in。

## 6. 规则阶段

规则按阶段执行，避免不同规则互相抢职责。

### 6.1 normalize_input

处理 prompt token 的归一化和 canonical 表达。

第一版包含：

- `tag_normalize`
- 权重语法保留
- 空格和下划线等价匹配

### 6.2 compose_selection

处理角色素材选择和局部镜头裁剪。

第一版可以只消费已有 `PromptBundle.meta.composition` 和 character materials，不主动重新读取文件。

第一版包含：

- `clothing_policy`
- `visibility_policy`

### 6.3 post_compose_cleanup

处理完整 prompt 的冲突消解和稳定化。

第一版包含：

- `tag_conflict`
- `character_count`
- `dedupe`

### 6.4 trace_finalize

写入规则执行结果。

输出：

- 启用的 profile
- 启用和禁用的规则
- 每条规则版本
- 每条规则的变更 trace
- 是否实际改写 prompt

## 7. 规则接口

```python
class PromptRule:
    id: str
    version: str
    phase: RulePhase
    default_enabled: bool

    def apply(self, context: PromptRuleContext) -> PromptRuleResult:
        ...
```

`PromptRuleContext`：

```python
class PromptRuleContext:
    bundle: PromptBundle
    resolved_nodes: ResolvedNodeSet | None
    profile: PromptPolicyProfile
    positive_tokens: list[PromptToken]
    negative_tokens: list[PromptToken]
    trace: list[PromptPolicyTraceEntry]
```

`PromptRuleResult`：

```python
class PromptRuleResult:
    positive_tokens: list[PromptToken] | None
    negative_tokens: list[PromptToken] | None
    trace: list[PromptPolicyTraceEntry]
```

规则必须是确定性的。同一输入、同一配置、同一规则版本应输出同一 PromptBundle。

## 8. Token 归一化

规则匹配统一使用 canonical token。canonical 的目标是让下面两种写法等价：

```text
high heels
high_heels

from back
from_back

bare feet
bare_feet
```

### 8.1 PromptToken

```python
class PromptToken:
    raw: str
    body: str
    canonical: str
    weight_prefix: str
    weight_suffix: str
    separator: str = ","
```

示例：

```text
{{high heels}}
```

解析为：

```json
{
  "raw": "{{high heels}}",
  "body": "high heels",
  "canonical": "high_heels",
  "weight_prefix": "{{",
  "weight_suffix": "}}"
}
```

示例：

```text
2.0::akemi homura::
```

解析为：

```json
{
  "raw": "2.0::akemi homura::",
  "body": "akemi homura",
  "canonical": "akemi_homura",
  "weight_prefix": "2.0::",
  "weight_suffix": "::"
}
```

### 8.2 输出模式

归一化匹配和最终输出分开配置：

```yaml
prompt_policy:
  normalization:
    match_canonical: underscore
    output_style: underscore
```

`output_style` 可选：

- `underscore`：输出下划线，默认推荐。
- `preserve`：规则匹配用 canonical，但输出保留原文。

第一版默认使用 `underscore`。如果后续发现某些 artist tag 的空格写法效果更好，可对 artist 节点或 renderer 输入加局部 preserve 策略。

## 9. 配置和开关

全局配置示例：

```yaml
prompt_policy:
  enabled: false
  profile: off
  normalization:
    match_canonical: underscore
    output_style: underscore
  rules:
    tag_normalize: true
    dedupe: true
    tag_conflict: true
    character_count: true
    clothing_policy: true
    visibility_policy: true
```

默认值必须保护现有链路：

```yaml
prompt_policy:
  enabled: false
  profile: off
```

入口可以显式启用：

```json
{
  "prompt_policy": {
    "enabled": true,
    "profile": "balanced",
    "disabled_rules": ["visibility_policy"]
  }
}
```

## 10. Profile

### 10.1 off

完全不运行规则。默认 profile。

用途：

- 保护现有 AgentComposer。
- 排查规则是否导致出图变化。
- 兼容完整 prompt 原样出图。

### 10.2 normalize_only

只运行：

- `tag_normalize`
- `dedupe`

用途：

- 低风险稳定化。
- 检查空格/下划线归一化效果。

### 10.3 balanced

运行：

- `tag_normalize`
- `dedupe`
- `tag_conflict`
- `character_count`
- `clothing_policy`
- `visibility_policy`

用途：

- ScriptComposer / run-action 默认候选 profile。
- 修复脚部特写、鞋袜冲突、衣着冲突等常见问题。

### 10.4 strict

在 `balanced` 基础上更强执行局部镜头过滤。

用途：

- 批量修复明确局部镜头动作。
- 例如 `foot_detail` 强制过滤 `eyes`、`hair`、`upper_clothes`。

## 11. 第一批规则

### 11.1 tag_normalize

职责：

- 解析 prompt token。
- 生成 canonical。
- 按配置输出下划线或保留原文。
- 保留 `{}`、`[]`、`2.0::tag::` 等权重语法。

不负责：

- 判断哪些 token 应该删除。
- 判断衣着和局部镜头。

### 11.2 dedupe

职责：

- 删除 canonical 完全相同的重复 token。
- 保留第一次出现的位置和权重形式。

例：

```text
bare_feet, bare feet
```

归一化后只保留一个 `bare_feet`。

### 11.3 tag_conflict

职责：

- 根据冲突规则删除互斥 token。
- 第一版优先复用旧 `design/masks.txt` 语义。

示例：

```text
barefoot -> remove high_heels, socks, pantyhose, boots, legwear
bare_feet -> remove high_heels, socks, pantyhose, boots, legwear
bare_leg -> remove high_heels, socks, pantyhose, boots, legwear
```

配置来源：

- 第一版可以提供内置默认规则。
- 后续可支持从 `legacy.design_root/masks.txt` 加载。

### 11.4 character_count

职责：

- 根据 action prompt 和角色节点数量整理人数标签。
- 如果没有人数标签且只有一个 female character，补 `1girl`。
- 多角色时根据角色节点数量和已有 prompt 保守补充。
- 将人数标签前置。

不负责：

- 强行改变 agent 已明确写好的复杂人数关系。
- 从图片内容推断性别。

### 11.5 clothing_policy

职责：

- 根据 action prompt、action `character_scope`、可选 `classify.yaml` / node metadata 推断是否使用角色 outfit。
- 处理 `nude` / `naked` / `clothed` / `alternative_clothing` 等状态。
- 对 `foot_detail`、`lower_body` 等局部镜头减少默认服装污染。

第一版推荐行为：

```text
default scope:
  保留角色 outfit

nude / naked:
  移除角色 outfit

st_clothes / clothing_control:
  移除默认 outfit，追加 alternative_clothing

foot_detail:
  移除 upper_clothes，保留 feet / legwear
```

### 11.6 visibility_policy

职责：

- 根据镜头和可见性删除不应出现的角色细节。

第一版规则：

```text
from_back / facing_away:
  remove eyes, pupils, eye_color

head_out_of_frame:
  remove eyes, face, hair_detail

foot_detail / lower_body:
  remove eyes, face, hair_detail, upper_clothes
```

在 AgentComposer 链路中默认不执行。未来如果显式启用，可以先用 advisory 模式只记录 trace，不改写 prompt。

## 12. AgentComposer 保护策略

这是本规格的硬约束：

```text
AgentComposer 默认不经过 PromptPolicyPipeline。
```

具体要求：

- `AgentComposer.compose_from_result()` 当前输出保持不变。
- agent cache key 默认不加入 policy 字段。
- `run-prompt --composer agent` 默认不改写 agent 输出 prompt。
- 如果未来显式启用 policy，必须修改 cache key，并在 PromptBundle meta 中写入 policy 信息。
- 显式启用前，现有 agent cache 文件继续可读可用。

未来 opt-in 形式示例：

```json
{
  "composer": "agent",
  "prompt_policy": {
    "enabled": true,
    "profile": "normalize_only"
  }
}
```

## 13. ScriptComposer 接入策略

`ScriptComposer` 是第一阶段推荐接入口。

接入方式：

```python
bundle = ScriptComposer().compose_nodes(...)
bundle = PromptPolicyPipeline(config).apply(bundle, resolved_nodes=resolved_nodes)
```

`compose_full_prompt()` 默认也不启用规则，除非显式传入 policy config。完整 prompt 通常被用户或 agent 视为已经完成的结果，不应默认改写。

## 14. PromptBundle 元数据

`PromptBundle.meta.extra` 中新增 `prompt_policy`，避免扩展正式顶层字段造成契约震荡。

示例：

```json
{
  "meta": {
    "extra": {
      "prompt_policy": {
        "enabled": true,
        "profile": "balanced",
        "normalization": {
          "match_canonical": "underscore",
          "output_style": "underscore"
        },
        "rules": [
          {
            "id": "tag_normalize",
            "version": "v1",
            "enabled": true
          },
          {
            "id": "tag_conflict",
            "version": "v1",
            "enabled": true
          }
        ],
        "trace": [
          {
            "rule": "tag_normalize",
            "action": "replace",
            "from": "high heels",
            "to": "high_heels"
          },
          {
            "rule": "tag_conflict",
            "action": "remove",
            "token": "high_heels",
            "reason": "barefoot conflicts with footwear"
          }
        ]
      }
    }
  }
}
```

如果 profile 为 `off`，可以不写 `prompt_policy`，或只写：

```json
{
  "enabled": false,
  "profile": "off"
}
```

## 15. Cache 规则

当 policy 未启用时：

- 现有 cache key 规则保持不变。
- AgentComposer 不受影响。

当 policy 显式启用时，cache key 必须包含：

- `prompt_policy.enabled`
- `prompt_policy.profile`
- enabled rule ids
- disabled rule ids
- rule versions
- normalization output style

不进入 cache key：

- trace 内容
- 输出路径
- 运行耗时

## 16. 与 Renderer 的关系

PromptPolicyPipeline 不生成后端专属字段。

仍由 NovelAI Renderer 负责：

- artist prompt_prefix / prompt_suffix
- model / sampler / steps / scale / seed / size
- quality prompt
- default negative prompt
- after_negative_prompt
- gen_json / gen_param
- reference / vibe
- NAI4+ character_prompts / char_captions
- PNG info

规则管线只修改或记录 PromptBundle 的 prompt 语义，不直接写 `RenderRequest.params`。

## 17. 验收标准

### 17.1 稳定链路

- 在不显式启用 policy 时，AgentComposer 输出的 PromptBundle 与当前行为一致。
- 在不显式启用 policy 时，AgentComposer cache key 与当前行为一致。
- 在不显式启用 policy 时，run-prompt agent 链路不新增规则 trace，不改写 prompt。

### 17.2 规则开关

- `profile=off` 时不改写 positive / negative prompt。
- 单独关闭某条规则时，该规则不产生 trace，也不影响输出。
- 同一输入、同一 profile、同一规则版本输出稳定。

### 17.3 tag normalize

- `high heels` 和 `high_heels` 在规则匹配中等价。
- 权重语法保留，例如 `{{high heels}}` 输出为 `{{high_heels}}`。
- `2.0::akemi homura::` 输出为 `2.0::akemi_homura::`。

### 17.4 冲突规则

- `barefoot, high heels` 在 `tag_conflict` 开启后移除 `high_heels`。
- `bare_feet, socks` 在 `tag_conflict` 开启后移除 `socks`。

### 17.5 局部镜头规则

- `foot_detail` 在 strict profile 下抑制 `eyes`、`face`、`hair_detail`、`upper_clothes`。
- `from_back` 在 strict profile 下抑制 `eyes` / `pupils`。
- AgentComposer 默认不执行这些抑制。

## 18. 第一阶段实施计划

1. 新增 policy 数据模型和配置模型。
2. 新增 token parser / serializer。
3. 实现 `tag_normalize` 和 `dedupe`。
4. 实现 `tag_conflict`，先内置旧 `masks.txt` 中最核心的鞋袜冲突规则。
5. 实现 policy trace 写入 `PromptBundle.meta.extra.prompt_policy`。
6. 在 ScriptComposer 显式 opt-in 路径接入 pipeline。
7. 保持 AgentComposer 默认不接入，并补回归验证。
8. 后续再实现 `character_count`、`clothing_policy`、`visibility_policy`。

## 19. 风险和约束

- 规则会改变 prompt，因此默认必须关闭。
- 下划线输出可能影响少量 artist alias，需要保留 `preserve` 输出模式。
- clothing / visibility 规则如果过强，可能压掉 agent 的语义表达，所以 AgentComposer 默认不接入。
- 旧 `formula.py` 的 DSL 很灵活，但不应直接复刻，否则会破坏新架构边界。
- `PromptBundle.meta.extra.prompt_policy.trace` 可能变长，后续可限制 trace 数量或提供 summary。

## 20. 推荐结论

第一阶段只在 `refactor` 内开发 `PromptPolicyPipeline` 基础设施，并让 `ScriptComposer` 或显式 opt-in 的入口使用它。`AgentComposer` 继续保持现在的稳定行为。

这套设计让旧 formula 的有效经验逐步进入新架构，但不会把旧项目的硬编码和历史分支搬进来。
