# Action Meta Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一个可每天重复执行的离线命令，扫描动作 `new` 目录，生成缺失的 `meta.yaml` 并补齐工具负责的 `clothing` 字段。

**Architecture:** 在 `tools/legacy_migration` 中新增同步编排器。编排器复用 `migrate_legacy_action_tags()` 生成基础节点，复用 Clothing 分析逻辑更新字段；已有 `meta.yaml` 不重新迁移，只允许更新 `clothing` 和清理旧 `type` 指令。写入采用同目录临时文件原子替换，并用根目录锁文件阻止重叠执行。

**Tech Stack:** Python 3.11、PyYAML、argparse、pathlib、pytest。

## Global Constraints

- 该功能只属于 `tools` 离线维护工具，`tags_machine_core` 运行时不得导入。
- 默认 preview，不传 `--write` 时不得写入动作目录。
- 缺少 `tags.txt` 且缺少 `meta.yaml` 的目录记录为错误，不生成残缺节点。
- 已有 `meta.yaml` 不覆盖人工或 Agent 字段。
- 中文注释；报告必须包含 created、updated、unchanged、skipped、errors。

---

### Task 1: Action Meta 同步服务

**Files:**
- Create: `tools/legacy_migration/sync_action_meta.py`
- Modify: `tools/legacy_migration/fill_action_meta_clothing.py`
- Test: `tests/test_sync_action_meta.py`

**Interfaces:**
- Consumes: `migrate_legacy_action_tags(source, node_id, name) -> dict[str, Any]`
- Produces: `sync_action_meta(root: Path, *, write: bool, backup: bool, lock: bool = True) -> dict[str, Any]`

- [ ] **Step 1: 覆盖缺失 meta、已有 meta、无 clothing 信号、错误和幂等场景**

- [ ] **Step 2: 实现发现节点、生成基础 meta、更新 clothing 和汇总报告**

- [ ] **Step 3: 使用同目录临时文件写入并通过 `Path.replace()` 原子替换**

- [ ] **Step 4: 添加根目录 `.action-meta-sync.lock`，锁已存在时退出并给出明确错误**

- [ ] **Step 5: 运行 `uv run pytest tests/test_sync_action_meta.py tests/test_fill_action_meta_clothing.py -q`，预期全部通过**

### Task 2: CLI 与文档

**Files:**
- Modify: `tools/legacy_migration/cli.py`
- Modify: `README.md`
- Modify: `docs/action_yaml_spec_v1.md`
- Test: `tests/test_cli_nodes.py`

**Interfaces:**
- Consumes: `sync_action_meta(...)`
- Produces: `python -m tools.legacy_migration sync-action-meta ROOT [--write] [--backup] [--no-lock] [--report PATH]`

- [ ] **Step 1: 注册 `sync-action-meta` 子命令和参数**

- [ ] **Step 2: 报告写入 JSON；存在错误时返回退出码 1**

- [ ] **Step 3: 文档补充每天定时执行的 PowerShell 示例**

- [ ] **Step 4: 在真实 `design/动作改2/new` 上运行 preview，确认没有文件写入**

- [ ] **Step 5: 运行迁移工具测试和完整测试套件**
