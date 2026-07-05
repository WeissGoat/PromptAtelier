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

## 2026-07-05 扫描补充：Extension Slot Registry

对 `design/角色/**/tags.txt` 做统计后，需要修正上一版 `Extension Type` 设计。真实 character 节点里 extension 很多，而且明显分成两层：一层是角色素材声明，另一层是通用触发规则。

### 扫描结果

素材声明主要是 `ext_*`：

| 类型 | 出现次数 | 语义 |
| --- | ---: | --- |
| `ext_legwear` | 323 | 角色默认腿部/袜类素材，例如 `black_thighhighs`、`white socks` |
| `ext_shoes` | 306 | 角色默认鞋类素材，例如 `loafers`、`boots`、`high_heels` |
| `ext_weapon` | 286 | 角色默认武器/道具素材，例如 `greatsword`、`mage_staff` |
| `ext_background` | 218 | 角色关联背景素材，例如 `outdoors`、`sky`、`indoors` |
| `ext_item` | 114 | 角色关联小物件素材，例如 `flower`、`book`、`controller` |

触发规则主要是：

| 类型 | 出现次数 | 说明 |
| --- | ---: | --- |
| `leg_wear` | 366 | 腿部/袜类规则 |
| `shoes` | 359 | 鞋类规则 |
| `weapon` | 316 | 武器/道具规则 |
| `barefoot` | 27 | 赤脚规则 |
| `extend_func_pant` | 44 | 裤袜/内衣/连体衣相关修正规则 |
| `extend_func_pantyhose` | 7 | 连裤袜相关修正规则 |
| `extend_func_barefoot` | 7 | 赤脚相关修正规则 |
| `extend_func_nipple` | 4 | 胸甲/乳首冲突修正规则 |
| `extend_func_boy` | 3 | 男性角色/路人男性补充规则 |
| `after_uc` | 33 | 负面提示词追加，不归入正向 character extension |
| `blocking_story` | 8 | 动作分类过滤，不归入 prompt 改写 |

因此，上一版中“每条 legacy rule 自带 trigger 列表”的设计过于生硬。新的规范应改成：每个 extension slot 的触发词由系统统一维护；character 节点主要声明本角色在该 slot 下应该使用的素材。

### 新模型

新增内部概念：

```text
ExtensionSlotRegistry
  -> slot: legwear / shoes / weapon / item
  -> fixed triggers
  -> legacy rule names
  -> declaration names

CharacterExtensionMaterial
  -> character ref
  -> slot
  -> material tags from ext_*

LegacyExtensionRule
  -> optional operation override from legacy rule lines
```

也就是说，`ext_legwear/ext_shoes/ext_weapon/ext_item` 是素材声明，不是 operation；`leg_wear/shoes/weapon/barefoot/extend_func_*` 是旧 rule 行，可以提供兼容 operation。

### 固定触发词

第一版内置固定 slot：

```yaml
legwear:
  legacy_rule_names: ["leg_wear", "barefoot"]
  declaration_names: ["ext_legwear"]
  triggers:
    any:
      - pantyhose
      - thighhighs
      - socks
      - sock
      - kneehighs
      - legwear
      - stirrup legwear
      - toeless legwear
      - barefoot
      - bare feet

shoes:
  legacy_rule_names: ["shoes"]
  declaration_names: ["ext_shoes"]
  triggers:
    any:
      - shoes
      - footwear
      - boots
      - high heels
      - sneakers
      - loafers
      - mary janes
      - sandals
      - thigh boots
      - armored boots

weapon:
  legacy_rule_names: ["weapon"]
  declaration_names: ["ext_weapon", "ext_item"]
  triggers:
    any:
      - weapon
      - sword
      - gun
      - rifle
      - staff
      - wand
      - bow
      - shield
      - spear
      - holding weapon
```

`ext_background` 暂时不接入 `character_extension`。它更像背景选择素材，后续应交给 background selector 或 batch planner 规则。

