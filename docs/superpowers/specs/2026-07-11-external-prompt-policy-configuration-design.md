# PromptPolicyPipeline 外部配置与角色提权 Policy 设计规格

日期：2026-07-11

## 1. 目标

本次迭代把 `PromptPolicyPipeline` 从“代码内可扩展规则集合”升级为“可以由项目配置、Batch 和调用方稳定调节的提示词业务规则层”。

核心目标：

- 外部可以开启、关闭和配置单条 Policy。
- 外部可以调整 Policy 执行顺序。
- 未配置顺序时，严格保持代码中预定义的默认顺序。
- 外部顺序配置只描述需要改变的关系，不要求复制完整默认规则列表。
- 配置变化必须进入 cache key，并完整写入 `PromptBundle.meta.extra.policy`。
- AgentComposer 继续默认绕过 PromptPolicyPipeline。
- 首个标准范例为 `character_weight`，默认把角色身份标签从 `akemi_homura` 转换为 `2.0::akemi_homura::`。
- NovelAI v4 character prompts 自动拆分必须忽略权重进行匹配，并在最终 `char_caption` 中保留权重。

## 2. 职责边界

PromptPolicyPipeline 负责 Composer 输出之后、Renderer 之前的通用提示词业务治理：

```text
NodeResolver
  -> ScriptComposer / FullPromptComposer
  -> PromptBundle
  -> PromptPolicyPipeline
  -> Renderer
  -> RenderRequest
```

适合放入 Policy：

- token 标准化、去重和冲突处理；
- 根据 character/action 等节点元数据增删提示词；
- 衣着、可见性、角色扩展和角色提权；
- 通用正向/负向提示词治理；
- 与具体生图后端无关的 prompt 调整。

不放入 Policy：

- NovelAI `characterPrompts` 请求结构；
- sampler、steps、scale、分辨率；
- vibe、reference image；
- ComfyUI workflow、LoRA；
- 后端参数兼容和 HTTP 请求逻辑。

NovelAI Renderer 可以消费 Policy 调整后的 prompt，但不能反向承载 `character_weight` 的业务规则。

## 3. 当前问题

当前实现具备 `enabled_rules`、`disabled_rules`、`rules` 和 `options_for()`，但仍存在以下扩展成本：

1. Batch 只接受 `prompt_policy_profile`，不能传完整 Policy 配置。
2. Rule 参数是无类型的 `dict[str, Any]`，字段拼错时不能尽早报错。
3. Profile 固定写在 Python 的 `PROFILE_RULES` 中。
4. 同一 phase 内的执行顺序隐式依赖 `DEFAULT_RULES` 列表顺序。
5. 外部不能表达“让 A 在 B 之前/之后执行”。
6. `RulePhase` 在 `context.py` 和 `rules/base.py` 中重复定义且内容不一致。
7. NovelAI character prompts 当前按原始字符串匹配，权重变化会导致角色标签匹配失败。

## 4. 总体设计

新增四个明确概念：

```text
PromptPolicyRegistry
  管理可用规则、默认顺序、规则配置模型

PromptPolicyTemplateResolver
  读取 require 模板并完成原始配置合并

PromptPolicyProvider
  保存项目默认配置，为每次调用解析局部覆盖

PromptPolicyConfig
  表示已经解析和校验完成的运行时配置

PromptPolicyOrderResolver
  根据默认顺序和 before/after 约束计算最终顺序

PromptPolicyPipeline
  按解析后的顺序执行规则并生成 trace/cache metadata
```

完整调用关系：

```text
内置模板 / 项目模板 / 项目配置
  -> PromptPolicyTemplateResolver
  -> PromptPolicyProvider.default_config

Batch / CLI / Web / Python API 的局部配置
  -> PromptPolicyProvider.resolve(override)
  -> Effective PromptPolicyConfig
  -> GenerationService
  -> PromptPolicyPipeline
```

`PromptPolicyPipeline` 是纯执行器，不读取 YAML、不查找模板，也不理解 Batch 配置路径。

### 4.1 默认顺序的唯一来源

代码中的 Registry 列表是默认顺序的唯一来源：

```python
DEFAULT_RULES = [
    TagNormalizeRule(),
    CharacterExtensionPolicyRule(),
    ClothingPolicyRule(),
    VisibilityPolicyRule(),
    TagConflictRule(),
    CharacterCountRule(),
    DedupeRule(),
    CharacterWeightPolicyRule(),
]
```

