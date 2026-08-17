# 月度投稿计划业务验收

## 范围

本验收覆盖月历计划、已有 task 图集、inline 散图、同日多时间槽、`all/post/cover` 独立顺序、到期构建、失败隔离和重复执行幂等。

测试使用少量临时图片和临时 task，不把公共 workspace 的大目录作为一次投稿输入。测试入口：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest tests/test_monthly_calendar_acceptance.py -q
```

## 用例

测试建立一个 `2026-09` 计划：

| entry | 内容 | 时间 | 验证 |
| --- | --- | --- | --- |
| `inline-entry` | 3 张 Catalog 图片，其中 `all`、`post`、`cover` 顺序不同 | 2026-09-05 20:00 | inline 物化和独立顺序 |
| `task-entry` | 1 个已有 task 图集 | 2026-09-05 21:00 | task build |
| `inline-late-entry` | 1 张 Catalog 图片 | 2026-09-06 20:00 | 同计划另一时间槽 |

计划锁定后执行：

```text
run_due -> inline-entry completed
        -> task-entry completed
        -> inline-late-entry completed
run_due -> []
```

验收检查以下结果：

- 三个 entry 均有 `ExecutionRecord.status=completed` 和 `build_id`；
- inline build 的 `all/post/cover` 数量和顺序与计划一致；
- inline 临时 task 目录已清理，正式 build 保留在 `plans/2026-09/executions/`；
- task build 保留在原 task 的 `builds/`，结构与手工 `task build` 一致；
- 第二次 `run_due` 不生成新的成功 execution；
- 计划 revision、执行记录和 build manifest 可重新读取。

`tests/test_plan_executor.py` 另外覆盖了一条失败 task 不阻塞成功 task 的失败隔离用例；`tests/test_schedule_api.py` 覆盖页面入口、任务列表、revision 冲突和素材检索 API。

## 页面验收

启动：

```powershell
uv run publishing-workspace web G:\ai_publish --host 127.0.0.1 --port 61300 --log-level info
```

人工检查：

1. 创建空计划，确认默认日期为空。
2. 搜索 import 中的图片，勾选素材后加入 `post`。
3. 选择 `all`、`post`、`cover` 标签分别调整顺序，保存后重新加载确认顺序保持。
4. 同一天新建两个不同时间的投稿。
5. 将投稿卡片拖到另一天，确认时间保持不变。
6. 选择已有 task，保存后确认日历显示“任务”。
7. 点击素材缩略图确认大图预览接口可用。
8. 锁定计划，确认编辑、删除和拖拽被禁用；解锁后恢复。

页面不提供自动排期和复制投稿入口。
