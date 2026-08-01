# 示例工作区

`workspace/` 是已经初始化的空公共素材工作区，可直接用于试运行：

```powershell
uv run publishing-workspace import examples/workspace <图片目录或 NeeView.nvpls>
uv run publishing-workspace export examples/workspace --log-level info
```

Git 保存 `workspace.yaml` 和目录骨架。SQLite Catalog、导入快照和导出结果属于运行状态，不纳入版本管理。

## 投稿任务示例

`task/` 下的 YAML 是投稿任务配置示例。任务创建后，直接编辑 `tasks/<task_id>/selection/all`、`selection/post` 和 `selection/cover` 中的图片即可进行二次筛选。

```powershell
uv run publishing-workspace task create G:\ai_publish 20260801_demo --candidates E:\NeeView41.3\Profile\Playlists\demo.nvpls
uv run publishing-workspace task status G:\ai_publish 20260801_demo
uv run publishing-workspace task build G:\ai_publish 20260801_demo
```

构建结果在 `tasks/20260801_demo/builds/<build_id>/`，包括三套输出目录、内部 manifest 和可选 ZIP。删除、重命名图片后重新 build，会以当前目录为准。