实际列表应根据当前行为迁移，不能因为示例顺序改变已有业务结果。

未提供任何外部顺序约束时，Pipeline 必须保持 Registry 中的默认顺序；同一配置重复运行必须得到相同顺序。

### 4.2 Phase 仍然是固定生命周期

统一 RulePhase：

```text
normalize_input
compose_selection
post_compose_cleanup
bundle_finalize
```

Phase 顺序固定，外部不能把规则移动到另一个 phase。外部 `before/after` 主要调整同 phase 规则；跨 phase 约束只有在本身符合 phase 顺序时才允许，违反固定 phase 顺序时直接报配置错误。

这样可以避免把标准化规则移动到最终加权之后等不稳定组合。

## 5. 外部配置格式

统一使用完整 `prompt_policy` 对象：

```yaml
prompt_policy:
  require: legacy_compat
  enabled: true

  apply_to:
    script: true
    agent: false
    full_prompt: false

  normalization:
    output_style: underscore

  enabled_rules: []
  disabled_rules: []

  rules:
    visibility_policy:
      enabled: true
      options:
        mode: enforce

    character_weight:
      enabled: true
      options:
        style: braces
        level: 2
        existing_weight: replace
        missing_identity: ignore
      order:
        after:
          - dedupe
```

### 5.1 内置默认模板

Policy 不能再把“未传配置”理解成临时构造一个字段全是默认值的 `PromptPolicyConfig()`。系统应提供一份可查看、可测试、可被外部继承的内置默认模板：

```text
src/tags_machine_core/policies/templates/default.yaml
```

默认内容以 ScriptComposer 批量链路使用的 `legacy_compat` 规则集合为基线，`character_weight` 与其他默认 Policy 一起启用：

```yaml
schema: tags-machine-core.prompt-policy-template/v1
name: default

enabled: true
apply_to:
  script: true
  agent: false
  full_prompt: false

normalization:
  output_style: underscore

rules:
  tag_normalize:
    enabled: true
  character_extension:
    enabled: true
  clothing_policy:
    enabled: true
  visibility_policy:
    enabled: true
  tag_conflict:
    enabled: true
  character_count:
    enabled: true
  dedupe:
    enabled: true
  character_weight:
    enabled: true
    options:
      style: numeric
      numeric_weight: 2.0
```

注意：当前源码中 `PromptPolicyConfig()` 的实际行为是 `enabled: false`。切换为上述内置模板属于明确的默认行为变更，实施时必须通过现有 Batch mock 和真实出图确认后再启用，不能把它伪装成无行为变化的重构。

Rule 类与默认模板各自负责不同内容：

- Rule 类声明 `id`、`version`、`phase`、实现逻辑和 options 字段默认值；
- Registry 声明规则默认执行顺序；
- `default.yaml` 声明产品默认开启哪些规则，以及默认的业务参数；
- Batch/项目配置只覆盖需要变化的部分。

这样不会在 Rule 类和配置模板中重复维护执行顺序或算法参数。

现有代码中的 profile 全部迁移为包内置模板：

```text
templates/default.yaml
templates/off.yaml
templates/normalize_only.yaml
templates/balanced.yaml
templates/strict.yaml
templates/legacy_compat.yaml
```

新配置不再同时保留 `profile` 和 `require` 两套规则集合选择机制：

```yaml
prompt_policy:
  require: legacy_compat
```

替代旧写法：

```yaml
prompt_policy:
  profile: legacy_compat
```

完成现有配置迁移后删除代码中的 `PROFILE_RULES`。

### 5.2 require 与模板继承

下层配置通过 `require` 引用模板：

```yaml
defaults:
  prompt_policy:
    require: default
    rules:
      character_weight:
        enabled: true
        options:
          level: 2
```

模板查找规则：

1. `require: default` 等名称先从项目配置的 `prompt_policy_template_root` 查找；
2. 项目目录没有同名模板时，从包内置 `policies/templates` 查找；
3. `require: ./policies/portrait.yaml` 按当前 YAML 文件目录解析相对路径；
4. 找不到模板、模板 schema 非法或出现循环 require 时，在任务展开前报错。

模板自身可以继续 require 一个父模板，但首版只允许单继承，不支持同时 require 多份模板，避免多继承合并顺序不清晰。

运行时 `PromptPolicyConfig` 不保留 `require` 字段。Resolver 先加载并合并模板，再把最终结果交给 Pydantic 校验；Policy metadata 额外记录模板名称和内容 hash。

### 5.3 未传配置与局部覆盖语义

