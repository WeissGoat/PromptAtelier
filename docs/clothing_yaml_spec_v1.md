# Clothing YAML 规范 v1

clothing 节点用于描述角色的独立服装覆盖层（outfit overlay）。它作为可跨角色复用的服装素材库，在 compose 时或 batch 阶段动态替换角色的内置服饰 sections。

## 核心边界

clothing 节点应该回答：

```text
这套服装有哪些部件（上衣、裙子、鞋子、袜子、配饰等）？
穿这套衣服时有哪些负向约束（如避免长袖、避免其他服饰）？
```

它不应该回答：

```text
谁穿这套衣服（角色的发型、眼睛等身体特征保留在 character 节点中）？
画面发生在哪里（属于 background）？
角色的动作和姿态是什么（属于 action）？
```

## 文件名与目录

推荐存放路径：

```text
design/服装/<clothing_id>/meta.yaml
```

文件名推荐固定为：

```text
meta.yaml
```

## 最小结构

```yaml
schema: tags-machine.clothing/v1
kind: clothing
id: school_uniform_summer
name: "夏季校服"

tags:
  role:
    - "{{alternative_clothing}}"
  upper_clothes:
    - white_shirt
    - short_sleeves
    - sailor_collar
  lower_clothes:
    - blue_skirt
    - pleated_skirt
  legwear:
    - white_knee_highs
  shoes:
    - brown_loafers

negative_prompt:
  - long_sleeves
```

## 字段说明

### `schema`

固定为：

```yaml
schema: tags-machine.clothing/v1
```

### `kind`

固定为：

```yaml
kind: clothing
```

### `id`

服装的全局唯一标识。

### `tags`

服装包含的 sections。

1. **`role`（身份与角色标签合并）**：
   - 服装节点默认携带 `role: ["{{alternative_clothing}}"]`。
   - 在应用覆盖（overlay）时，对 `role` section 采取**合并与去重（Merge & Dedupe）**机制：优先保留角色原节点的 `role` 标签（如 `cat_girl`, `1girl`），并将服装节点的 `role`（如 `{{alternative_clothing}}`）追加在后，绝不覆盖抹除角色原有的种族或身份特征。
   - 若角色原节点未定义 `role`，则直接使用服装节点的 `role`。

2. **`OUTFIT_SECTION_KEYS`（衣着全量覆盖）**：
   以下衣装 sections 会自动清空角色原节点对应字段并由 clothing 节点全量替换：
   - `clothes`
   - `upper_clothes`
   - `lower_clothes`
   - `full_body_clothes`
   - `outfit`
   - `uniform`
   - `dress`
   - `shirt`
   - `skirt`
   - `jacket`
   - `capelet`
   - `legwear`
   - `shoes`
   - `feet`

3. **其他 Sections（如 `accessories`、`headwear`、`props` 等）**：
   clothing 节点中定义的其他 section 会被覆盖/追加到角色的 tags 中。

### `negative_prompt`

穿戴此服装时的负向提示词，在应用覆盖时会自动合并到角色的 `negative_prompt` 中。
