# Web Control Console

PromptAtelier Web Control Console 是本地优先的前端控制台。前端只负责编辑、预览和发起任务；提示词生成、节点读取、batch 展开、渲染请求构建和真实出图都由 `tags_machine_core` 后端完成。

## 启动后端

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python -m tags_machine_core.web
```

默认地址：

```text
http://127.0.0.1:8765/api
```

后端会读取 `configs/local.example.yaml`，其中 `legacy.design_root` 指向旧 `tags_machine/design`。

## 启动前端

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm install
npm run dev
```

默认前端地址：

```text
http://127.0.0.1:5173
```

如果 5173 在本机不可用，可以直接调用 Vite 指定端口：

```powershell
.\node_modules\.bin\vite.cmd --host 127.0.0.1 --port 53173
```

## Custom

Custom 页面用于单张或少量图片的自定义生成。

字段含义：

- `Artist`：画风节点 ref，通常是旧 `design/画风` 下的节点名。
- `Character`：角色节点路径或 ref，可为空。
- `Action`：动作节点路径或 ref，可为空。
- `Full Prompt`：完整角色 + 动作提示词；如果填写完整 prompt，后端不会再用节点二次拼接角色动作。
- `Negative`：负面提示词。
- `Width` / `Height`：输出尺寸。
- `NT`：NovelAI `n_samples`，后端会按现有规则拆成单张请求。
- `Seed`：种子，`-1` 表示随机。

按钮：

- `Preview`：调用 `/api/compose-preview`，只生成 `PromptBundle` 和 `RenderRequest`，不出图。
- `Generate`：调用 `/api/generate`，创建后台 job 并真实出图。

## Batch

Batch 页面用于批量任务预览和运行。

模式：

- `Inline draft` 开启：界面字段会组成临时 batch spec。
- `Inline draft` 关闭：直接使用 `Batch YAML` 路径。

常用字段：

- `Characters`：角色集合名，例如 `special_next_select`。
- `Action Groups`：动作组集合名，多个用英文逗号分隔，例如 `action_new,action_sfw`。
- `Artist`：画风节点 ref。
- `Max Tasks`：写入 batch spec 的最大规划任务数，适合试跑。
- `NT`：每个任务生成张数。

按钮：

- `Plan Preview`：调用 `/api/batches/preview`，使用真实 BatchPlanner 展开任务，但不出图。
- `Run Batch`：调用 `/api/batches/run`，创建后台 job 并真实执行。

注意：`limit` 是执行阶段限制；如果 YAML 本身会展开很多任务，预览仍会完整规划。快速试跑建议设置 `Max Tasks=1` 或在 YAML 中设置 `batch.max_tasks: 1`。

## Results

Results 页面调用 `/api/results/runs` 扫描输出目录，展示 run 列表和任务数量。后续可以继续扩展为图片缩略图、PNG 参数和任务 artifact 浏览。

## Compare

Compare 页面是对比模式的第一版壳：可以保留共享 prompt，同时编辑 base/variant artist。后续会接入 Custom 当前状态镜像、锁定节点、批量生成对比组。

## 后端结果结构

单次生成 job 成功后，`job.result` 是 `GenerationResult`：

- `images[]`：图片路径和文件名。
- `request_body`：实际发送给后端模型的请求体。
- `png_info`：从生成图片读取回来的 PNG 参数。

Batch job 成功后，`job.result` 包含：

- `run_dir`：工作目录，保存 task/status/report。
- `output_dir`：图片和 artifact 输出目录。
- `counts`：任务状态统计。
- `entries[]`：每个任务的状态、图片路径、错误信息和 source。

每个成功的 batch task 输出目录通常包含：

- `*.png`
- `prompt_bundle.json`
- `render_request.json`
- `generation_result.json`
- `png_params.json`
- `images.json`
- `zz_*_parameter_details.png`，当 `archive.save_parameter_image: true` 时生成。