`after_uc` 暂时不接入正向 prompt 改写。它应作为独立的 negative prompt extension 规则处理。

`blocking_story` 暂时不接入 prompt 改写。它对应旧版 `TagsMachine.default_filter_func` 的动作分类过滤，应放在 batch planner 或 task filter 层。

### Character Material Declaration

character 的 `tags.txt` 中，`ext_*` 行优先作为素材声明读取。

示例：

```text
ext_legwear,black_thighhighs,{single_thighhigh}
ext_shoes,boots
ext_weapon,mage_staff,witch_hat
```

归一化后：

```yaml
materials:
  legwear:
    - black_thighhighs
    - "{single_thighhigh}"
  shoes:
    - boots
  weapon:
    - mage_staff
    - witch_hat
```

当 prompt 命中 slot 固定触发词时，规则优先使用该角色对应 slot 的 materials。

### Legacy Rule Lines

旧 character 节点里也有完整 rule 行，例如：

```text
leg_wear, pantyhose|thighhighs|socks, include_replace|thighhighs|pantyhose|black_thighhighs, add|black_thighhighs
shoes, shoes|boots|high_heels, include_replace|boots|high_heels|boots, add_after|boots|shoes, add|boots
weapon, weapon|sword, include_replace|weapon|sword|mage_staff, add_after|mage_staff|weapon, add|mage_staff
```

这些行的 operation 可以继续兼容，但触发判断默认不再使用第二段 legacy trigger。触发词应该来自 slot registry。

兼容策略：

| 模式 | 行为 | 用途 |
| --- | --- | --- |
| `fixed` | 只使用 slot 固定触发词 | 默认模式，长期推荐 |
| `fixed_plus_legacy` | 固定触发词和 legacy trigger 取并集 | 过渡期排查差异 |
| `legacy` | 只使用 legacy rule 第二段 trigger | 旧 formula 对比 |

### Operation 支持范围修订

扫描后，第一版 operation 需要支持：

```text
include_replace|old_a|old_b|target
replace|old_a|old_b|target
add|tag_a|tag_b
add_before|tag_a|target
add_after|tag_a|target
remove|match_a|match_b
exact_replace|old|new
fuzzy_replace|match|new
add_if_not_exist|target|match_a|match_b
```

其中 `include_replace` 是最重要的兼容操作，真实素材中出现超过一千次，主要用于 `leg_wear/shoes/weapon` 的同类替换。

### Disabled And Loose Lines

扫描发现存在明显禁用行：

```text
#leg_wear,...
-leg_wear,...
--leg_wear,...
#ext_weapon,...
```

也有少量松散行：

```text
neck ribbon
```

第一版处理方式：

- 以 `#`、`-`、`--` 开头的 extension 行默认忽略。
- 无法解析成 `slot, ...` 或 `ext_*, ...` 的松散行默认忽略并写 warning trace。
- 不把松散行自动追加到 prompt，避免历史注释或误写内容变成生图参数。

### 配置修订

`character_extension` 增加配置：

```yaml
prompt_policy:
  rules:
    character_extension:
      enabled: true
      source: legacy_tags_txt
      include_default_extensions: true
      include_declaration_materials: true
      trigger_mode: fixed
      ignore_disabled_lines: true
      enabled_slots:
        - legwear
        - shoes
        - weapon
```

字段含义：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `include_declaration_materials` | `true` | 是否读取 `ext_legwear/ext_shoes/ext_weapon/ext_item` 作为角色素材 |
| `trigger_mode` | `fixed` | extension slot 触发词来源：`fixed`、`fixed_plus_legacy`、`legacy` |
| `ignore_disabled_lines` | `true` | 是否忽略 `#`、`-`、`--` 开头的 legacy extension 行 |
| `enabled_slots` | `["legwear", "shoes", "weapon"]` | 启用哪些 slot；`background` 不在第一版范围 |

