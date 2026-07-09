# Web 控制台设计方案

## 1. 背景与目标

`tags_machine_core` 已经具备稳定的本地 JSON API、节点读取、提示词生成、NovelAI 渲染、BatchPlanner、BatchRunner 和结果归档能力。下一阶段目标是接入一个本地 Web 服务与前端 UI，让常用生图流程从命令行迁移到可视化工作台。

首版 UI 的定位是 **PromptAtelier 本地 Web 控制台**：

- 面向本机运行，不做云端多用户。
- 复用 `tags_machine_core`，不在前端重写 prompt 拼接、batch 展开、生图参数或后端 payload。
- `batch YAML`、`NodeDocument`、`meta.yaml`、`tags.txt` 继续作为核心数据来源。
- 预览阶段只生成 `PromptBundle` 和 `RenderRequest`，不联网生图。
- 点击“生图”或“运行 Batch”后才进入 NovelAI 执行层。

## 2. 首版范围

首版包含：

- Custom Studio：自定义模式，支持选择已有 artist、character、action、background，或输入 full prompt。
- 结构化节点编辑：UI 以表单编辑节点草稿，保存时写回原格式，新建节点默认写 `meta.yaml`。
- Compare Studio：从当前自定义组合镜像 variant，用于 artist、参数、节点差异对比。
- Batch Studio：配置、预览、运行 batch，覆盖旧 `blackboard.py:run_tags_machine` 类批量跑图。
- Results Gallery：查看生成图、PNG 参数、parameter details、PromptBundle、RenderRequest、GenerationResult。
- 本地 FastAPI 服务：封装现有 core API、节点文件管理、Job 管理和结果索引。

首版不包含：

- AgentComposer UI 闭环。
- 自动调用外部 agent。
- 云端部署、多用户账号、权限系统。
- Tauri/Electron 桌面壳。
- ComfyUI / SD 的完整 UI 工作流。

## 3. 推荐架构

```text
React / Vite 前端
  -> FastAPI 本地 Web 服务
    -> tags_machine_core JSON API / BatchPlanner / BatchRunner / NodeReader
      -> Renderer / Executor
        -> NovelAI
        -> outputs / manifest / task artifacts
```

### 3.1 前端职责

- 提供可视化选择、编辑、预览和运行界面。
- 管理当前页面草稿状态。
- 显示实时日志、任务进度、结果图库和参数 diff。
- 只通过 HTTP/SSE/WebSocket 调用本地服务，不直接读写 `design` 目录。

### 3.2 Web 服务职责

- 暴露 HTTP API。
- 直接 import `tags_machine_core`，不通过 subprocess 包一层 CLI。
- 提供节点读取、节点保存、临时节点草稿预览。
- 提供 compose preview、render plan、generate。
- 提供 batch preview、batch run、batch inspect、batch resume。
- 维护长任务 `JobManager`，支持实时事件、取消和状态查询。
- 建立结果索引，方便前端浏览历史输出。

### 3.3 Core 职责

Core 继续保持业务能力来源：

- `GenerationJsonApi`
- `GenerationService`
- `NodeReader`
- `BatchPlanner`
- `BatchRunner`
- `NovelAIRenderAdapter`
- `execute_render_request`

UI 和 Web 服务不得复制这些内部规则。

## 4. 主要页面

### 4.1 Custom Studio

Custom Studio 用于单次或少量生图调试。

布局：

```text
左侧：节点选择
中间：节点结构化编辑草稿
右侧：最终 prompt / render params 预览
底部：生图参数和操作按钮
```

节点选择：

- Artist：搜索/下拉选择。
- Character：支持单选、多选。
- Action：单选。
- Background：可选。
- Composer：首版只支持 `script` 和 `full prompt`。

节点编辑：

- 读取已有节点后解析为 `NodeDocument`。
- UI 展示结构化表单，而不是让用户直接编辑 YAML。
- 修改先进入 session draft，不立即写文件。
- 预览使用 draft。
- 点击“保存节点”才写回文件。
- 点击“恢复原始”丢弃 draft。
- Raw View 展示原始 `meta.yaml` / `tags.txt`，作为高级视图。

预览区：

- Positive Prompt。
- Negative Prompt。
- RenderRequest。
- NovelAI 参数摘要。
- `character_prompts` 摘要。
- reference/vibe 摘要。
- warnings，例如节点缺字段、路径不存在、batch 过大。

