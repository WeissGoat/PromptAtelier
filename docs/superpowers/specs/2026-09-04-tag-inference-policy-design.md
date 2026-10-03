# Tag Inference Policy 设计规范

## 1. 文档信息

- 日期：2026-09-04
- 状态：已确认，待实现
- 适用范围：`tags_machine/refactor`
- 目标：当提示词包含 `barefoot` 等裸足标签时，自动补充 `bare_legs`。

## 2. 背景

当前 `tag_conflict` 负责根据触发标签删除互斥标签，例如裸足出现时删除鞋袜。现在还需要支持另一类相反的提示词处理：根据已有标签推导出语义相关的标签。

第一条规则为：

```text
barefoot -> bare_legs
```

该行为不依赖 character 节点，也不属于角色扩展。它处理的是最终 Prompt 中的通用标签语义，因此应作为独立的 Prompt Policy。

## 3. 目标

### 3.1 必须支持

- 新增 `tag_inference` Prompt Policy；
- 内置裸足推导规则：`barefoot`、`bare_feet`、`bare_foot`、`barefeet` 触发 `bare_legs`；
- 目标标签已存在时不重复添加；
- 触发词带有 `{{}}`、`[]` 或数字权重时仍可识别；
- 采用现有 `canonicalize_tag()` 处理空格、连字符和下划线；
- 自动添加的标签默认不带权重；
- 每次推导写入 Policy trace；
- 可通过 Policy 的 `enabled` 和 `apply_to` 控制启用范围；
- 支持通过配置增加通用的额外推导规则；
- 不修改 negative prompt；
- 不影响 AgentComposer，除非未来显式开启对应 target。

### 3.2 明确不做

- 不把规则加入 `tag_conflict`；
- 不读取 character/action 节点；
- 不实现基于自然语言的模糊推理；
- 不使用子串匹配触发，例如 `barefoot_pose` 不自动视为 `barefoot`；
- 不自动合并或覆盖目标标签已有的权重；
- 不在第一版引入规则脚本执行、表达式求值或外部 Python 插件。

## 4. Policy 定义

新增规则类：

```text
class TagInferenceRule
  id = "tag_inference"
  version = "v1"
  scope = "prompt"
  phase = "post_compose_cleanup"
  default_enabled = false
```

源码位置：

```text
src/tags_machine_core/policies/rules/tag_inference.py
```

加入 `DEFAULT_RULES`，默认注册但不依靠类级别默认值隐式启用。模板决定实际是否启用。

## 5. 内置规则

### 5.1 裸足推导

```yaml
id: barefoot_to_bare_legs
when_any:
  - barefoot
  - bare_feet
  - bare_foot
  - barefeet
add:
  - bare_legs
```

匹配过程先将 PromptToken 转换为 canonical key：

```text
bare feet  -> bare_feet
bare-feet  -> bare_feet
bare_feet  -> bare_feet
{{barefoot}} -> barefoot
```

仅当 token 的 canonical key 与触发词 canonical key 完全相等时触发。

### 5.2 输出行为

输入：

```text
1girl, barefoot, high heels
```

输出：

```text
1girl, barefoot, bare_legs, high heels
```

如果 `bare_legs` 已经存在：

```text
输入：1girl, barefoot, {{bare_legs}}
输出：1girl, barefoot, {{bare_legs}}
```

目标标签已有权重时必须保留原 token；Policy 不重新赋权。

如果触发词带权重：

```text
输入：1girl, {{barefoot}}
输出：1girl, {{barefoot}}, bare_legs
```

新增的 `bare_legs` 使用普通无权重 token。

## 6. 通用推导规则结构

Policy 内部使用结构化规则对象，不在执行过程中直接散落字典判断。

建议结构：

```python
class TagInferenceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    when_any: list[str]
    add: list[str]
    unless_any: list[str] = Field(default_factory=list)
    position: Literal["after_trigger", "append"] = "after_trigger"
```

第一版的执行语义：

- `when_any`：任意一个标签存在即触发；
- `add`：依次添加目标标签；
- `unless_any`：任意排除标签存在时跳过该规则；
- `position=after_trigger`：插入到第一个触发 token 后面；
- `position=append`：追加到 Prompt 尾部；
- 每个目标标签只添加一次；
- 触发和排除都使用精确 canonical 匹配；
- `id` 只用于 trace 和错误定位，不参与 Prompt 内容。

Policy 配置模型：

```python
class TagInferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    additional_rules: list[TagInferenceSpec] = Field(default_factory=list)
```

`additional_rules` 采用追加语义：内置规则始终存在，外部配置只增加规则。需要关闭内置规则时关闭整个 `tag_inference`，第一版不提供单独禁用某条内置规则的字段。

示例：

```yaml
prompt_policy:
  require: default
  rules:
    tag_inference:
      enabled: true
      options:
        additional_rules:
          - id: high_heels_to_shoes
            when_any:
              - high_heels
            add:
              - shoes
```

## 7. 执行阶段和顺序

`tag_inference` 放在 `post_compose_cleanup` 阶段，默认顺序为：

```text
character_extension
  -> tag_inference
  -> tag_conflict
  -> character_count
  -> character_weight
```

这样可以保证：

- `character_extension` 新增的 `barefoot` 也能触发 `tag_inference`；
- 推导出的标签可以被后续 `tag_conflict` 看到；
- 用户仍可通过现有 Policy order 机制调整同一 phase 内的顺序；
- 不改变固定 phase 的整体顺序。