### 设计结论

最终推荐模型是：

```text
固定触发词由 ExtensionSlotRegistry 管
角色具体素材由 ext_* 声明
旧 rule 行只作为 operation 兼容层
```

这样既能复用旧 character `tags.txt`，又不会把“通用触发规则”继续散落在每个角色节点里。

## 2026-07-05 最终修订：触发词全集与 character operation 边界

本节覆盖前文手写的示例 registry。实现时以本节的扫描全集为准。

### 扫描范围

扫描范围：

```text
design/角色/**/tags.txt
```

扫描规则：

- 只统计 `=` 后的 legacy extension section。
- `after_uc`、`origin_uc`、`origin_clear`、`gen_param`、`gen_json` 这类 inline extension 也会识别。
- 以 `#`、`-`、`--` 开头的行归入 disabled，不进入 active registry。
- 只有一个字段且不是已知 extension 形态的行归入 loose，不自动执行。

### Active Extension Types 全量

以下是 character extension section 中真实出现的 active 类型全集：

| 类型 | 次数 | 归类 | 第一版处理 |
| --- | ---: | --- | --- |
| `leg_wear` | 366 | positive slot rule | 接入 `legwear` slot |
| `shoes` | 359 | positive slot rule | 接入 `shoes` slot |
| `weapon` | 316 | positive slot rule | 接入 `weapon` slot |
| `extend_func_pant` | 44 | positive operation rule | 接入 `pant` slot |
| `after_uc` | 33 | negative prompt extension | 第一版不接入 character positive extension |
| `barefoot` | 27 | positive slot rule | 接入 `legwear` slot |
| `blocking_story` | 8 | action filter | 第一版不接入 prompt 改写 |
| `extend_func_barefoot` | 7 | positive operation rule | 接入 `barefoot` slot |
| `extend_func_pantyhose` | 7 | positive operation rule | 接入 `pantyhose` slot |
| `extend_func_nipple` | 4 | positive operation rule | 接入 `nipple` slot |
| `extend_func_boy` | 3 | positive operation rule | 接入 `boy` slot |

素材声明类型全集：

| 类型 | 次数 | 归类 | 第一版处理 |
| --- | ---: | --- | --- |
| `ext_legwear` | 323 | material declaration | 接入 `legwear` slot materials |
| `ext_shoes` | 306 | material declaration | 接入 `shoes` slot materials |
| `ext_weapon` | 286 | material declaration | 接入 `weapon` slot materials |
| `ext_background` | 218 | material declaration | 第一版不接入；后续给 background selector |
| `ext_item` | 114 | material declaration | 接入 `item` materials，并可被 `weapon` slot 使用 |

disabled 类型全集：

```text
leg_wear
ext_weapon
black fingerless gloves
stomach_tattoo magical sapphire
white gloves
aura
multiple_rings
teddy_bear
extend_func_pant
purple_armor
extend_func_nipple
bat_(animal)
hooded_cloak
```

loose 行全集：

```text
neck ribbon
```

disabled 和 loose 默认都不执行，只写 trace 或 warning。

### 触发词全集

后续实现里，触发词只从 registry 读取。character 上的 legacy rule 行只提供 operation，不再决定 trigger。

扫描得到的触发词全集如下。

`legwear` slot 合并 `leg_wear` 和 `barefoot`：

```yaml
legwear:
  legacy_rule_names:
    - leg_wear
    - barefoot
  declaration_names:
    - ext_legwear
  triggers:
    any:
      - ankle socks
      - argyle_legwear
      - barefoot
      - black socks
      - black thighhighs
      - black_pantyhose
      - black_thighhighs
      - bobby_socks
      - brown_thighhighs
      - fishnet_pantyhose
      - frilled_socks
      - garter straps
      - kneehighs
      - loose socks
      - loose_socks
      - pantyhose
      - pink thighhighs
      - purple thighhighs
      - purple_thighhighs
      - single_thighhigh
      - socks
      - stirrup legwear
      - thighhighs
      - toeless legwear
      - white kneehighs
      - white socks
      - white_pantyhose
      - white_socks
      - white_thighhighs
```

