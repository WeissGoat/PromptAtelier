# ai-image-gateway NovelAI Raw 接入设计

## 目标

在 `refactor` 项目里，把 `NovelAI` 的实际出图执行层切换为可选地通过 `ai-image-gateway` 的 raw provider 发请求，同时保持现有 `core` 业务链路不变：

- `PromptBundle -> RenderRequest -> execution -> PNG/归档`
- 继续由 `core` 控制 `n_samples=1` 拆分、PNG 参数补写、结果结构
- 不把 composer / renderer / policy 逻辑迁入 gateway

## 边界

### `tags_machine_core` 继续负责

- `RenderRequest` 的业务结构
- `NovelAI` 请求前的 `n_samples` 拆分
- 输出文件命名、归档、PNG 文本写入
- `GenerationResult` / `png_info` 结构
- 与旧 `tags_machine` 验收对比所需的业务元信息

### `ai-image-gateway` 负责

- `NovelAI` token / auth 解析
- HTTP transport
- retry / timeout / rate-limit
- raw payload 执行
- provider 结果解码

## 方案

采用“最小可切换执行器”方案：

1. 在 `tags_machine_core.config` 增加 `generation.executor`
2. `execution.execute_novelai_generation()` 内部根据 `generation.executor` 选择：
   - `core_novelai_client`
   - `ai_image_gateway_raw`
3. 新增 `GatewayNovelAIRawClient` 适配层，接口对齐现有执行层需要的最小能力：
   - `build_payload(request) -> dict`
   - `generate_images(request) -> list[NovelAIImage]`
   - `last_retry_records`

这样可以保证：

- 现有执行层改动小
- gateway 仍然只承担 provider/transport 责任
- 后续如果要继续抽象执行器，可以在现有边界上再演进

## 非目标

这一步不做以下事情：

- 不把 `PromptBundle` / `RenderRequest` 直接改成 gateway contracts
- 不让 `core` 直接依赖 gateway facade service
- 不改 `ComfyUI` / `SD` 接入方式
- 不重构 composer / renderer / prompt policy
- 不在这一步处理 `main` review 里发现的 `clothing_policy` 与 `selected_keys` 问题

## 风险点

1. `configs/local.example.yaml` 当前带有真实 token，必须清掉
2. `vendor/ai-image-gateway` 是子模块，`refactor` 侧只能依赖其公开 API，不应读取其生成产物
3. gateway raw 执行器需要保留 retry records，方便 `png_info` 继续记录验收信息
4. `main` 与 gateway 分支已经拆分完成，本次只推进 gateway 接入残余文件，避免把非 gateway 逻辑重新混进来

## 验收

### 代码级

- `tests/test_execution.py` 中 gateway raw executor 场景通过
- 原有 `core_novelai_client` 路径不回归

### 业务级

- `refactor` 可以通过 `generation.executor=ai_image_gateway_raw` 正常走通 NovelAI 出图
- 输出图仍然保留 `tags_machine_core` PNG 文本
- `GenerationResult.png_info.ai_image_gateway.retry_records` 可读

## 实现范围

只修改当前 gateway 分支上残留的接入相关文件：

- `configs/local.example.yaml`
- `pyproject.toml`
- `src/tags_machine_core/config.py`
- `src/tags_machine_core/execution.py`
- `src/tags_machine_core/clients/__init__.py`
- `src/tags_machine_core/clients/gateway_novelai.py`
- `tests/test_execution.py`
- `uv.lock`
- `.gitmodules`

