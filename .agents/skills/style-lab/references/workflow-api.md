# 两阶段 API

路径相对于 `/api/style-lab/workspaces/{w}`。请求和响应使用 UTF-8 JSON；图片/组/配方 id 均从实际响应读取。

## 准备

- `GET /analysis-context?offset=0&limit=20`：按投稿分页；有 posts/images/probs、next_offset、custom_groups、已有 recipes。图片记录附 `problems`，原始完整参数仍通过 `/images/{i}` 读取。
- `GET /custom-groups`：revision、groups、membership（image_id → 叶子组 id）、locked_image_ids、ungrouped_image_ids。计数、日期、可用样本由后端计算。
- `PUT /custom-groups`：带当前 revision 的完整文档，以及 `actor:agent`。Web 手动编辑使用 actor:user；Agent 不可解除人工锁定。
- `POST /recipes`：`{image_id, draft:true, source_group:{kind:custom,id:cg_...}}` 取初始完整草稿。完成实际划分，不直接把初始 subject 当成配方提取结果。
- `POST /recipes/preview`：`{recipe:完整对象}`，不出图。
- `POST /preparations`：下面结构；稳定请求 id 用于续做，不覆盖已有配方。

```json
{
  "id": "prep_task_001",
  "rules_version": "style-lab-analysis/v1",
  "summary": "投稿级分析总结",
  "custom_groups": {
    "revision": 0,
    "groups": [
      {"id":"cg_family","name":"清晰漫画","reason":"稳定画师组合","evidence_strength":"strong","updated_by":"agent"},
      {"id":"cg_main","parent_id":"cg_family","name":"基础栈 · 无 vibe"}
    ],
    "membership": {"真实图片id":"cg_main"},
    "locked_image_ids": []
  },
  "recipes": []
}
```

recipes 填从 API 草稿实际改好的完整对象，各配方有固定 id、source_image_id、source_group、stage/edit、locked/true 和 preparation/status（ready 或 needs_review）。同时保留其他已有字段。上面空数组只演示结构，不代表完成建配方。组字段还有 notes、kind（style/review/archive）、evidence_image_ids、representative_image_id、order、locked。

再次分析时提交包含已有组/人工锁定项的完整组文档，不能只用新组数组替换整份。新图片原归属留空则未分组。group.id 以 `cg_` 开头，不能复用自动画风的 g1。叶子组才能直接放图片，父组成员自动汇总。

准备结果有 id、status（succeeded/partial）、results（每个 recipe_id 的 created/failed）、groups_applied。`GET /preparations/{id}` 可恢复；partial 重发**原请求**补未完成项，改变分析内容时使用新任务 id。revision 冲突重新读取合并，不覆盖人工修改。

## 测试

先读取当前 `/api/style-lab/shelf`（或 helper materials）与选定配方。`POST /test-plans` 请求：

```json
{
  "recipe_ids": ["r1"],
  "group_ids": [],
  "include_materials": true,
  "variant_limit": 3,
  "variants": []
}
```

variants 每项 `{recipe_id:r1,label:角色A与动作B,recipe:完整变体对象}`。变体和基准的 id/source_image_id/画风签名必须相同；测试内容不保存回配方。materials 及 exclusions 必须匹配本次素材架。每个变体最终请求必须不同。

group_ids 只接受自定义组 id，父组展开关联配方；和 recipe_ids 合并去重。仅测前两项时明确 `include_materials:false`，或 variant_limit:0。只有用户允许在原参漂移后仍继续时才传 `continue_on_drift:true`。

创建返回 id、status、recipe_ids、shelf 快照、items（各项 preview/原种子/生成尺寸）、estimated_count/reuse_count。不出图。素材架有选择但没提供变体时返回 awaiting_content，需要准备后新建计划；不要直接开始，也不要悄悄取消素材测试。

- `POST /test-plans/{id}/start`：明确执行；成功/运行中计划重复开始会返回同一计划，其他终态可继续未完成项。
- `GET /test-plans/{id}`、`GET /test-plans`：进度与历史。items 含 status、run_id、results、reused、error、blocks_following。
- plan 终态 succeeded/partial/failed/cancelled/interrupted。原参不 match 默认暂停该来源后续项；单张配方图是 reference 对照。
- 源图/完整配方内容变化（即便版本没增加）在 start 返回 409，需重新建立计划。
- 等待超时继续查原 id，不重建/重提。返回路径用原有工作区 file 接口读取，或本地绝对路径打开。

helper 快捷命令：`prepare w --body-file ...`、`start-plan w id`、`wait-plan w id --timeout 45`。准备不生成，创建计划不生成，只有 start-plan 执行。
