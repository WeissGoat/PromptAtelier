# 投稿任务、选择集合与打包验收报告

验收日期：2026-08-02

对应设计：[2026-08-01-publishing-task-selection-packaging-design.md](./2026-08-01-publishing-task-selection-packaging-design.md)

对应实现计划：[2026-08-01-publishing-task-selection-packaging-implementation.md](../plans/2026-08-01-publishing-task-selection-packaging-implementation.md)

## 验收范围

本次验收覆盖单次投稿任务的完整链路：

- `all / post / cover` 三套选择集合
- 真实图片物化和当前目录扫描
- PNG 参数清理
- 处理缓存
- 原子 build
- 输出目录和 ZIP
- 集合关系 warning
- Operation 不可用时的失败隔离

完整 NeeView 收藏列表不作为投稿任务验收输入。公共 workspace 可以保存大规模素材，单次 task 使用本次人工筛选后的子集。

## 真实任务验收

任务：`G:\ai_publish\tasks\acceptance_20260802_packaging`

选择数量：

```text
candidates = 10
all        = 10
post       = 3
cover      = 1
```

构建：`20260802_021649_8516cd`

结果：

- `output/all` 输出 10 张图片
- `output/post` 输出 3 张图片
- `output/cover` 输出 1 张图片
- 生成 `all.zip`、`post.zip`、`cover.zip`
- ZIP 内只包含对应集合的 PNG 文件
- ZIP 不包含 manifest、history、snapshot 或本地路径
- 输出 PNG 的 Pillow `info` 为空，prompt、seed 等内部参数已清除
- manifest 状态为 `success`
- warnings 和 errors 均为空

## 边界验收

### 集合关系 warning

任务：`G:\ai_publish\tasks\acceptance_20260802_warning`

配置为 `all=1`、`post=3`，其中两张 post 图片不在 all 中。

构建成功，manifest 记录 2 条 `post_not_in_all` warning，没有阻止构建。

### 构建失败隔离

任务：`G:\ai_publish\tasks\acceptance_20260802_failure`

启用未配置 adapter 的 `mosaic` Operation，构建按预期失败：

```text
mosaic 已启用，但没有配置 adapter
```

失败后正式 build 数量为 0，临时 build 目录数量为 0，未污染正式输出。

## 自动化验证

```text
60 passed in 10.10s
```

CLI 帮助中包含 `task` 命令。`git diff --check` 仅发现工作区已有的 `examples/batches/blackboard_action_new.yaml` 尾随空格，本次变更文件没有该问题。

## 结论

上一轮投稿任务与打包设计的第一阶段实现和业务验收已完成。`refresh`、公共 Catalog 到任务的直接筛选交互、resize/watermark 等后续功能不属于本阶段。