统一语义如下：

```text
没有 prompt_policy
  -> 使用内置 default 模板

传入 prompt_policy，但没有 require
  -> 隐式 require: default
  -> 只覆盖明确传入的字段

传入 prompt_policy.require
  -> 以指定模板为基线
  -> 只覆盖明确传入的字段
```

因此下面不是“整份配置替换”，而是“规则级深度覆盖”：

```yaml
prompt_policy:
  rules:
    character_weight:
      enabled: true
      options:
        level: 2
```

它只改变 `character_weight`，其他 Policy 继续使用 `default` 模板中的配置。

若要关闭默认规则，必须显式声明：

```yaml
prompt_policy:
  rules:
    visibility_policy:
      enabled: false
```

若要关闭整个 Pipeline：

```yaml
prompt_policy:
  enabled: false
```

首版不提供隐式的“整份替换”模式。需要完全自定义时，显式 `require: off`，再逐条开启规则：

```yaml
prompt_policy:
  require: off
  enabled: true
  rules:
    tag_normalize:
      enabled: true
    character_weight:
      enabled: true
```

内置 `off.yaml` 内容只负责关闭 Pipeline，不复制任何规则配置。

### 5.4 深度覆盖规则

模板合并必须在 Pydantic model validation 之前对原始映射执行，否则无法区分“字段未传入”和“字段传入了默认值”。

合并规则：

- mapping 递归合并；
- scalar 使用下层值替换上层值；
- list 使用下层完整替换，不做追加；
- 字段缺失表示继承；
- 空列表 `[]` 表示显式清空；
- `rules.<id>.options` 递归合并；
- `rules.<id>.order.before/after` 使用下层列表完整替换；
- 合并结束后统一执行 schema、rule id、options 和顺序约束校验。

例如默认模板中：

```yaml
rules:
  character_weight:
    enabled: false
    options:
      style: braces
      level: 2
      existing_weight: replace
```

下层只写：

```yaml
rules:
  character_weight:
    enabled: true
```

最终结果为：

```yaml
rules:
  character_weight:
    enabled: true
    options:
      style: braces
      level: 2
      existing_weight: replace
```

### 5.5 原始配置与运行时配置分离

为了正确表达“字段没传就是继承”，需要区分两种模型：

```python
class PromptPolicySource(BaseModel):
    """来自 YAML、Batch、Web 或 Python API 的可继承局部配置。"""

    require: str | None = None
    enabled: bool | None = None
    apply_to: dict[str, bool] | None = None
    normalization: dict[str, Any] | None = None
    enabled_rules: list[str] | None = None
    disabled_rules: list[str] | None = None
    rules: dict[str, PromptPolicyRuleSource] | None = None


class PromptPolicyConfig(BaseModel):
    """模板和局部覆盖合并后得到的完整运行时配置。"""

    enabled: bool
    apply_to: PromptPolicyApplyTo
    normalization: PromptNormalizationConfig
    enabled_rules: list[str]
    disabled_rules: list[str]
    rules: dict[str, PromptPolicyRuleConfig]
```

不能先把局部输入直接解析成 `PromptPolicyConfig` 再合并，因为 Pydantic 会填充默认值，导致系统无法判断某个字段是调用方明确传入，还是模型自动补上的。

### 5.6 字段含义

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `require` | string/null | 引用内置、项目级或相对路径 Policy 模板 |
| `enabled` | bool | 是否启用整个 Pipeline |
| `apply_to` | object | 控制 script、agent、full_prompt 目标 |
| `normalization` | object | token 匹配和最终输出格式 |
| `enabled_rules` | string[] | 在模板基础上额外开启规则 |
| `disabled_rules` | string[] | 强制关闭规则，优先级最高 |
| `rules.<id>.enabled` | bool/null | 单规则开关 |
| `rules.<id>.options` | object | 单规则类型化参数 |
| `rules.<id>.order.before` | string[] | 当前规则必须位于这些规则之前 |
| `rules.<id>.order.after` | string[] | 当前规则必须位于这些规则之后 |

### 5.7 开关优先级

规则是否启用按以下优先级判定：

```text
disabled_rules
  > rules.<id>.enabled: false
  > enabled_rules
  > rules.<id>.enabled: true
  > require 模板
  > rule.default_enabled
```

`disabled_rules` 是最终否决项，方便 Batch 临时关闭模板中的规则。

### 5.8 不再保留两套规则参数入口

当前 `rules` 与 `rule_options` 表达能力重复。新格式统一为：

