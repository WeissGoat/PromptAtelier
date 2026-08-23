# 节点身份归一化

Publishing Workspace 需要同时读取真实节点目录和旧项目生成的快捷方式节点。
这两类名称可能不同，但它们代表同一个角色，因此归一化发生在 Reader 之后、
分类投影之前。

## 当前默认规则

只处理 `character` role：

1. 删除名称末尾的 ` - 快捷方式`。
2. 删除紧邻 `danbooru_` 前的数字编号和可选 `a`，例如 `1a`、`2a`。
3. 归一化后按不区分大小写的值去重。

例如以下两个值会投影为同一个分类节点：

```text
1adanbooru_akemi_homura_暁美ほむら _魔法少女 - 快捷方式
danbooru_akemi_homura_暁美ほむら _魔法少女
```

结果为：

```text
danbooru_akemi_homura_暁美ほむら _魔法少女
```

## 数据保留原则

`ImageNodeInfo.nodes`、Catalog 的 `asset_nodes` 和图片原始元数据都保持原值。
归一化只由 `ImageNodeInfo.values_for()` 和 `AssetRecord.node_projection()` 使用，
因此分类目录统一，同时仍可以根据原始 `id/ref` 追溯旧链接来源。

## 扩展显式别名

代码提供 `NodeIdentityNormalizer(aliases=...)` 作为后续扩展入口：

```python
normalizer = NodeIdentityNormalizer(
    aliases={("character", "old_name"): "canonical_name"}
)
```

当前默认分类使用内置归一化器；不需要为每个已知快捷方式手写映射表。
