---
name: comfyui-cloud-deploy
description: >-
  部署、更新或迁移本项目的 ComfyUI 云端后端（当前在 Modal），以及把项目接到一个新的 ComfyUI 运行位置。
  在改插件/ComfyUI 版本后重新部署、排查云端出图失败、估算或核对花费、换到其他云平台时使用。
---

# ComfyUI 云端部署

项目通过 ComfyUI 原生 HTTP API（`/prompt` → `/history` → `/view`）出图，本机 aki、Modal、云主机都是同一套协议。
详细步骤以 `deploy/comfyui/README.md` 为准，这里是给 agent 的操作要点和边界。

## 文件分工

| 位置 | 内容 | 换平台时 |
|---|---|---|
| `deploy/comfyui/Dockerfile` | 唯一的运行环境定义（ComfyUI + 插件 + rclone），模型挂载到 `/models` | 不动 |
| `deploy/comfyui/manifest.yaml` | ComfyUI 版本、插件 repo@commit、补丁、依赖约束 | 不动 |
| `deploy/comfyui/install_comfyui.py` | 按 manifest 安装（Docker 和裸主机都能跑） | 不动 |
| `deploy/comfyui/models.yaml` + `fetch_models.py` | 模型清单和拉取脚本，见 `comfyui-models` skill | 不动 |
| `deploy/comfyui/providers/modal_app.py` | 只属于 Modal 的部分：GPU、Volume、web_server、入口鉴权 | 新平台另写 `providers/<平台>` |
| `configs/local.yaml` 的 `comfyui.targets` | 每个运行位置一条：地址、鉴权、path_style、冷启动等待、状态探测 | 加一条 |

项目代码不依赖 modal SDK；平台差异只能出现在 `providers/` 和 `comfyui.targets` 里。

## 常用命令（仓库根目录）

```bash
# 部署 / 更新 API（只改了 models.yaml、fetch_models.py 或注释时不需要）
uv run modal deploy deploy/comfyui/providers/modal_app.py

# 预检：workflow 用到的节点类、模型文件在目标上是否都在（--live 会触发一次冷启动）
uv run python -m tags_machine_core comfyui-check --artist-node examples/nodes/artists/comfyui_cunyfunky --manifest deploy/comfyui/manifest.yaml --config configs/local.yaml --comfyui-target modal --live

# 冒烟出图
uv run python -m tags_machine_core run-batch examples/batches/comfyui_cunyfunky_smoke.yaml --fresh --comfyui-target modal

# 花费
uv run modal billing report --for today -r h --show-resources --tz local
```

## Modal 的坑（已在 modal_app.py 处理，改它时别破坏）

- Modal 把整个 Dockerfile 当成一个构建步骤：改 Dockerfile 指令、`manifest.yaml`、补丁都会从头重建（约 15 分钟，CPU 费用不到 1 美分）。
  所以 `models.yaml` / `fetch_models.py` 在 Modal 上不进镜像，容器启动时挂载。
- Modal 1.6 按系统默认编码读 Dockerfile（中文 Windows 是 GBK）。`modal_app.py` 交给 Modal 的是去掉注释的 ASCII 副本，
  所以 Dockerfile 注释可以写中文，但**指令行必须是 ASCII**。
- `api` 函数 `max_containers=1`（ComfyUI 的队列和 history 在单个容器里）、`min_containers=0`、空闲 3 分钟缩容。
  这几项同时是花费护栏，不要改成常驻。

## 花费

- 只有 GPU 贵：L40S 约 $1.95/小时，从容器启动开始计，包括冷启动（约 15 秒）、首张加载模型（约 40 秒）、出图和 3 分钟空闲。
  单张零散出图约 $0.15，大头是空闲；批量出图划算得多。
- 下载模型、构建镜像只用 CPU，几分钱以内；Volume 和出网流量都在每月免费额度内。
- 月预算 $30（Starter 赠送额度），Workspace budget 由用户在 Modal 后台设置。

## 换到其他平台

1. 能跑 Docker 镜像的平台：用 `deploy/comfyui/Dockerfile` 构建，持久盘挂到 `/models`，容器里跑
   `python /opt/tm-comfyui/fetch_models.py --dest /models`（带上 `RCLONE_CONFIG_TMGDRIVE_*` 就从模型仓库拉），暴露 8188。
   平台没有入口鉴权就要在前面加鉴权反向代理（还没做）。
2. 不能跑自定义镜像的主机：直接运行 `install_comfyui.py --comfyui-dir ... --models-dir ...` 和 `fetch_models.py`。
3. 提交 workflow → 轮询任务的 serverless 队列平台（RunPod Serverless 等）：需要实现
   `tags_machine_core.clients.ComfyUITransport` 适配器并在 `ComfyUIConnectionConfig.transport` 登记（还没做）。
4. 在 `configs/local.yaml` 的 `comfyui.targets` 加一条（格式见 `configs/local.example.yaml`），跑预检和冒烟。
   Web 控制台的「ComfyUI 运行位置」下拉会自动出现新目标。
5. 按小时租的 GPU 机器开着就计费，装环境、下模型的时间也算：用持久盘，模型只下一次。

## 规则

- 会启动 GPU 的操作（`--live` 预检、冒烟、Web 出图、`modal run ...::ui`）要花钱，用户没要求时先说明再做。
- 不打印、不提交任何凭据：`TM_COMFYUI_MODAL_TOKEN`（Modal proxy token）、`CIVITAI_TOKEN`、rclone 配置里的 token。
  `configs/local.yaml` 含 NovelAI token，永远不要提交。需要新 proxy token 时让用户运行
  `deploy/comfyui/providers/modal_create_proxy_token.ps1`，它直接写进用户环境变量、不显示密钥。
- Web 后端从环境变量读 `TM_COMFYUI_MODAL_TOKEN`，改了要重启 Web 控制台。
- 改 `modal_app.py` 后至少在本机导入一次（`modal.is_local()` 分支会生成 Dockerfile 副本），确认不报错再部署。