```yaml
rules:
  character_weight:
    enabled: true
    options:
      level: 2
```

`rule_options` 在完成已有配置迁移后删除，避免参数覆盖顺序不清晰。

## 6. Policy 顺序解析

### 6.1 为什么使用 before/after

不采用完整 `order: [a, b, c]` 列表作为主要接口，原因是：

- Batch 只想移动一条规则时，不应复制全部默认规则。
- 后续新增 Policy 后，旧配置不应该因为没有列出新规则而漏执行。
- `before/after` 更适合表达局部意图。

### 6.2 解析算法

每个 phase 单独排序：

1. 从 Registry 取得已启用规则及默认下标。
2. 收集 `before/after` 约束，形成有向图。
3. 使用稳定拓扑排序计算结果。
4. 对没有显式先后关系的规则，以 Registry 默认下标作为稳定排序依据。
5. 合并各 phase 的结果。

因此：

- 没有顺序配置时，结果与 Registry 完全一致。
- 只配置一条约束时，只改变必要的局部关系。
- 新增无约束 Policy 时，按 Registry 默认位置自动进入旧配置。

### 6.3 配置校验

以下情况必须在真正出图前报错：

- 引用了未注册的 rule id；
- 规则同时声明在同一目标的 before 和 after；
- before/after 形成循环；
- 约束要求跨越固定 phase 的逆序；
- 单规则 options 不符合该规则的配置模型；
- 同一个 rule id 被重复注册。

引用已注册但当前未启用的规则不报错，记录 warning，并忽略该条约束。这样模板切换时可以复用同一份覆盖配置。

### 6.4 顺序元数据

PromptBundle 中记录默认与实际顺序：

```json
{
  "policy": {
    "enabled": true,
    "template": "legacy_compat",
    "template_hash": "sha256:...",
    "default_rule_order": [
      "tag_normalize@v1",
      "character_extension@v1",
      "dedupe@v1",
      "character_weight@v1"
    ],
    "effective_rule_order": [
      "tag_normalize@v1",
      "character_extension@v1",
      "dedupe@v1",
      "character_weight@v1"
    ],
    "order_overrides": {
      "character_weight": {
        "after": ["dedupe"]
      }
    }
  }
}
```

最终生效的规则开关、实际顺序、规则版本和 options 进入 cache signature。

模板名称、模板路径和模板内容 hash 只进入追踪 metadata，不直接进入 cache key。只要两个模板解析出的 effective config 完全相同，它们的业务输出就应允许共用缓存；模板内容变化导致 effective config 变化时，cache signature 会自然变化。

## 7. 类型化 Rule 配置

每个 Rule 可以声明自己的 Pydantic 配置模型：

```python
class CharacterWeightOptions(BaseModel):
    style: Literal["braces", "numeric"] = "numeric"
    level: int = Field(default=2, ge=1, le=6)
    numeric_weight: float = Field(default=2.0, gt=0)
    existing_weight: Literal["replace", "keep", "increase"] = "replace"
    missing_identity: Literal["ignore", "error"] = "ignore"


class CharacterWeightPolicyRule:
    id = "character_weight"
    version = "v1"
    phase = "bundle_finalize"
    default_enabled = False
    options_model = CharacterWeightOptions
```

Registry 在 Pipeline 执行前完成 options 校验，Rule 内拿到的是已校验对象，不再自行解析松散字典。

为了平滑迁移，未声明 `options_model` 的旧 Rule 可以暂时继续接收字典，但新建 Rule 必须提供类型化配置。

## 8. PromptPolicyProvider 与 GenerationService

### 8.1 Provider 职责

`PromptPolicyProvider` 是所有非 Agent 入口共享的配置入口：

```python
class PromptPolicyProvider:
    def __init__(
        self,
        *,
        template_resolver: PromptPolicyTemplateResolver,
        project_default_source: PromptPolicySource | None = None,
    ): ...

    def default_config(self) -> PromptPolicyConfig: ...

    def resolve(
        self,
        override: PromptPolicySource | PromptPolicyConfig | dict | None,
    ) -> PromptPolicyConfig: ...
```

Provider 启动时完成：

1. 加载内置 `default` 模板；
2. 合并项目级 `AppConfig.prompt_policy`；
3. 校验规则、options 和顺序；
4. 缓存完整的项目默认 `PromptPolicyConfig`。

每次生成时：

