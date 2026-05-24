# Character YAML 规范 v1

本文档确认角色节点的轻量 YAML 结构。当前结论是：`character` 节点只作为角色提示词素材事实库，不承载通用拼接规则。

## 结论

角色节点继续使用现在已经在 `design/角色/.../meta.yaml` 中落地的结构：

- 文件名：`meta.yaml`
- schema：`tags-machine.character/v1`
- 正向素材字段：`tags`
- 负向素材字段：`negative_prompt`
- 不写 `rules`
- 不写 `profiles`
- 不写 `prompt.positive`
- 不写 `include_scopes` / `exclude_scopes`

也就是说，角色 YAML 只回答一个问题：这个角色有哪些可用素材标签。

动作镜头如何选择这些标签，是 composer 的统一策略，不是 character 节点自己的职责。

## 最小结构

```yaml
schema: tags-machine.character/v1
kind: character
id: danbooru_akemi_homura_暁美ほむら_魔法少女
character_id: akemi_homura
variant: 魔法少女
negative_prompt: []

tags:
  character:
    - akemi_homura
  copyright:
    - mahou_shoujo_madoka_magica
  role:
    - magical_girl
  hair:
    - black_hair
  eyes:
    - purple_eyes
  head_accessories:
    - red_ribbon
  upper_clothes:
    - white_shirt
  lower_clothes:
    - purple_skirt
  full_body_clothes: []
  handwear: []
  legwear:
    - black_thighhighs
  footwear:
    - shoes
  accessories: []
  weapons:
    - shield
  props: []
  wings: []
  tail: []
  ears: []
  body: []
  feet: []
  hands: []
  extra: []
```

空 section 可以省略。保留常用空 section 也可以，取决于批量生成和人工编辑时哪个更方便。

## 字段说明

### `schema`

固定为：

```yaml
schema: tags-machine.character/v1
```

这是角色专用轻量格式，不等同于通用 `tags-machine.node/v1`。

### `kind`

固定为：

```yaml
kind: character
```

### `id`

具体节点 id，通常使用角色节点文件夹名。

同一个人物的不同形态、服装、来源名，可以有不同 `id`。

### `character_id`

同一底层人物的稳定 id。

例如这些节点可以共享同一个 `character_id`：

- 校服 Homura
- 魔法少女 Homura
- 恶魔 Homura

```yaml
character_id: akemi_homura
```

### `variant`

当前节点描述的角色变体，例如：

- `常服`
- `校服`
- `魔法少女`
- `恶魔`
- `泳装`
- `幼年`
- `成年`

### `tags`

正向提示词素材，按语义 section 分组。

这里叫 `tags`，不是 `prompt`，原因是：这些内容还不是最终提示词，而是等待 composer 根据 action 的 `character_scope`、style 等上下文选择的素材库。

最终完整提示词由 `PromptBundle.prompt.positive` 表示。

### `negative_prompt`

当前角色节点自带的负向提示词素材。

它不是最终完整负向提示词，而是会被 composer 合并到 `PromptBundle.prompt.negative` 的角色级负向素材。

示例：

```yaml
negative_prompt:
  - nipples
  - extra fingers
```

当前阶段保留这个字段名，不改成 `negative_tags`，因为它已经在 `design` 中落地，并且对 agent 和生图工作流都足够直观。

## 推荐 tags section

### 身份与来源

- `character`：角色名 prompt tag。
- `copyright`：作品、系列、来源。
- `role`：角色身份或职业，如 `magical_girl`、`maid`、`idol`。

### 头部与脸部

- `hair`：发色、发长、发型。
- `eyes`：眼睛颜色、稳定眼部特征。
- `face`：脸部稳定特征。
- `head_accessories`：发饰、帽子、头饰、发夹。
- `ears`：动物耳、尖耳等。

### 服装与穿戴

- `upper_clothes`：上衣、外套、上半身服装。
- `lower_clothes`：裙子、裤子、下半身服装。
- `full_body_clothes`：连衣裙、连体衣等不方便拆成上下半身的服装。
- `handwear`：手套、袖套、腕部穿戴。
- `legwear`：袜子、裤袜、过膝袜、腿部饰品。
- `footwear`：鞋、靴、凉鞋、高跟鞋。

### 身体、局部与道具

