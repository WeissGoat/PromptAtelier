# Windows 任务便捷工具

这套工具用于从批量生图归档快速跳回关联的 Action、Artist 节点目录。它只读取归档，不修改提示词、生图参数或节点内容。

## 支持的输入

- 单个任务目录。
- 任务目录中的 PNG 图片。
- 任务目录中的 JSON 文件。
- Explorer 多选的多个任务、图片或 JSON。

解析器从输入路径向上寻找最近的任务归档目录，不递归扫描子目录，也不根据任务目录名猜节点。Action 优先读取 `render_request.json` 的 `meta.node_refs`；Artist 优先读取 `artist_payload.path`。`prompt_bundle.json` 只作为补充来源。

## 安装

在 `refactor` 项目目录运行：

```powershell
uv run python -m tags_machine_core task-tools install-sendto --config configs/task_tools.example.yaml
```

也可以使用脚本：

```powershell
.\scripts\install_task_tools.ps1 -Mode install -Config .\configs\task_tools.example.yaml
```

安装后，Windows Explorer 的“发送到”菜单会出现：

- `Refactor - 打开 Action 目录`
- `Refactor - 打开 Artist 目录`
- `Refactor 工具`

前两个是高频快捷项；`Refactor 工具` 会打开统一窗口，显示任务和关联资源，再选择操作。

## 配置

```yaml
schema: prompt-atelier.task-tools/v1
log_level: error

operations:
  open_action_directory:
    enabled: true
    placement: both
    order: 10
```

`placement` 的含义：

- `quick`：只创建独立 SendTo 快捷项。
- `launcher`：只显示在统一工具窗口。
- `both`：同时显示在两个位置。

`enabled: false` 会完全禁用该操作。`label` 可覆盖显示名称，`order` 控制统一窗口中的排序。未提供配置时使用代码注册的默认值。

配置修改后同步：

```powershell
uv run python -m tags_machine_core task-tools sync-sendto --config configs/task_tools.example.yaml
```

卸载：

```powershell
uv run python -m tags_machine_core task-tools uninstall-sendto
```

安装器只删除 `%LOCALAPPDATA%\PromptAtelier\TaskTools\install.json` 中记录的文件，不会扫描或清理其他 SendTo 项，现有 `ct.*` 文件会保留。

## 直接运行

```powershell
uv run python -m tags_machine_core task-tools run open_action_directory -- "G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f"

uv run python -m tags_machine_core task-tools launcher -- "G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f"
```

多个路径放在 `--` 后依次传入。

## 错误与日志

- 项目路径或 `.venv\Scripts\pythonw.exe` 不存在：启动器显示 Windows 错误消息。
- 输入不是任务归档：提示未找到归档。
- Action 或 Artist 路径缺失：快捷操作报错；统一窗口显示禁用原因。
- 默认日志级别为 `error`，日志位于 `%LOCALAPPDATA%\PromptAtelier\TaskTools\logs\task-tools.log`。

## 扩展操作

新增操作时，在代码的 `OperationRegistry` 中注册固定 handler、目标资源类型、默认 placement 和顺序。YAML 只能调整已注册操作的启用状态和展示方式，不能指定任意 Python、PowerShell 或可执行文件。

当前业务验收目录：`G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f`。