- `override is None`：返回项目默认配置的深拷贝；
- `override` 是局部 source/dict：基于项目默认配置深度覆盖并重新校验；
- `override` 是完整 `PromptPolicyConfig`：直接作为已解析配置使用，但仍由 Registry 检查 rule/version/order；
- 模板文件不会在每张图生成时重复读取。

项目模板可以按绝对路径和内容 hash 缓存；开发模式检测 mtime 后重新加载，生产模式在进程启动时固定，避免同一 Batch 中途改变规则。

### 8.2 GenerationService 默认行为

`GenerationService` 注入 Provider：

```python
class GenerationService:
    def __init__(
        self,
        *,
        policy_pipeline: PromptPolicyPipeline | None = None,
        policy_provider: PromptPolicyProvider | None = None,
    ):
        self.policy_pipeline = policy_pipeline or PromptPolicyPipeline()
        self.policy_provider = (
            policy_provider
            or PromptPolicyProvider.with_builtin_defaults()
        )
```

现有调用方式保持不变：

```python
service = GenerationService()

bundle = service.compose_resolved_nodes(
    resolved_nodes,
)
```

内部执行：

```python
effective_policy = self.policy_provider.resolve(prompt_policy)

return self.policy_pipeline.apply(
    bundle,
    resolved_nodes=resolved_nodes,
    config=effective_policy,
    target="script",
)
```

统一语义：

```text
prompt_policy=None
  -> 使用项目默认配置；没有项目覆盖时使用内置 default

prompt_policy={局部字段}
  -> 基于项目默认配置覆盖

prompt_policy={require: xxx}
  -> 加载指定模板，再应用当前局部字段

prompt_policy={enabled: false}
  -> 当前调用关闭 Pipeline
```

### 8.3 Pipeline 保持纯执行

`PromptPolicyPipeline.apply()` 只接受完整 `PromptPolicyConfig`，不再包含 `_coerce_config(dict | None)` 之类的配置兼容逻辑：

```python
def apply(
    self,
    bundle: PromptBundle,
    *,
    resolved_nodes: ResolvedNodeSet | None,
    config: PromptPolicyConfig,
    target: PolicyTarget,
) -> PromptBundle:
    ...
```

这样职责为：

```text
Provider：配置继承、模板、默认值、校验
Pipeline：执行计划和 PromptBundle 修改
Rule：单条业务规则
```

### 8.4 入口一致性

以下入口必须使用同一个 Provider：

- BatchPlanner/BatchRunner；
- CLI compose/run-nodes/run-prompt 等非 Agent 入口；
- Web API；
- JSON API；
- Python 直接调用 GenerationService。

入口不得自行实现 `require` 查找、深度合并或默认规则选择。

### 8.5 默认行为变更门禁

当前 `PromptPolicyConfig()` 默认关闭 Pipeline。改造后 `GenerationService()` 不传 Policy 将使用内置 `default.yaml`，这是业务行为变化。

启用前必须：

1. 固化一份“当前标准默认”对比集；
2. 用 mock batch 对比新旧最终 prompt 和 render request；
3. 对存在预期变化的规则逐条记录；
4. 至少完成单角色和多角色 NovelAI 真实出图；
5. 确认 AgentComposer 链路完全不受影响。

若默认模板尚未通过验收，可以先让 `default.yaml` 等价于 off，在验收完成的提交中再切换为正式默认规则集合。

## 9. Batch 接入

### 9.1 Batch YAML

`BatchDefaults.prompt_policy_profile` 替换为完整对象：

```yaml
defaults:
  composer: script
  artist: "20260412"

  prompt_policy:
    require: legacy_compat
    enabled: true
    apply_to:
      script: true
      agent: false
      full_prompt: false
    rules:
      character_weight:
        enabled: true
        options:
          style: braces
          level: 2
        order:
          after:
            - dedupe
```

BatchPlanner 不再使用 `_policy_config(profile, composer)` 手工拼装简化字典，而是：

```text
读取 BatchDefaults.prompt_policy
  -> 验证 PromptPolicyConfig
  -> 根据 composer 检查 target 是否允许
  -> 原样写入 BatchTask.policy
  -> BatchRunner 传给 GenerationService
```

BatchTask 中的 `policy` 从 `dict[str, Any]` 改为 `PromptPolicyConfig | None`，让任务展开阶段就能发现非法配置。

### 9.2 配置层级

配置合并顺序：

```text
Rule 代码默认值
  < 项目 AppConfig.prompt_policy
  < Batch defaults.prompt_policy
  < BatchTask.policy 覆盖
```

