# Web Control Console

PromptAtelier Web Control Console 是本地 Web 控制台。前端负责节点选择、编辑、预览和提交任务；提示词生成、节点读取、batch 展开、渲染请求构建和真实出图都由 `tags_machine_core` 后端完成。

## 推荐启动方式

在 `refactor` 目录执行一个命令即可同时启动后端和前端：

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python scripts\dev_web.py
```

默认地址：

```text
Frontend: http://127.0.0.1:53173
Backend : http://127.0.0.1:8765/api
```

脚本会做三件事：

- 启动 `tags_machine_core.web` 后端。
- 启动 Vite 前端，并自动设置 `VITE_API_ROOT=http://127.0.0.1:8765/api`。
- 如果 `web/node_modules` 不存在，先执行一次 `npm install`。

常用参数：

```powershell
uv run python scripts\dev_web.py --config configs\local.yaml
uv run python scripts\dev_web.py --backend-port 8766 --frontend-port 53174
uv run python scripts\dev_web.py --reload-backend
uv run python scripts\dev_web.py --no-install
```

按 `Ctrl+C` 会同时停止前后端。

## 本地配置

Web 后端默认按这个顺序读取配置：

1. 命令行 `--config`。
2. 环境变量 `TAGS_MACHINE_CONFIG`。
3. `configs/local.yaml`。
4. `configs/local.example.yaml`。

`configs/local.yaml` 用来保存本机私有配置，例如 NovelAI token。这个文件已被 `.gitignore` 忽略，不应该提交。

首次配置可以复制示例文件：

```powershell
Copy-Item configs\local.example.yaml configs\local.yaml
```

然后在 `configs/local.yaml` 中填写：

```yaml
novelai:
  base_url: "https://image.novelai.net"
  access_token: "你的 NovelAI token"
  access_token_env: "NAI_ACCESS_TOKEN"
  timeout: 120
  retry: 3
  retry_interval: 8
  request_interval: 3
```

如果 `access_token` 为空，后端会继续读取 `access_token_env` 指定的环境变量，默认是 `NAI_ACCESS_TOKEN`。

## 分开启动

后端：

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python -m tags_machine_core.web --config configs\local.yaml
```

前端：

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm install
npm run dev
```

`npm run dev` 默认使用 `127.0.0.1:53173`。如果需要临时指定端口：

```powershell
npm run dev -- --port 53174
```

## Custom

Custom 页面用于单张或少量图片的自定义生成。

常用字段：

- `Artist`：画风节点 ref，通常来自旧 `design/画风`。
- `Character`：角色节点路径或 ref，可为空。
- `Action`：动作节点路径或 ref，可为空。
- `Full Prompt`：完整角色 + 动作 prompt；填写后后端不会再用角色/动作节点二次拼接。
- `Negative`：负面提示词。
- `Width` / `Height`：输出尺寸。
- `NT`：生成张数；后端会按现有规则拆成多次 `n_samples=1` 请求。
- `Seed`：种子，`-1` 表示随机。

按钮：

- `Preview`：调用 `/api/compose-preview`，只生成 `PromptBundle` 和 `RenderRequest`，不出图。
- `Generate`：调用 `/api/generate`，创建后台 job 并真实出图。

### 临时节点工作流

1. 在 `Artist`、`Character` 或 `Action` 槽位中搜索并选择节点。选择后会读取节点库中的原始内容；也可以点击文件加号按钮 `新建空白...节点`，创建一个不关联节点库的空白临时节点。
2. 点击铅笔按钮 `编辑...节点`，在 JSON 编辑器中修改 prompt，并点击 `应用到本次运行`。这个操作只更新当前 Custom 页面内的草稿，不写入源节点文件；原始节点的 `meta.yaml` 和 Git 状态应保持不变。
3. `应用到本次运行` 与 `保存到节点库` 的区别：前者把当前草稿作为本次 Preview/Generate 的输入；后者会覆盖所选节点库中的原始节点，需要先选择已有节点，并在确认后调用 `/api/nodes/save`。空白临时节点没有 `sourceRef`，不能直接保存到节点库。
4. `Preview` 和 `Generate` 都使用当前草稿。`Generate` 会在草稿、负面 prompt、尺寸、张数或 seed 变化后重新 Preview，避免使用过期结果；它不会因为生成而自动保存节点。

节点槽位顶部的状态标签表示当前来源：

- `原始节点`：草稿与已选择的节点库内容相同，Preview/Generate 可按节点 ref 使用。
- `临时修改`：已有节点被编辑，草稿会以内联 `node` 发送，本次运行使用修改后的内容。
- `空白临时节点`：通过 `新建空白...节点` 创建的节点，草稿 ref 形如 `web-temporary:action:temporary-action`；填写有效 positive prompt 后才能 Preview/Generate。
- `未选择`：该槽位没有节点。

点击垃圾桶清除槽位，或点击刷新重新载入页面，都会清除尚未保存的临时草稿。需要保留修改时，应先使用 `保存到节点库`；还原按钮则把已有节点的草稿恢复为原始内容。

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

- `Plan Preview`：调用 `/api/batches/preview`，使用真实 `BatchPlanner` 展开任务，但不出图。
- `Run Batch`：调用 `/api/batches/run`，创建后台 job 并真实执行。

注意：`limit` 是执行阶段限制；如果 YAML 本身会展开很多任务，预览仍会完整规划。快速试跑建议设置 `Max Tasks=1` 或在 YAML 中设置 `batch.max_tasks: 1`。

## Compare

Compare 页面是对比模式的第一版：保留共享 prompt，同时分别编辑 base/variant artist。后续会接入 Custom 当前状态镜像、锁定节点和批量生成对比组。

## Results

Results 页面调用 `/api/results/runs` 扫描输出目录，展示 run 列表和任务数量。后续可以继续扩展为图片缩略图、PNG 参数和 task artifact 浏览。

## 结果结构

单次生成 job 成功后，`job.result` 是 `GenerationResult`：

- `images[]`：图片路径和文件名。
- `request_body`：实际发送给模型后端的请求体。
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
- `zz_*_parameter_details.png`：当 `archive.save_parameter_image: true` 时生成。
