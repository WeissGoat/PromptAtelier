# ComfyUI 云端运行环境

项目通过 ComfyUI 原生 HTTP API（`/prompt` → `/history` → `/view`）调用 ComfyUI，本地 aki、Modal、云主机都是同一套协议。
这个目录定义"云端那台 ComfyUI 长什么样"，分两层：

| 层 | 文件 | 换云时 |
|---|---|---|
| 平台无关 | `manifest.yaml`：ComfyUI 版本、插件 @commit、补丁、依赖版本约束 | 不动 |
| | `models.yaml`：模型路径 + 大小 + sha256 + 来源（运行时读取，不进镜像安装层） | 不动 |
| | `install_comfyui.py`：按 manifest 装 ComfyUI 和插件（Docker 和裸主机都能跑） | 不动 |
| | `fetch_models.py`：按 models.yaml 下载/复制模型到任意目录并校验 sha256 | 不动 |
| | `Dockerfile`：唯一的镜像定义，模型运行时挂载到 `/models` | 不动 |
| 平台适配 | `providers/modal_app.py`：Modal 的 GPU、Volume、web_server、入口鉴权 | 新平台写一个 `providers/<平台>/` |

项目侧对应 `configs/*.yaml` 里的 `comfyui.targets`：每个目标一条配置（地址、鉴权、路径风格、冷启动等待），用 `--comfyui-target` 或环境变量 `TAGS_MACHINE_CORE_COMFYUI_TARGET` 切换。

## 当前覆盖范围

目前只装了 `comfyui_cunyfunky` 用到的 5 个插件和 10 个模型（约 7.6 GB）。
项目提交前会把 workflow 裁剪到 `output_nodes` 的上游（cunyfunky 64 → 24 个节点），所以其余预览分支用到的插件不需要装。

和本地 aki 对齐的几处细节：

- ComfyUI 钉在 v0.3.59（2026-07-04 业务验收的版本）。
- Impact Pack 带本地 aki 的兼容补丁 `patches/comfyui-impact-pack-differential-diffusion.patch`：
  该 commit 调用 `DifferentialDiffusion().execute()`，ComfyUI 0.3.59 只有 `apply()`，不打补丁 FaceDetailer 会报错。
- 跳过 Impact Pack 的 `sam2` 依赖（本地也没装；SAMLoader 用的是 segment-anything）。
- numpy 等依赖按本地版本约束，避免云端装到 numpy 2.x。

## 用 Modal 部署

以下命令都在仓库根目录执行。本机 `modal` CLI 需已登录（`modal profile current`）。

1. **先设花费上限**：Modal Dashboard → Usage & Billing → Workspace budget 设为 `$30`（Starter 每月赠送额度）。

2. **部署 API**（首次会在 Modal 上构建镜像，约十几分钟；构建在云端完成，不占本机带宽）：

   ```bash
   modal deploy deploy/comfyui/providers/modal_app.py
   ```

   记下输出里 `api` 的地址，形如 `https://<workspace>--tm-comfyui-api.modal.run`。

3. **放模型**（二选一，已存在且大小一致的会跳过）：

   - 从本机上传（会先校验 sha256）：

     ```bash
     modal run deploy/comfyui/providers/modal_app.py::upload --local-roots "D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI/models;G:/AI/draw/models"
     ```

   - 在云端直接下载（Civitai 模型需要先在本机设置 `CIVITAI_TOKEN` 环境变量）：

     ```bash
     modal run deploy/comfyui/providers/modal_app.py::download
     ```

