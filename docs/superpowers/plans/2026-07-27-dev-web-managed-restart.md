# Dev Web Managed Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `scripts/dev_web.py` 可安全重启并回收 Windows 子进程树。

**Architecture:** 启动器使用 `runtime/dev_web.json` 记录其直接子进程，并以状态文件为主、端口命令行识别为后备来清理残留。未知端口占用保留并阻断启动。

**Tech Stack:** Python 3.11、argparse、subprocess、unittest.mock。

## Global Constraints

- 只关闭当前 `refactor` 的 PromptAtelier 后端或 Vite 进程。
- Windows 必须递归关闭子进程树。
- 保留原有 `--host`、端口和 reload 参数。

---

### Task 1: 进程状态与安全识别

**Files:**
- Modify: `scripts/dev_web.py`
- Create: `tests/test_dev_web.py`

**Interfaces:**
- Produces: `--stop`、`_cleanup_previous_instance()`、`_write_state()`、`_ensure_ports_available()`。

- [x] 编写失败测试：状态文件 PID 被递归关闭、当前项目端口占用可关闭、未知进程占用抛出错误、`--stop` 不启动进程。
- [x] 运行 `uv run python -m unittest tests.test_dev_web`，确认测试在旧实现失败。
- [x] 实现状态文件读写、Windows `taskkill /T /F`、端口进程识别与未知占用报错。
- [x] 重新运行目标测试。

### Task 2: 启动器集成与回归验证

**Files:**
- Modify: `scripts/dev_web.py`
- Test: `tests/test_dev_web.py`

- [x] 在启动前清理，在 `Popen` 后登记，在 finally 删除状态。
- [x] 手工启动一轮 Web 服务，再次执行启动命令，确认旧监听 PID 被替换且两个端口均可用。
- [x] 执行 `--stop`，确认两个监听端口均释放，并重新启动最终服务。
