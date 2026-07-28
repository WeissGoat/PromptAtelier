# Publishing Workspace 迁移说明

Publishing Workspace 已从 `tags_machine_core` 提取为独立项目：

```text
tools/publishing_workspace/
```

旧命令：

```powershell
uv run python -m tags_machine_core publish ...
```

已删除，不提供兼容转发。请在独立项目目录中使用：

```powershell
uv run publishing-workspace ...
```

旧工作区数据不需要重新导入。独立工具首次打开旧工作区时会自动执行一次性升级：

- `workspace.yaml`：先生成 `workspace.yaml.tags-machine-core-v1.bak`，再把 `tags-machine-core.publish-workspace/v1` 更新为 `publishing-workspace.workspace/v1`，其他配置键保持不变。
- `catalog.sqlite`：在事务内保留现有资产、导入与导出状态，并为 `schema_meta` 补充独立项目 schema id；中断后可以继续恢复。

该升级为单向迁移，重要工作区建议先备份 `workspace/` 目录。

详细使用方式见 `tools/publishing_workspace/README.md`。
