# Action Knowledge Base v1 业务验收报告

验收日期：2026-08-02

数据目录：`F:/my_project/new/tags_machine/design/动作改2`

配置：`configs/knowledge_base.example.yaml`

## 1. 导入结果

实际执行：

```powershell
uv run python -m tags_machine_core kb import `
  --config configs/knowledge_base.example.yaml `
  --log-level info
```

结果：

| 项目 | 结果 |
| --- | ---: |
| source root | 110 |
| Catalog record | 5391 |
| `new/` record | 1724 |
| `st_*/` record | 3667 |
| alias group | 5391 |
| warning | 7379 |
| 最终首次导入耗时 | 23.08s |
| 最终第二次导入耗时 | 19.25s |

稳定 hash：

```text
sha256:51d2c06b913c67c807573e3bb3e089bfa27d333da8f5032d59709f44392f5863
```

连续两次导入的 hash 完全相同，第二次结果为 `reused_build=true`。

第一次串行原型导入耗时约 203.75s。节点独立读取改为线程池后降至 18-20s，Catalog 内容和排序保持确定性。

## 2. 来源边界

- Catalog 中只有 `new` 和 `st_*` source group。
- `excluded_source_count=0`。
- `--source pn_group` 查询返回 `total=0`。
- 没有自动扫描 `pn_*` 或 `story_*`。
- `new/` 与 `st_*/` 经过相同 Importer、归一化、warning 和查询服务。

## 3. Warning 结果

```text
missing_file         3672
empty_action_prompt  3672
duplicate_content      29
id_mismatch              6
```

当前全部 `st_*` 节点只有 `classify.yaml + tags.txt`，没有 `meta.yaml`；另有少量 `new` 节点缺 meta，因此产生 3672 组 `missing_file + empty_action_prompt`。导入没有被这些节点阻断，也没有从 `tags.txt` 偷偷反推正式 action prompt。

29 条 `duplicate_content` 表示动作 prompt 相同但分类不同，节点仍分别保留。

6 条 `id_mismatch` 来自 `classify.yaml.node_id` 与当前目录名/ref 不一致，例如目录增加了 `_5star` 后缀但 classify 仍保留旧 id；Importer 只告警，不回写源文件。

`kb audit` 已对当前 build 实际执行，退出码为 0。

## 4. Facets 与查询

主要 facet 实际计数：

```text
phase: core=2198, pre=1166, climax=1017, start=675, post=335
domain: sex=3052, body=2004, crotch=1384, mouth=1192,
        breast=747, foot=610, sfw=381, yuri=156
```

实际查询：

| 查询 | total | 结论 |
| --- | ---: | --- |
| `--domain foot --cast 1boy1girl` | 172 | 字段间 AND 生效 |
| `--character-scope foot_detail --clothing specific_outfit` | 85 | scope/clothing 组合过滤生效 |
| `--text footjob` | 25 | 正向 action prompt 全文检索生效 |
| `--source st_rp --phase core` | 14 | 历史分类来源查询生效 |
| `--source pn_group` | 0 | 未配置来源没有进入 Catalog |

当前真实 Catalog 的 `nonempty_negative_records=0`，没有可用于 negative-only 查询的真实节点。聚焦业务夹具使用仅存在于 negative prompt 的 `forbidden-only-token` 验证，搜索结果为 0，证明 negative 不进入正向全文索引。

## 5. Show 与原文保真

已实际检查：

```text
new/20260501_02_双足皮鞋洛丽_2star
new/20260630_0038_动作1
st_rp/12_20240509_1715235532
```

结果：

- `new` 节点返回完整 classify mapping、meta mapping 和 tags 原文。
- `:: mystical fog ::` 等 NovelAI 权重文本在 Catalog positive terms 和 `show.meta` 中原样保留。
- `st_*` 缺 meta 时返回空 meta mapping，并保留完整 classify、tags 以及对应 warning。
- `show` 使用精确 ref，没有模糊回退。

## 6. 随机源数据抽查

使用固定随机种子 `20260802` 抽查 10 个 `new` 和 10 个 `st_*` 节点：

```text
sample_count=20
failure_count=0
```

逐项对比：

- Catalog classification 与源 `classify.yaml` 重新归一化结果一致。
- Catalog positive terms 与源 `meta.yaml.tags.action` 重新归一化结果一致。
- Catalog character scope 与源 `meta.yaml.character_scope` 一致。

## 7. Alias

真实数据本次没有三个源文件内容完全相同的物理节点，因此 `record_count` 与 `alias_group_count` 都是 5391。聚焦夹具验证了：

- 完全相同内容归入同一 alias group。
- canonical ref 使用 POSIX ref 字典序第一项。
- 默认搜索隐藏 alias，`--all-sources` 可展开物理来源。

## 8. 源目录只读确认

导入前后 `design` Git 状态一致：

```text
 M .gitignore
 M 动作改2
 M 画风
 M 角色
```

这些是验收前已经存在的用户变更。Knowledge Base 导入没有新增、删除或回写 `design/动作改2` 文件。

## 9. 自动化验证

```text
Knowledge Base 聚焦测试：10 passed
既有 core 基线：574 passed, 34 subtests passed
```

全仓无路径限定的 `pytest` 会误收集独立 `tools/publishing_workspace` 和嵌套 `vendor/ai-image-gateway` 测试，产生既有包边界/同名模块收集错误；本次使用主项目正式 `tests/` 作为 core 门禁。

## 10. 结论

Action Knowledge Base v1 主链路已通过真实 `new + st_*` 数据验收：全量导入、稳定版本发布、warning 宽进、facets、组合搜索、正向全文检索、精确 show 和源目录只读均符合 v1 设计。