规则只处理 `context.positive_tokens`，不处理 `negative_tokens`。

## 8. 默认模板

更新内置模板：

| 模板 | `tag_inference` |
|---|---|
| `off` | 关闭 |
| `normalize_only` | 不启用 |
| `balanced` | 启用 |
| `strict` | 继承 `balanced`，启用 |
| `legacy_compat` | 继承 `balanced`，启用 |
| `default` | 继承 `legacy_compat`，启用 |

`balanced.yaml` 增加：

```yaml
  tag_inference:
    enabled: true
```

Rule 类的 `default_enabled` 仍保持 `false`，避免自定义 Registry 在没有模板明确选择时隐式改变行为。

## 9. Trace 和日志

自动添加标签时记录：

```yaml
rule: tag_inference@v1
action: add
token: bare_legs
reason: "inferred from barefoot"
mode: after_trigger
```

日志等级：

- `trace`：规则命中、跳过和目标已存在；
- `info`：本次执行新增标签数量；
- `warning`：配置中的额外规则被跳过的非致命情况；
- `error`：额外规则结构非法或规则 ID 重复。

日志不输出完整 Prompt，避免长提示词污染运行日志。

## 10. 错误处理

以下配置直接报错：

- `additional_rules` 不是列表；
- 规则缺少 `id`、`when_any` 或 `add`；
- `when_any` 或 `add` 为空；
- `position` 不是 `after_trigger` 或 `append`；
- 同一配置中规则 ID 重复；
- 额外规则包含未声明字段。

空字符串、只包含空白的标签在规范化后忽略；如果一条规则规范化后没有有效触发词或目标词，则作为配置错误处理，而不是静默生成无效 Prompt。

## 11. 与其他 Policy 的边界

### `tag_normalize`

负责 token 的格式规范化。`tag_inference` 复用同一套 canonical 逻辑，但不重复实现空格和下划线转换。

### `dedupe`

负责删除重复 token。`tag_inference` 添加前会先检查目标是否存在，因此正常不会制造重复；`dedupe` 仍作为整体 Prompt 的最终保险。

### `tag_conflict`

负责删除冲突标签，例如裸足删除鞋袜。它不负责添加 `bare_legs`。

### `character_extension`

负责读取角色节点中的 extension 定义。`tag_inference` 不依赖角色节点，但可以消费 extension 产生的标签。

### `clothing_policy` / `visibility_policy`

分别负责服装状态和镜头可见性，不因为 `tag_inference` 的添加而改变职责。

### `character_weight`

负责角色身份权重。`bare_legs` 不属于角色身份，不参与角色权重匹配。

## 12. AgentComposer 行为

AgentComposer 默认绕过 `PromptPolicyPipeline`，因此默认不会执行 `tag_inference`。

普通 ScriptComposer 和完整 Prompt 链路是否执行，仍由统一的 `PromptPolicyConfig.apply_to` 控制：

```yaml
apply_to:
  script: true
  full_prompt: true
  agent: false
```

不新增 Agent 专用分支，也不修改 AgentComposer cache key。

## 13. 验收标准

### 13.1 Prompt 业务链路

通过 `GenerationService` 走完整 compose + Policy 链路，验证：

1. `barefoot` 自动得到 `bare_legs`；
2. `bare_feet`、`bare-foot`、`bare feet` 可以触发；
3. `{{barefoot}}`、`2.0::barefoot::` 可以触发；
4. 已有 `bare_legs` 时不重复添加且保留原权重；
5. 没有裸足标签时不添加；
6. `barefoot_pose` 不误触发；
7. negative prompt 中的 `barefoot` 不触发；
8. Policy 关闭时 Prompt 完全不变；
9. AgentComposer 不执行该规则；
10. character extension 产生 `barefoot` 时，后续能够推导 `bare_legs`。

### 13.2 Policy 顺序和兼容性

验证：

1. `tag_inference` 位于 `tag_conflict` 之前；
2. 默认 `balanced/default` 开启；
3. `normalize_only` 不开启；
4. `additional_rules` 能追加至少一条自定义推导；
5. 自定义规则非法时在生成前报错；
6. 未配置 Policy 或使用 `off` 时不改变原有 Prompt。

### 13.3 真实业务验证

这是 Prompt 生成规则，不要求为每条单元测试单独调用 NovelAI。至少使用一个现有 NovelAI 真实出图入口验证最终请求中的 `prompt` 包含：

```text
barefoot, bare_legs
```

同时确认：

- 模型、尺寸、seed、sampler、steps 等生图参数不改变；
- `tag_conflict` 仍能清理鞋袜冲突；
- PNG 参数中的最终 prompt 与 `RenderRequest` 一致。

## 14. 实施文件

预计修改：

- `src/tags_machine_core/policies/rules/tag_inference.py`：新增 Policy 和配置模型；
- `src/tags_machine_core/policies/rules/__init__.py`：注册并导出规则；
- `src/tags_machine_core/policies/templates/balanced.yaml`：默认启用；
- `docs/prompt_policy_configuration.md`：增加配置与行为说明；
- `tests/test_prompt_policy.py`：增加完整 Prompt 链路验收；
- 必要时补充 `tests/test_prompt_policy_acceptance.py`：验证 Policy trace、模板和业务输出。

不修改：

- 旧 `tags_machine` 主链路；
- AgentComposer 实现和 cache key；
- NovelAI Renderer 协议；
- `PromptBundle` 数据结构。