合并规则：

- 标量字段由高层覆盖低层；
- `apply_to`、`normalization`、`rules` 按键深度合并；
- `enabled_rules`、`disabled_rules` 使用高层完整替换，避免隐式累积；
- `rules.<id>.order.before/after` 使用高层完整替换；
- 最终合并结果重新执行完整校验。

第一阶段可以只接入项目配置与 Batch defaults；Task 级覆盖保留数据结构和合并能力，等 Web/Batch Studio 需要时开放。

## 10. AgentComposer 边界

本次不改变 AgentComposer 稳定链路：

```text
AgentComposer -> PromptBundle -> Renderer
```

即使外部配置写了 `apply_to.agent: true`，当前 AgentComposer 调用链也不会自动执行 Pipeline。为避免产生“配置已生效”的错觉，本次校验规则为：

- AgentComposer + `prompt_policy.enabled: true` 时，如果没有未来明确的 agent opt-in 入口，记录 warning；
- Batch 中 composer 为 `agent` 时，Policy 不执行；
- 不为兼容配置而把 AgentComposer 偷偷接入 Pipeline。

以后如果需要对 agent 结果做规则治理，应新增明确模式，例如 `agent_post_policy: true`，并单独做业务验收。

## 11. CharacterWeightPolicyRule

### 11.1 目的

对 character 节点声明的身份提示词提权：

```text
akemi_homura
  -> 2.0::akemi_homura::
```

它只处理角色身份，不默认处理发色、眼睛、服装、武器和版权标签。

### 11.2 身份提示词来源

按以下顺序收集，每个角色可以得到多个身份 token：

1. `character.prompt.positive` 中 `role: character` 的 fragment；
2. `character.tags.character`；
3. `character.character_id` 作为兜底。

收集后 canonicalize 并去重。不能使用节点目录名、`name` 或整个 character prompt 做模糊推断。

例如：

```yaml
kind: character
character_id: akemi_homura
tags:
  character:
    - akemi_homura
  hair:
    - black_hair
  eyes:
    - purple_eyes
```

只会默认提权 `akemi_homura`。

### 11.3 匹配规则

- 只匹配 positive prompt。
- 使用去权重后的 canonical token 做精确匹配。
- 不使用 substring 匹配。
- 多角色分别收集、分别匹配。
- 同一身份 token 出现多次时全部转换，后续是否去重由规则顺序决定。
- 找不到身份 token 时按 `missing_identity` 决定忽略或报错。

### 11.4 权重格式

默认配置：

```yaml
character_weight:
  enabled: true
  options:
    style: braces
    level: 2
    existing_weight: replace
    missing_identity: ignore
```

转换结果：

| 输入 | 配置 | 输出 |
| --- | --- | --- |
| `akemi_homura` | braces + level 2 | `{{akemi_homura}}` |
| `{akemi_homura}` | replace | `{{akemi_homura}}` |
| `{{{akemi_homura}}}` | replace | `{{akemi_homura}}` |
| `2.0::akemi_homura::` | replace | `{{akemi_homura}}` |
| `{akemi_homura}` | keep | `{akemi_homura}` |
| `{akemi_homura}` | increase + level 2 | `{{{akemi_homura}}}` |

`increase` 的 braces `level` 表示额外增加层数；`replace` 的 level 表示最终层数。

### 11.5 默认执行位置

`character_weight` 规则类默认：

```text
phase: bundle_finalize
default_enabled: false
```

产品默认模板会显式开启该规则；`default_enabled: false` 只保证脱离模板单独注册规则时不会意外启用。执行位置原因：

- 先完成角色扩展、衣着和可见性处理；
- 先完成冲突和去重；
- 最后只修改身份 token 的权重表现；
- 避免较早加权影响仍未完成权重无关匹配的旧规则。

如以后新增其他 `bundle_finalize` 规则，可以通过 before/after 调整它们的相对顺序。

### 11.6 Trace

每个转换记录一条 trace：

```json
{
  "rule": "character_weight@v1",
  "action": "replace_weight",
  "token": "akemi_homura",
  "from": "akemi_homura",
  "to": "2.0::akemi_homura::",
  "reason": "matched character identity: akemi_homura",
  "mode": "replace"
}
```

多角色必须能从 trace 看出每个身份 token 的处理结果。后续可给 trace 增加 `node_ref`，但本次不要求修改公共 trace schema。

## 12. NovelAI Character Prompts 兼容

### 12.1 当前问题