运行参数：

- model。
- resolution。
- seed。
- nt。
- steps。
- scale。
- sampler。
- `character_prompts`: auto/off。
- `archive.save_parameter_image`。
- output_dir。

操作：

- 预览提示词。
- 生图。
- 保存当前组合为 batch。
- 保存当前组合为 preset。

### 4.2 Compare Studio

Compare Studio 挂在 Custom Studio 之上，用于对比不同 artist、节点或参数。

核心交互：

- 从当前 Custom Studio 组合创建 Compare Set。
- 复制一个或多个 Variant。
- 支持锁定 character/action/params，只修改 artist。
- 支持固定 seed。
- 支持预览 PromptBundle / RenderRequest diff。
- 一键生成所有 Variant。
- 结果并排展示图片、prompt diff、参数 diff。

数据形态：

```json
{
  "base": {
    "nodes": [],
    "params": {}
  },
  "variants": [
    {
      "name": "artist A",
      "overrides": {
        "artist": "20260412"
      }
    }
  ]
}
```

输出结构建议：

```text
compare_runs/<case_id>/
  base/
  variant_artist_a/
  variant_artist_b/
  report.json
  report.md
```

### 4.3 Batch Studio

Batch Studio 用于替代旧 `blackboard.py` 的批量跑图入口。

配置项：

- characters：collection 或 explicit refs。
- action_groups：collection，例如 `action_new`、`action_sex`、`st_rp`。
- artist。
- composer：首版优先 script/full。
- strategy：ordered / random / balanced_random。
- auto_num。
- max_tasks。
- nt。
- resolution。
- output_dir。
- archive options。
- retry options。

必须先进行 plan preview：

- task_count。
- character_count。
- action_group_count。
- 每个 action group 的动作数。
- 前 N 条任务编排。
- 跳过原因统计。
- 预计输出目录。
- 预计使用的 composer 和 backend。

运行：

- `POST /api/batches/run` 创建 job。
- UI 显示当前 character、action、artist、resolution。
- 显示 succeeded / failed / skipped / retry。
- 支持 cancel。
- 支持 resume。

Batch YAML 仍然是 source of truth。UI 可以编辑结构化表单，但保存时生成或更新 YAML。

### 4.4 Node Library

节点库用于浏览和管理旧 `design` 里的节点。

支持类型：

- artist。
- character。
- action。
- background。
- collections。
- action_groups。

能力：

- 搜索。
- 展开 collection。
- 展开 action group。
- 查看节点解析结果。
- 新建节点。
- 编辑节点草稿。
- 保存节点。
- 查看原始文件。

结构化编辑字段：

- 基础信息：name、description、role。
- Prompt：positive、negative。
- Tags：character、appearance、clothing、action_hint、custom。
- Relations：cp、aliases。
- Composition：selected_keys、可选 scope 信息。
- Backend Hints：NovelAI 专属参数、reference、vibe。
- Raw View：原始文件内容。

保存规则：

- 原节点是 `meta.yaml`：保存回 `meta.yaml`。
- 原节点是 `tags.txt`：首版可保存回 `tags.txt`，但优先提示用户转换为 `meta.yaml`。
- 新建节点：默认写 `meta.yaml`。
- 保存前展示 diff。

### 4.5 Results Gallery

结果页按 run/task 浏览输出。

展示：

- 图片。
- `zz_*_parameter_details.png`。
- PNG 参数。
- `prompt_bundle.json`。
- `render_request.json`。
- `generation_result.json`。
- NovelAI `request_body`。

功能：

- 按 artist / character / action / batch 过滤。
- 打开图片所在目录。
- 标记 pass/fail。
- 对比两张图参数 diff。
- 从结果反向创建 Compare Set。

## 5. 后端服务模块

建议目录：

```text
src/tags_machine_core/web/
  app.py
  routes/
    nodes.py
    compose.py
    generate.py
    batch.py
    jobs.py
    results.py
  services/
    node_workspace.py
    job_manager.py
    batch_workspace.py
    result_index.py
```

### 5.1 HTTP API 草案

节点：

```text
GET  /api/nodes?type=artist&q=
GET  /api/nodes/{type}/{id}
POST /api/nodes/preview
PUT  /api/nodes/{type}/{id}
POST /api/nodes
```

自定义模式：

