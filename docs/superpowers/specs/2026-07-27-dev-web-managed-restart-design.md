# Dev Web 受控重启设计

## 目标

`scripts/dev_web.py` 在 Windows 上可靠停止上一轮 PromptAtelier Web 前后端及其子进程，避免 uvicorn reload、Vite 和 esbuild 遗留监听端口；同时不得误杀其他项目或系统服务。

## 行为

- 默认 `uv run python scripts/dev_web.py`：启动前先执行受控清理，再启动新的后端和前端。
- `--stop`：仅停止旧的受控实例并退出，不启动新服务。
- 成功启动后将前端、后端的直接子进程 PID 与端口写入 `runtime/dev_web.json`。
- 正常退出、启动失败或 `--stop` 成功后删除状态文件。

## 进程识别与安全边界

1. 优先读取状态文件。若其中 PID 仍存在，Windows 使用 `taskkill /PID <pid> /T /F` 关闭整棵进程树。
2. 再检查配置的后端与前端端口。只有端口监听进程的命令行同时满足以下条件时才作为遗留实例关闭：
   - 命令行位于当前 `refactor` 根目录；
   - 后端包含 `tags_machine_core.web`，或前端包含 `web/node_modules/vite`。
3. 其余端口占用者视为未知进程，脚本拒绝启动，并打印 PID、进程名、命令行与端口。

## 实现边界

- 核心逻辑保持 Python 标准库；Windows 使用系统自带的 `netstat`、`taskkill` 和 PowerShell CIM 查询端口进程及父进程链。
- 不扫描或关闭没有占用配置端口的进程。
- Linux/macOS 延续现有 `terminate/kill` 回收逻辑；受控状态文件仍会被清理。

## 验收

- 已登记 PID 会以整棵进程树被关闭。
- 状态文件缺失但当前项目旧 Vite/uvicorn 占用端口时，仍会被清理。
- 不属于当前项目的监听进程不被关闭，启动返回明确错误。
- `--stop` 只执行清理，不创建前端/后端进程。
