# 双页面与投稿导出业务验收

## 范围

本验收覆盖双页面拆分（`/calendar` 日历排期页、`/library` 素材库与投稿管理页）、Submission 投稿模型持久化与更新、all/post/cover 自动补齐与上下移动、后台导出进度轮询、PNG 清除参数、打码集成与打开导出目录、以及日历页面关联跳转与拖拽改期。

自动化验收测试：

```powershell
cd F:\my_project\new\tags_machine\refactor\tools\publishing_workspace
uv run pytest tests/test_two_pages_acceptance.py tests/test_legacy_compatibility.py -q
```

## 核心验收链路

### 1. 素材库分页检索与筛选
- 启动 Web 服务后访问 `/library`；
- 通过 `/api/library/assets` 瀑布流滚动加载（初始 60 项），图片卡片利用 `aspect-ratio` 预占位防止布局抖动；
- 支持按 Import 快照、Artist / Character / Action 节点及 `classify.yaml` Facets 多维度过滤。

### 2. Submission 保存与 Task 生成
- 勾选素材并加入 `all` 集合；
- 用户保存投稿：自动补齐 `post`（默认等于 `all`）与 `cover`（默认等于 `post[0]`）；
- 系统生成 `tasks/<task_id>/task.yaml` 与 `submission.yaml`；
- 更新已有投稿时，采用临时 Staging 目录物化，保留历史 `selection/history`，并实现原子交换与全量回滚。

### 3. 单 Worker 队列后台导出
- 点击“导出发布包”，调用 `POST /api/submissions/{task_id}/exports` 进入单 worker 线程池；
- 前端轮询 `/api/export-jobs/{job_id}`，实时呈现进度条、阶段（validate / process / finalize）与当前处理文件名；
- 导出完成后调用 `POST /api/export-jobs/{job_id}/open-output`，安全验证并调起系统资源管理器打开构建输出目录。

### 4. 日历页面关联与拖拽
- 访问 `/calendar`，月历仅聚焦排期编排；
- 在日历中关联已有 Submission 任务，点击卡片直达素材库对应投稿；
- 拖拽卡片调整日期，保持原有时间槽；
- 历史 inline 散图排期标注散图标识，进入素材库保存后懒转换为正式 Task。

## 页面人工检查要点

1. 访问 `http://127.0.0.1:61302/calendar`，验证日历排期与月份切换。
2. 访问 `http://127.0.0.1:61302/library`，验证素材瀑布流无限滚动与筛选。
3. 勾选素材新建投稿并保存，确认 `tasks/` 目录生成对应任务与 `submission.yaml`。
4. 点击导出，观察进度条与阶段文件变化，完成后点击“打开导出目录”成功弹出文件夹。
5. 回到日历页，选择新建的任务进行排期，拖拽改变日期验证保存。