NovelAI Renderer 当前使用原始字符串比较：

```text
character material: akemi_homura
base prompt: 2.0::akemi_homura::
```

两者不相等，导致：

- `akemi_homura` 不会进入 `char_captions`；
- 角色身份仍留在 `base_caption`；
- character prompts 功能实际失效。

### 12.2 新匹配方式

Renderer 的匹配改为两层数据：

```text
raw token:       2.0::akemi_homura::
canonical key:   akemi_homura
```

匹配使用 canonical key，输出使用 raw token：

```text
candidate key akemi_homura
  == base key akemi_homura
  -> char_caption 保留 2.0::akemi_homura::
```

最终 NovelAI v4 参数应为：

```json
{
  "v4_prompt": {
    "caption": {
      "base_caption": "...",
      "char_captions": [
        {
          "char_caption": "girl, 2.0::akemi_homura::, black_hair, purple_eyes"
        }
      ]
    }
  }
}
```

`base_caption` 中不再保留已迁移的 `2.0::akemi_homura::`。

### 12.3 多角色和共享特征

保持现有原则：所有角色先完成匹配，再从 base prompt 删除已匹配 token。

共享特征例如 `black_hair` 同时属于两个 character material 时：

- 两个角色的 char caption 都获得该特征；
- 所有角色匹配完成后，base caption 再删除一次对应 token；
- 权重形式必须在两个 char caption 中保持一致。

## 13. Registry 设计

建议新增：

```python
@dataclass(frozen=True)
class PromptPolicyRegistration:
    rule: PromptRule
    default_index: int
    options_model: type[BaseModel] | None


class PromptPolicyRegistry:
    def register(self, rule: PromptRule) -> None: ...
    def get(self, rule_id: str) -> PromptPolicyRegistration: ...
    def default_order(self) -> list[str]: ...
    def validate_config(self, config: PromptPolicyConfig) -> ValidatedPolicyPlan: ...
```

第一阶段不做动态 Python 插件扫描。新增 Rule 仍通过代码显式注册，保证部署可控；“外部可调整”指外部调整已注册规则的开关、参数和顺序，而不是从 YAML 执行任意 Python。

## 14. Pipeline 输出

Pipeline 执行完成后至少记录：

```yaml
meta:
  extra:
    policy:
      enabled: true
      template: legacy_compat
      template_hash: sha256:...
      target: script
      default_rule_order: []
      effective_rule_order: []
      rule_options: {}
      order_overrides: {}
    policy_trace: []
```

日志：

```text
INFO  PromptPolicyPipeline plan target=script template=legacy_compat rules=[...]
TRACE PromptPolicyRule start rule=character_weight@v1 token_count=...
TRACE PromptPolicyRule complete rule=character_weight@v1 changed=1
WARNING PromptPolicy order constraint ignored because target rule is disabled ...
ERROR PromptPolicy configuration invalid cycle=...
```

生产默认日志级别仍保持 error，不因本次改造改变全局日志策略。

## 15. 验收标准

### 15.1 顺序和配置验收

- 未配置 order 时，实际顺序和 Registry 默认顺序完全一致。
- 单条 `before/after` 只改变必要的局部顺序。
- 循环、未知 rule、非法 options 在出图前失败。
- Batch 展开后的每个 `BatchTask.policy` 都是完整、已验证配置。
- Policy options 或顺序改变后 cache key 必须变化。
- AgentComposer 的 prompt 和 cache key 不受影响。

### 15.2 CharacterWeight 功能验收

单角色：

```text
输入: 1girl, akemi_homura, black_hair
输出: 1girl, 2.0::akemi_homura::, black_hair
```

多角色：

```text
输入: 2girls, akemi_homura, kaname_madoka
输出: 2girls, 2.0::akemi_homura::, 2.0::kaname_madoka::
```

不应提权：

```text
black_hair
purple_eyes
school_uniform
mahou_shoujo_madoka_magica
```

### 15.3 Mock Batch 验收

使用现有 batch mock executor 展开一组包含至少两个角色的任务，检查：

- `PromptBundle.prompt.positive` 包含提权后的角色身份；
- `policy.effective_rule_order` 正确；
- `policy_trace` 包含每个角色的 `replace_weight`；
- `RenderRequest` 中的 prompt 与 PromptBundle 一致；
- 未启用 Policy 的对照任务保持原 prompt。

### 15.4 NovelAI 真实出图验收

业务测试优先，至少运行：

