# Action 分类解析

Publishing Workspace 在分类阶段区分两种 action：

- 动态分类 action：位于 `动作改2/new`，通过最新的
  `category_view_manifest.json` 获取当前 `action_group`；
- 独立分类 action：位于 `st_*` 等分类目录，且没有映射到 `new`，保留原始
  action 和 group。

Catalog 保存的 PNG 原始节点不会被修改。`classify` 时才计算分类投影，因此
更新 manifest 后不需要重新导入图片。

## 配置

```yaml
classification:
  hierarchy:
    - artist
    - character
    - action_group
    - action
  missing_value: unknown
  skip_missing: false
  action_resolution:
    enabled: true
    design_root: F:/my_project/new/tags_machine/design
    action_root_name: 动作改2
```

`design_root` 可以不配置。对于图片中带绝对 action ref 的情况，系统会从
ref 向上查找 `category_view_manifest.json`；没有 ref 或只有旧版 action 名称
时，建议配置该路径。

## 解析结果

```text
generated_new       -> 使用 new action，并读取最新 action_group
standalone_category -> 保留 st_* 等独立 action/group
unresolved           -> 保留原始 action/group，并记录 warning
missing              -> 使用 unknown 占位值
```

默认 `skip_missing: false`，以上所有情况都会生成分类视图。只有显式开启
`skip_missing: true`，缺少分类维度的图片才会被跳过。
