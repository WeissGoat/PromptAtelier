# Web Control Console 业务验收记录 2026-07-10

## Batch API 真实出图

- 入口：FastAPI `TestClient` 调用同一套 Web route。
- 接口：
  - `POST /api/batches/preview`
  - `POST /api/batches/run`
  - `GET /api/jobs/{job_id}`
- 配置：inline batch spec，引用现有 `examples/project/base.yaml`、`examples/project/collections.yaml`、`examples/project/nai_const_action_groups.yaml`。
- 节点选择：
  - characters: `special_next_select`
  - action_groups: `action_new`
  - artist: `109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable`
  - composer: `script`
  - auto_num: `true`
  - max_tasks: `1`
  - nt: `1`
- 认证：通过旧项目 NovelAI 登录流程临时获取 token，仅注入当前测试进程环境变量，未写入仓库文件。

## 结果

- Preview: pass，`task_count=1`。
- Run job: pass，`status=succeeded`。
- NovelAI retry: 过程中出现一次 `429`，`ai_image_gateway_raw` 按配置等待 `8s` 后成功。
- Counts: `{"succeeded": 1}`。
- Run dir: `C:\Users\WHITES~1\AppData\Local\Temp\tm_web_batch_work\web-batch-smoke-action-new-manga-monochrome`
- Output dir: `G:\ai_auto\web-batch-smoke`
- Image: `G:\ai_auto\web-batch-smoke\e027f51f_0_0_0_b0e307ab\3de259e7_0_01.png`
- Parameter details: `G:\ai_auto\web-batch-smoke\e027f51f_0_0_0_b0e307ab\zz_e027f51f_0_0_0_b0e307ab_parameter_details.png`

## 归档检查

输出任务目录包含：

- `3de259e7_0_01.png`
- `prompt_bundle.json`
- `render_request.json`
- `generation_result.json`
- `png_params.json`
- `images.json`
- `zz_e027f51f_0_0_0_b0e307ab_parameter_details.png`

工作目录任务归档包含：

- `task.json`
- `status.json`

## 发现

- 使用完整 `blackboard_action_new_manga_monochrome.yaml` 且只传 `limit=1` 时，Planner 仍会先展开全部任务；这符合当前架构，因为 `limit` 是执行阶段限制，不是规划阶段限制。
- Web/API 场景如果只想快速试跑一张，建议在 spec 中设置 `batch.max_tasks: 1` 或后续在 UI 层提供“试跑模式”自动生成临时 inline spec。
- 初次测试曾因 token 捕获方式错误，把旧登录进程 stdout 混入 `NAI_ACCESS_TOKEN`，导致 HTTP header ASCII 编码失败；修正为只取登录输出最后一行 token 后，真实出图通过。
