# 示例工作区

`workspace/` 是已经初始化的空公共素材工作区，可直接用于试运行：

```powershell
uv run publishing-workspace import examples/workspace <图片目录或 NeeView.nvpls>
uv run publishing-workspace export examples/workspace --log-level info
```

Git 保存 `workspace.yaml` 和目录骨架。SQLite Catalog、导入快照和导出结果属于运行状态，不纳入版本管理。