`shoes` slot：

```yaml
shoes:
  legacy_rule_names:
    - shoes
  declaration_names:
    - ext_shoes
  triggers:
    any:
      - armored shoes
      - armored_boots
      - barefoot
      - black footwear
      - black_footwear
      - boots
      - crocs
      - crosslaced_footwear
      - footwear
      - gladiator_sandals
      - high heels
      - high_heels
      - highleg
      - loafers
      - mary janes
      - mary_janes
      - okobo
      - sandals
      - shoes
      - sneakers
      - slippers
      - thigh boot
      - thigh boots
      - thigh_boots
      - uwabaki
      - winged_footwear
```

`weapon` slot：

```yaml
weapon:
  legacy_rule_names:
    - weapon
  declaration_names:
    - ext_weapon
    - ext_item
  triggers:
    any:
      - sword
      - weapon
```

`pant` slot：

```yaml
pant:
  legacy_rule_names:
    - extend_func_pant
  declaration_names: []
  triggers:
    any:
      - breasts out
      - lactation
      - leg_wear
      - nipples
      - off shoulder
      - pant
      - pussy
      - sex
      - underwear
      - virgin
    not_any:
      - nude
      - pantyhose
```

`pantyhose` slot：

```yaml
pantyhose:
  legacy_rule_names:
    - extend_func_pantyhose
  declaration_names: []
  triggers:
    any:
      - pantyhose
```

`barefoot` operation slot：

```yaml
barefoot:
  legacy_rule_names:
    - extend_func_barefoot
  declaration_names: []
  triggers:
    any:
      - barefoot
```

`nipple` slot：

```yaml
nipple:
  legacy_rule_names:
    - extend_func_nipple
  declaration_names: []
  triggers:
    any:
      - nipple
```

`boy` slot：

```yaml
boy:
  legacy_rule_names:
    - extend_func_boy
  declaration_names: []
  triggers:
    any:
      - 1boy
```

### Character Operation 边界

最终边界如下：

```text
系统负责：
  - extension type 识别
  - slot 归类
  - 触发词全集
  - disabled / loose 行过滤

character 负责：
  - ext_* material declaration
  - legacy rule line 上的 operation
```

也就是说，后续实现时：

- `leg_wear, <legacy triggers>, include_replace|..., add|...`
- `shoes, <legacy triggers>, include_replace|..., add_after|..., add|...`
- `weapon, <legacy triggers>, include_replace|..., add_after|..., add|...`

这些行中的 `<legacy triggers>` 默认不再用于判断是否触发；只保留后续 operation。

如果需要旧 formula 对比，可通过配置切换：

```yaml
trigger_mode: legacy
```

但生产默认必须是：

```yaml
trigger_mode: fixed
```

### Operation 全量

扫描得到的 operation 类型全集：

| operation | 次数 | 第一版处理 |
| --- | ---: | --- |
| `include_replace` | 1779 | 支持 |
| `add` | 1049 | 支持 |
| `add_after` | 1037 | 支持 |
| `fuzzy_replace` | 44 | 支持 |
| `replace` | 26 | 支持 |
| `add_if_not_exist` | 7 | 支持 |
| `{{braid}}` | 7 | 来自 `after_uc`，不作为 positive operation |
| `red skirt` | 6 | 来自 `after_uc`，不作为 positive operation |

第一版真正需要实现的 positive operations：

```text
include_replace
add
add_after
fuzzy_replace
replace
add_if_not_exist
```

`add_before`、`remove` 在当前 active 扫描中没有出现，可以作为兼容旧 `extend_ext_param` 的可选增强，不作为第一版必需项。
