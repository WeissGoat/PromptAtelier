# 动作知识库使用说明

Action Knowledge Base 将 `design/动作改2` 的动作节点导入为稳定 Catalog，供 Agent、Batch 和后续图集编排查询。它不参与提示词拼接和生图，也不会修改源节点。

## 数据范围

默认配置见 `configs/knowledge_base.example.yaml`：

- `new/`：正式新动作来源。
- `st_*/`：历史分类动作来源，与 `new/` 使用完全相同的扫描、warning 和查询规则。
- `pn_*`、`story_*`：默认不导入；需要时显式新增 source 配置。

`path` 指定一个固定一级目录，`pattern` 只匹配 `action_root` 第一层目录。两者必须且只能填写一个。`enabled: false` 会完全关闭对应来源。

## 导入

```powershell
uv run python -m tags_machine_core kb import `
  --config configs/knowledge_base.example.yaml `
  --log-level info
```

Catalog 默认写入 `cache/action_catalog`：

```text
cache/action_catalog/
  current.json
  builds/
    sha256-<hash>/
      manifest.json
      actions.jsonl
      warnings.jsonl
```

Windows 路径不能包含冒号，因此 build 目录使用 `sha256-<hash>`；JSON 中的正式 `catalog_hash` 仍使用 `sha256:<hash>`。

坏节点不会中断全量导入。缺文件、YAML 解析失败、枚举异常和分类冲突会写入 `warnings.jsonl`，日志默认只输出按 warning code 汇总的数量。

## 查询

先查看可用分类及计数：

```powershell
uv run python -m tags_machine_core kb facets --config configs/knowledge_base.example.yaml
```

组合查询时，不同字段是 AND，同一字段逗号分隔值是 OR：

```powershell
uv run python -m tags_machine_core kb search `
  --config configs/knowledge_base.example.yaml `
  --domain foot,body `
  --cast solo `
  --character-scope foot_detail `
  --limit 20
```

全文查询只搜索 `id/name/description/tags.action` 的正向词，不搜索 negative prompt：

```powershell
uv run python -m tags_machine_core kb search `
  --config configs/knowledge_base.example.yaml `
  --text "foot focus"
```

默认每个内容完全相同的 alias group 只返回稳定代表。需要查看全部物理来源时添加 `--all-sources`。

查看一个精确 ref 的原始内容：

```powershell
uv run python -m tags_machine_core kb show `
  --config configs/knowledge_base.example.yaml `
  "new/20260501_02_双足皮鞋洛丽_2star"
```

`show` 会读取并返回完整 `classify.yaml`、`meta.yaml` 和原始 `tags.txt`，保留 NovelAI 权重与正负面 prompt。ref 不存在时命令失败，不进行模糊猜测。

查看 warning：

```powershell
uv run python -m tags_machine_core kb audit --config configs/knowledge_base.example.yaml
```

所有命令默认输出 JSON，也可添加 `--format yaml`。结构化结果写 stdout，日志写 stderr，Agent 可以直接解析 stdout。
