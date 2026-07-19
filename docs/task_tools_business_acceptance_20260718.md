# Windows 任务工具业务验收记录

## 基本信息

- 日期：2026-07-18
- 分支：`codex/windows-task-tools`
- 验收基线提交：`a0b0012`
- 真实任务目录：`G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f`
- PNG 输入：`G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f\753fa8cc_2256998043_01.png`

## 归档解析

任务目录和 PNG 输入解析到同一个 `task_dir`，Action、Artist 结果一致：

```text
Action: F:\my_project\new\tags_machine\design\动作改2\pn_human_solo_sfw_portrait\00_start_侧脸回眸
Artist: F:\my_project\new\tags_machine\design\画风\114425243_Soft_Akipeco_Official
```

Action 来自 `render_request.json` 的 `meta.node_refs`。Artist 的有效路径来自 `render_request.json` 的 `artist_payload.path`，没有根据任务目录名或 Artist ID 猜测目录。

真实归档同时包含一条无绝对路径的 Artist node ref 和一条有效 `artist_payload.path`。验收中补充了 Launcher 展示层去重：同一 Artist 优先显示有效目录，不改变 Resolver 的原始归档语义。

## SendTo 安装

安装目录：

```text
%LOCALAPPDATA%\PromptAtelier\TaskTools
```

实际创建三项：

```text
Refactor - 打开 Action 目录.vbs
Refactor - 打开 Artist 目录.vbs
Refactor 工具.vbs
```

安装清单记录了当前项目根目录、`.venv\Scripts\pythonw.exe`、配置文件和三项受管文件。文件名的 Unicode code point 经 Python 读取确认正确；PowerShell 工具输出中的个别乱码来自当前终端代码页显示，不是实际文件名转码。

## 快捷操作

通过 CLI 对真实任务执行：

```powershell
uv run python -m tags_machine_core task-tools run open_action_directory --config configs/task_tools.example.yaml -- "G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f"
uv run python -m tags_machine_core task-tools run open_artist_directory --config configs/task_tools.example.yaml -- "G:\ai_auto\20260718\0c012038_2_0_2_d0108c2f"
```

两条命令退出码均为 0，并实际调用 Explorer 打开解析所得 Action、Artist 目录。

随后通过已安装的三个 VBS 文件从独立进程启动同一任务。Action、Artist 快捷项成功启动；统一窗口以独立 `pythonw` 进程运行，窗口标题为 `Refactor 任务工具`。

统一窗口真实 view model：

- Action：`00_start_侧脸回眸`，目录存在。
- Artist：`114425243_Soft_Akipeco_Official`，目录存在。
- `open_action_directory`：enabled。
- `open_artist_directory`：enabled。
- 操作成功后窗口不会主动关闭。

## Placement 同步

临时配置：Action=`quick`，Artist=`launcher`。执行 `sync-sendto` 后：

- Action 独立快捷项保留。
- Artist 独立快捷项移除。
- Launcher 只列出 `open_artist_directory`。
- 原有 `ct.*` 文件哈希变化数量为 0。

随后使用 `configs/task_tools.example.yaml` 再次同步，恢复默认三项。

安装前 SendTo 共 38 个文件，其中 31 个 `ct.*` 文件参与 SHA256 对比。安装、placement 同步和恢复后，这 31 个文件均未被删除或修改。

## 自动化验证

Task 1-6 聚焦回归在 CLI 接入后通过：

```text
58 passed
Ruff: All checks passed
```

Launcher 真实归档去重修复新增回归测试，单文件验证为：

```text
6 passed
Ruff: All checks passed
```

最终门禁重新执行结果：

```text
59 passed in 7.86s
Ruff: All checks passed
git diff --check: passed
```

## 重启持久化

SendTo 入口是 `%APPDATA%\Microsoft\Windows\SendTo` 下的普通 VBS 文件；bootstrap 和安装清单是 `%LOCALAPPDATA%\PromptAtelier\TaskTools` 下的普通文件。它们不依赖当前终端或 Python 进程内存，独立进程启动已通过。

本次没有自动重启用户工作站。Windows 重启不会删除这些普通文件，后续可直接在重启后右键验证，不需要重新安装。
