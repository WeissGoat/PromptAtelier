# ai-image-gateway NovelAI Raw Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `tags_machine_core` 的 `NovelAI` 执行层可选切换到 `ai-image-gateway` raw provider，同时保持现有业务结果结构不变。

**Architecture:** `core` 继续持有 `RenderRequest`、拆分、归档、PNG 信息写入；`ai-image-gateway` 只承担 `NovelAI` raw transport/provider。通过一个最小执行器适配层和 `generation.executor` 开关完成接入。

**Tech Stack:** Python 3.10+, `tags_machine_core`, `ai-image-gateway`, `pytest`, `uv`

## Global Constraints

- 只推进 `NovelAI raw` 接入，不扩展 `ComfyUI` / `SD`
- 不改 composer / renderer / prompt policy 业务边界
- 保留 `GenerationResult` / `png_info` 结构
- 清理示例配置中的真实 token

---

### Task 1: 固化执行器接入边界

**Files:**
- Modify: `F:\my_project\new\tags_machine\refactor\src\tags_machine_core\config.py`
- Modify: `F:\my_project\new\tags_machine\refactor\src\tags_machine_core\clients\__init__.py`
- Create: `F:\my_project\new\tags_machine\refactor\src\tags_machine_core\clients\gateway_novelai.py`

**Interfaces:**
- Consumes: `RenderRequest`, `NovelAIImage`, `ai_image_gateway.providers.novelai.NovelAIProvider`
- Produces: `GatewayNovelAIRawClient.build_payload(request)`, `GatewayNovelAIRawClient.generate_images(request)`, `GatewayNovelAIRawClient.last_retry_records`

- [ ] 梳理 `GatewayNovelAIRawClient` 的最小接口，确认只暴露 execution 需要的三个能力
- [ ] 校正 `config.py` 中 `generation.executor` 的默认值与可选值文案
- [ ] 确认 `clients.__init__` 只导出当前分支真正需要的 gateway client
- [ ] 自查 `gateway_novelai.py` 是否只依赖 gateway 公共 API，不触碰子模块生成产物

### Task 2: 接入 NovelAI execution 切换逻辑

**Files:**
- Modify: `F:\my_project\new\tags_machine\refactor\src\tags_machine_core\execution.py`
- Modify: `F:\my_project\new\tags_machine\refactor\tests\test_execution.py`

**Interfaces:**
- Consumes: `AppConfig.generation.executor`, `GatewayNovelAIRawClient`
- Produces: `_novelai_executor_client(config, access_token)`, `png_info.ai_image_gateway.retry_records`

- [ ] 检查 `execute_novelai_generation()` 单请求与 split 请求路径都能挂上 gateway retry records
- [ ] 确认 `build_payload()` 仍由 `core` 语义生成，避免 request body 结构漂移
- [ ] 补齐/修正 `tests/test_execution.py` 中 gateway raw executor 场景
- [ ] 复查 `core_novelai_client` 分支没有被误改

### Task 3: 清理配置与依赖接入细节

**Files:**
- Modify: `F:\my_project\new\tags_machine\refactor\configs\local.example.yaml`
- Modify: `F:\my_project\new\tags_machine\refactor\pyproject.toml`
- Modify: `F:\my_project\new\tags_machine\refactor\uv.lock`
- Modify: `F:\my_project\new\tags_machine\refactor\.gitmodules`

**Interfaces:**
- Consumes: `uv` editable source config, git submodule config
- Produces: 可安装的 `ai-image-gateway` 依赖声明、干净的示例配置

- [ ] 从 `local.example.yaml` 中移除真实 token，仅保留 env/config 占位方式
- [ ] 复核 `pyproject.toml` 的 editable source 指向 `vendor/ai-image-gateway`
- [ ] 确认 `uv.lock` 只包含本次依赖接入带来的必要变化
- [ ] 复查 `.gitmodules` 指向是否正确

### Task 4: 跑接入验证

**Files:**
- Modify: `F:\my_project\new\tags_machine\refactor\tests\test_execution.py`（如验证中发现需要补充断言）

**Interfaces:**
- Consumes: `uv run pytest ...`, `generation.executor=ai_image_gateway_raw`
- Produces: 测试结果、必要时的修正提交

- [ ] 运行 `tests/test_execution.py`
- [ ] 运行与 `NovelAI` 执行链路直接相关的测试子集
- [ ] 如条件允许，跑一次 `generation.executor=ai_image_gateway_raw` 的真实 NovelAI 出图
- [ ] 记录结果，确认 PNG 文本与 retry records 仍可读