1. NovelAI v3 或关闭 character prompts 的单角色图。
2. NovelAI v4.5 + `character_prompts=auto` 的单角色图。
3. NovelAI v4.5 + `character_prompts=auto` 的双角色图。

检查内容：

- PNG 参数中角色身份提示词权重正确；
- v4.5 `base_caption` 不再包含已迁移的角色身份；
- v4.5 `char_captions` 包含 `2.0::akemi_homura::` 等带权重身份；
- 双角色分别进入各自 caption；
- 图片主体角色和角色区分正常；
- 与未启用 Policy 的对照图记录 seed、画风、尺寸和参数差异。

## 16. 实施阶段

### 阶段一：Policy 配置基础设施

- 统一 RulePhase。
- 新增 Registry 和类型化 Rule 配置接口。
- 新增 before/after 稳定拓扑排序。
- 扩展 policy meta、trace、cache signature。

### 阶段二：模板与 Provider

- 新增内置 Policy 模板。
- 将现有 profile 迁移为模板。
- 新增 PromptPolicySource、TemplateResolver 和 Provider。
- GenerationService 默认通过 Provider 获取 effective config。
- Pipeline 收窄为只接受完整 PromptPolicyConfig。

### 阶段三：外部配置接入

- AppConfig 支持完整 `prompt_policy`。
- BatchDefaults 使用完整 `prompt_policy`。
- BatchTask.policy 类型化。
- BatchPlanner 删除只接受 profile 的简化拼装，并由模板 Resolver 生成完整配置。
- CLI、Web、JSON API 和 Python 调用共用 Provider。
- 更新 Batch README 和示例。

### 阶段四：CharacterWeightPolicyRule

- 实现角色身份 token 收集。
- 实现 braces/numeric 权重策略。
- 实现 existing_weight 行为和 trace。
- 注册为类级默认关闭、产品默认模板显式开启的 `bundle_finalize` Rule。

### 阶段五：NovelAI 权重透明匹配

- character prompt 匹配改为 canonical key。
- caption 输出保留原始权重 token。
- 保持多角色共享特征“全部匹配后再删除”。

### 阶段六：业务验收

- Mock batch 参数验证。
- NovelAI 单角色真实出图。
- NovelAI 双角色真实出图。
- 保存 PromptBundle、RenderRequest、GenerationResult、PNG 参数和视觉结论。

## 17. 预计改动模块

```text
src/tags_machine_core/policies/config.py
src/tags_machine_core/policies/context.py
src/tags_machine_core/policies/pipeline.py
src/tags_machine_core/policies/registry.py                 新增
src/tags_machine_core/policies/ordering.py                 新增
src/tags_machine_core/policies/source.py                   新增
src/tags_machine_core/policies/template_resolver.py        新增
src/tags_machine_core/policies/provider.py                 新增
src/tags_machine_core/policies/templates/default.yaml      新增
src/tags_machine_core/policies/templates/off.yaml          新增
src/tags_machine_core/policies/templates/*.yaml            新增
src/tags_machine_core/policies/rules/base.py
src/tags_machine_core/policies/rules/__init__.py
src/tags_machine_core/policies/rules/character_weight.py   新增
src/tags_machine_core/policies/tokens.py
src/tags_machine_core/batch/models.py
src/tags_machine_core/batch/planner.py
src/tags_machine_core/renderers/novelai.py
docs/batch_generation_readme.md
examples/batches/...
tests/...
```

## 18. 最终决策

- Policy 默认顺序继续由代码 Registry 控制。
- 外部通过 `before/after` 做局部顺序覆盖。
- 外部不需要复制完整规则列表。
- Phase 顺序不可由配置突破。
- 内置与项目级 YAML 模板统一管理产品默认 Policy 配置。
- 未传 `prompt_policy` 时隐式使用 `require: default`。
- 传入局部配置时基于模板深度覆盖，不影响未配置 Policy。
- 现有 profile 迁移为内置模板，完成迁移后删除 `PROFILE_RULES`。
- GenerationService 通过 PromptPolicyProvider 获得默认配置和调用级覆盖。
- PromptPolicyPipeline 不读取模板，只执行完整、已校验的运行时配置。
- Batch 使用完整 PromptPolicyConfig，不再只传 profile。
- 新 Rule 必须优先采用类型化 options。
- AgentComposer 继续绕过 PromptPolicyPipeline。
- `character_weight` 是首个标准范例，默认把 character 身份 token 转为双层 braces。
- NovelAI character prompts 必须做到权重透明匹配、权重原样输出。