```text
POST /api/compose-preview
POST /api/render-preview
POST /api/generate
```

对比模式：

```text
POST /api/compare/preview
POST /api/compare/generate
GET  /api/compare/{case_id}
```

Batch：

```text
POST /api/batches/preview
POST /api/batches/save
POST /api/batches/run
POST /api/batches/resume
GET  /api/batches/{run_id}
```

Job：

```text
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/events
POST /api/jobs/{job_id}/cancel
```

结果：

```text
GET /api/results/runs
GET /api/results/runs/{run_id}
GET /api/results/tasks/{task_id}
GET /api/results/files?path=
```

### 5.2 JobManager

真实生图和 batch run 都必须作为 job 运行。

状态：

```text
queued
running
cancelling
succeeded
failed
cancelled
```

事件：

```json
{
  "type": "task_started",
  "job_id": "...",
  "task_id": "...",
  "character": "...",
  "action": "...",
  "artist": "..."
}
```

取消策略：

- 首版支持 cooperative cancel。
- BatchRunner 在任务之间检查 cancel flag。
- 已经发出的 NovelAI 请求不强行中断，等待当前请求结束后停止后续任务。

## 6. 数据流

### 6.1 Custom Studio 预览

```text
选择节点/编辑草稿
-> POST /api/compose-preview
-> GenerationJsonApi.compose 或 compose_render_plan
-> PromptBundle + RenderRequest
-> UI 展示最终 prompt 和参数
```

### 6.2 Custom Studio 生图

```text
当前预览 RenderRequest
-> POST /api/generate
-> JobManager 创建 job
-> execute_render_request
-> GenerationResult
-> Results Gallery
```

### 6.3 Batch 预览

```text
Batch 表单/YAML
-> POST /api/batches/preview
-> load_batch_spec_mapping
-> BatchPlanner.plan
-> selector_summary + sample tasks + warnings
```

### 6.4 Batch 运行

```text
BatchSpec
-> POST /api/batches/run
-> JobManager
-> BatchRunner.run_tasks
-> manifest / status.json / artifacts
-> events
-> Results Gallery
```

## 7. 错误处理

前端应明确显示这些错误：

- 节点路径不存在。
- YAML 解析失败。
- 节点保存冲突。
- Batch 预览任务量过大。
- NovelAI token 缺失。
- NovelAI 429 / 500 / 502 / timeout。
- 生成参数不合法，例如不支持的模型参数。
- 输出目录不可写。

错误响应统一形态：

```json
{
  "error": {
    "code": "node_not_found",
    "message": "Node path not found",
    "details": {}
  }
}
```

## 8. 测试与验收

首版验收以业务链路为主。

自定义模式：

- 能选择已有 artist、character、action。
- 修改节点草稿后，预览 prompt 会变化，但未点击保存不会写文件。
- 点击保存后，节点文件发生预期 diff。
- 点击生图后真实生成图片。
- 输出目录包含 `prompt_bundle.json`、`render_request.json`、`generation_result.json`、`png_params.json` 和可选 `parameter_details`。

对比模式：

- 能从当前组合复制 variant。
- 能只修改 artist。
- 能固定 seed。
- 能生成多组 variant。
- 结果能并排查看，并展示参数 diff。

Batch 模式：

- 能加载 `special_next_select + action_new + artist` 类配置。
- plan preview 能显示 task_count 和前 N 条任务。
- max_tasks 能限制任务数量。
- run job 能真实生成至少一组图。
- cancel 能阻止后续任务继续执行。
- resume 能跳过已成功任务。

结果图库：

- 能列出 run。
- 能查看 task 图片。
- 能打开 PNG 参数和 request/result JSON。
- 能从结果创建 compare case。

## 9. 实施顺序建议

1. FastAPI 服务骨架。
2. JobManager。
3. 节点读取与结构化表单 API。
4. Custom Studio 预览。
5. Custom Studio 生图。
6. Results Gallery 最小版。
7. Batch preview。
8. Batch run job。
9. Compare Studio。
10. 节点保存与新建。

## 10. 开放给后续阶段

后续可以加入：

- Agent Studio。
- AgentComposer cache 可视化。
- 真实前端调度外部 agent。
- 多后端 UI：ComfyUI / SD。
- Tauri/Electron 桌面包装。
- 更完整的节点 schema 校验。
- 图片评分、收藏、筛选、批量移动。
