---
name: comfyui-models
description: >-
  管理 ComfyUI 后端用到的模型：在 models.yaml 登记新模型、放进谷歌云盘模型仓库、拉到 Modal Volume 或新机器、
  核对仓库是否齐全。在新增 checkpoint/LoRA/检测模型、云端报模型缺失（value_not_in_list）、换平台准备模型时使用。
---

# ComfyUI 模型管理

## 三个地方

| 位置 | 作用 |
|---|---|
| `deploy/comfyui/models.yaml` | 模型清单：`path`（相对 models 根目录）、`size`、`sha256`、`source`，以及 `mirrors` |
| 谷歌云盘 `tm-models/`（rclone remote `tmgdrive:tm-models`） | 自己的模型仓库，目录结构和 `path` 一致；不怕 Civitai 下架，私有模型也放这里 |
| 运行位置的模型目录 | Modal Volume `tm-comfyui-models`（挂在 `/models`）、新机器的持久盘、本机 aki 的 `ComfyUI/models` |

`fetch_models.py` 取模型的顺序：`--local-root` 本机目录 → `mirrors` 模型仓库 → 每个模型的 `source`
（`civitai` 按 sha256 查 Civitai，需要 `CIVITAI_TOKEN`；`url` 直接下载，HF 链接要钉到 commit；`mirror` 表示没有公开来源）。
不管从哪来，都按 `size` + `sha256` 校验，不对就失败。

本机模型目录：`D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI/models` 和 `G:/AI/draw/models`。
本机 Google Drive 桌面版把云盘镜像在 `G:\GoogleDrive`，放进 `G:\GoogleDrive\tm-models` 的文件会自动上传。

## 新增一个模型

1. 确认 workflow 里引用的路径（API workflow 的下拉值，Windows 导出的 `\` 云端会改成 `/`），模型放进本机 aki 对应目录。
2. 在 `models.yaml` 加一条：`path`、`size`（字节）、`sha256`（小写十六进制）、`source`。
   大小和哈希用 Python 算：`hashlib.sha256` 分块读文件；不要手抄。
3. 放进模型仓库（只复制清单里的模型，复制后校验）：

   ```bash
   uv run python deploy/comfyui/fetch_models.py --no-mirrors --local-root "D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI/models" --local-root "G:/AI/draw/models" --dest "G:/GoogleDrive/tm-models" --only "<path>"
   ```

4. 等桌面版上传完，核对仓库（对比大小和谷歌给出的 sha256，不下载）：

   ```bash
   uv run python deploy/comfyui/fetch_models.py --check-mirrors
   ```

5. 拉到 Modal Volume（在云端下载，走机房带宽，CPU 费用几分钱以内；不需要重新部署）：

   ```bash
   uv run modal run deploy/comfyui/providers/modal_app.py::download --only "<path>"
   ```

   仓库没有时也可以从本机直接传：`modal run deploy/comfyui/providers/modal_app.py::upload --local-roots "<目录1>;<目录2>"`。
6. 跑 `comfyui-check ... --manifest deploy/comfyui/manifest.yaml`，确认 `missing_models` 为空；需要时加 `--live` 对照云端。

## 凭据怎么流动

- 本机：rclone（winget 装在 `%LOCALAPPDATA%\Microsoft\WinGet\Links\rclone.exe`）的 remote `tmgdrive`，
  只读权限，配置在 `%APPDATA%\rclone\rclone.conf`。当前 agent 进程的 PATH 可能还没有它，必要时把上面的目录加进 PATH。
- Modal：`modal run ...::download` 时，`modal_app.py` 从本机 rclone 配置取出 `tmgdrive`，转成
  `RCLONE_CONFIG_TMGDRIVE_*` 环境变量，只随这一次调用传入，不写进部署好的 app。`CIVITAI_TOKEN` 同理。
- 其他平台：把 `tmgdrive` 的 `TYPE`、`SCOPE`、`TOKEN` 设成 `RCLONE_CONFIG_TMGDRIVE_<项名大写>` 环境变量，再跑 `fetch_models.py`。
- 凭据只在进程间传，不打印、不写进仓库或聊天。`rclone config dump` 会输出 token，只能在程序里读取，不要直接显示。

## 已知限制

- `tmgdrive` 用的是 rclone 公共的谷歌 client_id，rclone 官方说它会在 2026 年内停用。停用后仓库读不了，
  `fetch_models.py` 会打印 `skip mirror ...` 并退回 `source`。修复方式：用户在谷歌云控制台建服务账号，
  把 `tm-models` 文件夹以「查看者」共享给它，再把 `tmgdrive` 改成 `service_account_file`（云端改传 `SERVICE_ACCOUNT_CREDENTIALS`）。
  这一步需要用户本人登录谷歌操作。
- 云盘到 Modal 实测约 3–9 MB/s，大 checkpoint 要十几分钟以上。
- 换掉存储（R2、B2 等）只需改 `models.yaml` 的 `mirrors` 和 rclone 配置，代码不用动。

## 规则

- 清单里的 `sha256` 是模型身份，来源 URL 只是取法；Civitai 下架不影响已经在仓库里的模型。
- 不要用谷歌云盘的公开分享链接分发模型。
- 改 `fetch_models.py` 后跑 `uv run pytest tests/test_comfyui_fetch_models.py -q`。