- `body`：肤色、体型、稳定身体特征。
- `feet`：脚部特征，例如特殊脚饰、脚部纹身、bare feet 类素材。
- `hands`：手部特征。
- `accessories`：项链、领结、腰带、包等一般饰品。
- `weapons`：武器。
- `props`：非武器道具。
- `wings`：翅膀。
- `tail`：尾巴。
- `extra`：暂时不好归类但属于角色素材的 tag。

## 不写进 character 的内容

以下内容不建议放进 character `meta.yaml`：

- 通用过滤规则。
- 镜头规则。
- `profiles`。
- `rules`。
- `prompt.positive`。
- `include_scopes` / `exclude_scopes`。
- action 相关姿势。
- style / artist / quality tags。
- NovelAI / ComfyUI / SD 参数。

原因是这些信息不是角色事实，而是组合策略或后端策略。

例如，不要这样写：

```yaml
tags:
  eyes:
    - tag: purple_eyes
      exclude_scopes: [foot_detail]
```

应该只写事实：

```yaml
tags:
  eyes:
    - purple_eyes
```

然后由 composer 统一决定：当 action 是 `foot_detail` 时，默认不取 `eyes` section。

## Composer 策略示例

下面这类规则属于 composer，而不是 character YAML：

```yaml
foot_detail:
  include_character_sections:
    - character
    - copyright
    - body
    - feet
    - legwear
    - footwear
  suppress_character_sections:
    - hair
    - eyes
    - face
    - head_accessories
    - upper_clothes
    - full_body_clothes
```

这个例子只是解释职责边界，不表示要写进每个角色节点。

## 与 action 的关系

角色节点不知道自己会被用于什么镜头。

动作节点负责声明角色素材裁剪视角，例如：

```yaml
character_scope: foot_detail
```

composer 根据 action 的 `character_scope` 选择 character section。

所以组合链路是：

```text
character tags section
+ action character_scope
+ composer policy
-> PromptBundle.prompt.positive
```

## Tag 写法

角色素材建议保持 Danbooru prompt tag 风格：

```yaml
- black_hair
- purple_eyes
- high_heels
```

如果源 tag 本身包含权重或特殊字符，保留原文并加引号：

```yaml
- "{purple_skirt}"
- "[[bubble_skirt]]"
- "dark_orb_(madoka_magica)"
```

含有 `{}`、`[]`、`:`、`#`、`,` 或首尾空格的字符串建议加引号，避免 YAML 解析歧义。

## 旧 `tags.txt` 迁移

旧项目的角色 `tags.txt` 常见形态是前几行逗号分隔素材，例如：

```text
tachibana_kanade,angel_beats!
yellow_eyes,grey_hair,hairband
blazer,pleated_skirt,thighhighs
shirasaya
=
leg_wear, stirrup legwear|toeless legwear
shoes, shoes|boots|loafers
```

v1 提供保守迁移命令：

```powershell
uv run python -m tags_machine_core migrate-character-tags `
  F:\my_project\new\tags_machine\design\角色\danbooru_angel_beats_207\danbooru_715_tachibana_kanade_立華かなで `
  --variant school_uniform `
  --output migrated\nodes\characters\tachibana_kanade\meta.yaml
```

迁移策略：

- 第一行第一个 tag 进入 `tags.character`，后续 tag 进入 `tags.copyright`。
- 其余正向 tag 按关键词分入 `hair`、`eyes`、`head_accessories`、`upper_clothes`、`lower_clothes`、`legwear`、`footwear`、`weapons` 等 section。
- 无法稳定判断的 tag 会进入 `unclassified`，方便人工复核；composer 当前不会把 `unclassified` 纳入局部镜头策略。
- `origin_uc`、`uc`、`negative_prompt`、`after_uc`、`after_negative_prompt` 会提升为角色级 `negative_prompt`。
- `=` 后旧项目的 `leg_wear`、`shoes` 等替换规则只保留在 `legacy.raw_sections`，不提升为 `rules`、`profiles` 或 scope 规则。

迁移工具不会修改旧项目目录；只有传入 `--output` 时才写出新 YAML。迁移结果必须人工复核 tags 分组，尤其是服装、道具、身份称号和旧规则混杂的节点。

## 当前冻结点

character v1 暂时冻结以下决策：

- 使用 `meta.yaml`。
- 使用 `tags` 表示正向素材分组。
- 使用 `negative_prompt` 表示角色级负向素材。
- 不把通用 section 过滤规则写进 character。
- composer 负责把 character tags 渲染成最终 prompt。

后续讨论重点应继续用旧项目回归样例校准 `character_scope` 策略。