4. **创建 proxy token**（API 开了入口鉴权，没有 token 的请求在 Modal 边缘就被拒绝，不会唤醒 GPU）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy/comfyui/providers/modal_create_proxy_token.ps1
   ```

   脚本创建 token，并把 `wk-...` 和 `ws-...` 用点连起来，存进用户环境变量 `TM_COMFYUI_MODAL_TOKEN`；
   密钥不会显示在屏幕上（Modal 也只在创建时返回一次，丢了就再建一个，旧的用 `modal workspace proxy-tokens delete` 删掉）。

5. **配置目标**：参照 `configs/local.example.yaml`，在 `configs/local.yaml` 的 `comfyui` 下加 `targets.modal`，把 `base_url` 换成第 2 步的地址。

6. **预检**（`--live` 会请求一次 `/object_info`，触发一次冷启动）：

   ```bash
   uv run python -m tags_machine_core comfyui-check --artist-node examples/nodes/artists/comfyui_cunyfunky --manifest deploy/comfyui/manifest.yaml --config configs/local.yaml --comfyui-target modal --live
   ```

   `ok: true` 表示 workflow 用到的节点类和下拉值（模型文件等）在云端都存在。

7. **冒烟**：

   ```bash
   uv run python -m tags_machine_core run-batch examples/batches/comfyui_cunyfunky_smoke.yaml --fresh --comfyui-target modal --log-level info
   ```

   每张图的 `png_info.comfyui.target` 会记录用的是哪个目标。

8. **临时 UI**（调 workflow 用；默认 L4，Ctrl+C 结束，最长 2 小时）：

   ```bash
   modal run deploy/comfyui/providers/modal_app.py::ui
   ```

### 成本护栏

- `api`：`max_containers=1`、`min_containers=0`、空闲 3 分钟缩容。GPU 默认 L40S，可在部署前用 `TM_COMFYUI_MODAL_GPU=L4` 之类覆盖。
- 计费包括冷启动、执行和 3 分钟空闲：批量出图比零散单张划算得多。
- UI 页面开着时 ComfyUI 前端一直连着 websocket，容器不会缩容；用完关标签并结束 `modal run`。
- serverless 目标配置了 `allow_no_wait: false`：`--comfyui-no-wait` 只排队不轮询，容器缩容后结果会丢。

## 在 Web 控制台里用

- ComfyUI 画风节点放在 design 根目录的 `画风/comfyui/<名字>/`（`node.yaml` + `workflows/`），Artist 选择器里带 `ComfyUI` 标记。
- 选了 ComfyUI 画风后，参数区会出现「ComfyUI 运行位置」（整个工作区一个）：本机 aki 或 Modal 云端。
- 状态说明：本机探测端口；云端通过 Modal API 读容器数，不会因为查看状态启动 GPU。
  云端开着时显示自动关机倒计时（按 Web 最后一次生成 + 3 分钟估算）。
- 生成时任务下方显示当前阶段：正在启动 ComfyUI → 生成中 → 正在下载图片，带已等待秒数；
  冷启动后的第一张会提示「首张要先加载模型」。
- 预览里列出 Backend / Workflow / 尺寸 / Seed，以及换算权重后 ComfyUI 实际收到的提示词；
  图片详情里能看到这张图的运行位置、workflow 和换算后的提示词（从 PNG 里的 core 元数据读）。
- Batch 页也有「ComfyUI 运行位置」，只对用 ComfyUI 画风的任务生效，选择会记在浏览器里。
- Web 后端从环境变量 `TM_COMFYUI_MODAL_TOKEN` 读 proxy token；设置后要重启 Web 控制台。

## 新增 workflow / 插件 / 模型

1. 在本地 aki 里做好 workflow，`File -> Export (API)`，放进 artist node。
2. 跑 `comfyui-check --artist-node <dir> --manifest deploy/comfyui/manifest.yaml`，看 `manifest.not_provided_by_manifest`（内置节点或漏掉的插件）和 `missing_models`。
3. 插件：在 `manifest.yaml` 的 `custom_nodes` 里加 repo + commit（对齐本地 aki 的版本）和 `provides`，然后重新 `modal deploy`。
4. 模型：在 `models.yaml` 里加路径、大小、sha256、来源（URL 尽量钉到固定版本），然后跑上面的上传或下载；不需要重新部署。

## 换到其他平台

- **能跑 Docker 镜像、能暴露端口的平台**（GPU 云主机、RunPod Pod 等）：用这里的 `Dockerfile` 构建，把持久盘挂到 `/models`，在容器里跑 `python /opt/tm-comfyui/fetch_models.py --dest /models` 填充模型，暴露 8188。
  平台没有入口鉴权的话需要在前面加一层鉴权反向代理（还没做）。最后在 `comfyui.targets` 里加一条。
- **不支持自定义镜像的主机**：直接运行 `install_comfyui.py --comfyui-dir ... --models-dir ...` 和 `fetch_models.py`。
- **serverless 任务队列型平台**（RunPod Serverless 等，提交 workflow → 轮询任务 → 取图）：需要按 `tags_machine_core.clients.ComfyUITransport` 写一个 transport adapter，并在 `ComfyUIConnectionConfig.transport` 里登记（还没做）。
