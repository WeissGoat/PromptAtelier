"""Modal 适配层：只放 Modal 特有的东西。运行环境来自 ../Dockerfile 和 ../manifest.yaml。

    部署 API：      modal deploy deploy/comfyui/providers/modal_app.py
    本机上传模型：  modal run deploy/comfyui/providers/modal_app.py::upload --local-roots "D:/models;G:/models"
    云端下载模型：  modal run deploy/comfyui/providers/modal_app.py::download
    临时 UI：       modal run deploy/comfyui/providers/modal_app.py::ui

模型清单（../models.yaml）在运行时从本机读取，改清单不需要重新构建镜像。
云端下载先从模型仓库（清单里的 mirrors）拉，连接信息取自本机的 rclone 配置；
没有的再走 Civitai（本机 CIVITAI_TOKEN）或原链接。这些凭据只随这次调用传入，不写进部署好的 app。

可用环境变量覆盖：TM_COMFYUI_MODAL_GPU（默认 L40S）、TM_COMFYUI_MODAL_UI_GPU（默认 L4）、
TM_COMFYUI_MODAL_APP、TM_COMFYUI_MODAL_VOLUME。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import modal


RUNTIME_DIR = Path(__file__).resolve().parents[1]
APP_NAME = os.environ.get("TM_COMFYUI_MODAL_APP", "tm-comfyui")
VOLUME_NAME = os.environ.get("TM_COMFYUI_MODAL_VOLUME", "tm-comfyui-models")
API_GPU = os.environ.get("TM_COMFYUI_MODAL_GPU", "L40S")
UI_GPU = os.environ.get("TM_COMFYUI_MODAL_UI_GPU", "L4")
MODELS_DIR = "/models"
COMFYUI_DIR = "/opt/ComfyUI"
PORT = 8188
COMFYUI_COMMAND = ["python", "main.py", "--listen", "0.0.0.0", "--port", str(PORT), "--disable-auto-launch"]
MINUTES = 60

# 模型清单和下载脚本常改，而 Modal 把整个 Dockerfile 当成一步，任何改动都从头重建（约 15 分钟）；
# 所以 Modal 上这两个文件不进镜像，容器启动时挂到 Dockerfile 里同样的位置。
RUNTIME_FILES = ("models.yaml", "fetch_models.py")
DOCKERFILE = Path(tempfile.gettempdir()) / "tm-comfyui.Dockerfile"


def _write_modal_dockerfile() -> None:
    """写一份给 Modal 用的 Dockerfile：去掉注释和拷贝 RUNTIME_FILES 的那一行。

    Modal 按系统默认编码读 Dockerfile，中文 Windows 上是 GBK，读不了中文注释；副本只剩 ASCII 指令，
    顺带改注释也不会触发重建。
    """
    lines = []
    for line in (RUNTIME_DIR / "Dockerfile").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "COPY" and set(parts[1:-1]) <= set(RUNTIME_FILES):
            continue
        lines.append(line + "\n")
    DOCKERFILE.write_text("".join(lines), encoding="ascii", newline="\n")


if modal.is_local():  # 容器里只导入模块，不构建镜像
    _write_modal_dockerfile()
image = modal.Image.from_dockerfile(DOCKERFILE, context_dir=RUNTIME_DIR)
for _name in RUNTIME_FILES:
    image = image.add_local_file(RUNTIME_DIR / _name, f"/opt/tm-comfyui/{_name}")
models = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
app = modal.App(APP_NAME)


@app.function(
    image=image,
    gpu=API_GPU,
    volumes={MODELS_DIR: models},
    # ComfyUI 的队列、history 和输出图都在单个容器里，/prompt、/history、/view 必须落到同一个容器；
    # 这也顺便给 GPU 花费封了顶。
    max_containers=1,
    # 不要常驻：一台 L40S 常驻一个月约 $1,400。
    min_containers=0,
    scaledown_window=3 * MINUTES,
    timeout=15 * MINUTES,
)
@modal.concurrent(max_inputs=32)
@modal.web_server(PORT, startup_timeout=5 * MINUTES, requires_proxy_auth=True)
def api():
    """ComfyUI 原生 HTTP API。请求需带 Authorization: Bearer <proxy token id>.<secret>。"""
    subprocess.Popen(COMFYUI_COMMAND, cwd=COMFYUI_DIR)


@app.function(
    image=image,
    gpu=UI_GPU,
    volumes={MODELS_DIR: models},
    max_containers=1,
    timeout=2 * 60 * MINUTES,
)
def ui():
    """临时交互 UI：打印一个随机隧道地址；Ctrl+C 结束 modal run 或 2 小时后自动关闭。

    ComfyUI 前端会一直连着 websocket，标签页开着就一直按秒计费。
    """
    process = subprocess.Popen(COMFYUI_COMMAND, cwd=COMFYUI_DIR)
    _wait_for_port(PORT, timeout=5 * MINUTES)
    with modal.forward(PORT) as tunnel:
        print(f"ComfyUI UI: {tunnel.url}", flush=True)
        process.wait()


@app.function(
    image=image,
    volumes={MODELS_DIR: models},
    timeout=2 * 60 * MINUTES,
)
def download_models(
    models_yaml: str,
    only: str = "",
    verify: bool = False,
    env: dict[str, str] | None = None,
):
    """在云端下载并校验模型（不占用本机上行带宽）。models_yaml 是模型清单内容。

    verify=True 时对 Volume 上已有的文件重新计算 sha256。
    env 是这次下载用的凭据（模型仓库的 rclone 配置、CIVITAI_TOKEN），只给下载进程用。
    """
    models_file = Path("/tmp/models.yaml")
    models_file.write_text(models_yaml, encoding="utf-8")
    command = [
        sys.executable,
        "/opt/tm-comfyui/fetch_models.py",
        "--models",
        str(models_file),
        "--dest",
        MODELS_DIR,
    ]
    for item in filter(None, only.split(";")):
        command += ["--only", item]
    if verify:
        command.append("--verify")
    result = subprocess.run(command, env={**os.environ, **(env or {})})
    models.commit()
    if result.returncode:
        raise RuntimeError("some models failed to download; see the log above")


@app.local_entrypoint()
def download(only: str = "", verify: bool = False):
    """按本机的 models.yaml 在云端下载模型；only 用分号分隔多个路径，--verify 重新校验已有文件。"""
    download_models.remote(
        (RUNTIME_DIR / "models.yaml").read_text(encoding="utf-8"), only, verify, _download_env()
    )


def _download_env() -> dict[str, str]:
    """云端下载要用的凭据：本机的 CIVITAI_TOKEN，和清单里模型仓库的 rclone 配置。"""
    sys.path.insert(0, str(RUNTIME_DIR))
    import fetch_models

    env = {"CIVITAI_TOKEN": os.environ["CIVITAI_TOKEN"]} if os.environ.get("CIVITAI_TOKEN") else {}
    remotes = fetch_models.load_mirrors(RUNTIME_DIR / "models.yaml")
    for name in sorted({remote.split(":", 1)[0] for remote in remotes}):
        prefix = f"RCLONE_CONFIG_{name.upper()}_"
        remote_env = {key: value for key, value in os.environ.items() if key.startswith(prefix)}
        remote_env = remote_env or _rclone_remote_env(name, prefix)
        if not remote_env:
            print(f"mirror {name}: no rclone config on this machine; the cloud will use each model's source")
        env.update(remote_env)
    return env


def _rclone_remote_env(name: str, prefix: str) -> dict[str, str]:
    """把本机 rclone config 里的一个 remote 转成 RCLONE_CONFIG_<NAME>_* 环境变量（不打印）。"""
    executable = shutil.which("rclone")
    if executable is None:
        return {}
    result = subprocess.run(
        [executable, "config", "dump"], capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode:
        return {}
    section = json.loads(result.stdout or "{}").get(name) or {}
    return {prefix + key.upper(): str(value) for key, value in section.items() if value not in ("", None)}


@app.local_entrypoint()
def upload(local_roots: str, only: str = "", force: bool = False):
    """从本机目录上传 manifest 里的模型；Volume 上已有且大小一致的跳过。

    local_roots 用分号分隔，例如 "D:/AI/ComfyUI-aki/ComfyUI-aki-v1.6/ComfyUI/models;G:/AI/draw/models"。
    """
    sys.path.insert(0, str(RUNTIME_DIR))
    import fetch_models

    all_models = fetch_models.load_models(RUNTIME_DIR / "models.yaml")
    roots = [Path(item.strip()) for item in local_roots.split(";") if item.strip()]
    selected = fetch_models.select_models(all_models, [item for item in only.split(";") if item])
    existing = {
        entry.path.lstrip("/"): entry.size for entry in models.listdir("/", recursive=True)
    }

    pending: list[tuple[Path, str]] = []
    missing: list[str] = []
    for model in selected:
        if not force and existing.get(model["path"]) == model["size"]:
            print(f"ok      {model['path']}")
            continue
        local = fetch_models.find_local_model(model["path"], roots)
        if local is None:
            missing.append(model["path"])
            continue
        print(f"verify  {local}")
        digest = fetch_models.sha256_file(local)
        if digest != model["sha256"]:
            raise SystemExit(f"{local}: sha256 {digest} != manifest {model['sha256']}")
        pending.append((local, model["path"]))

    if pending:
        with models.batch_upload(force=True) as batch:
            for local, remote in pending:
                print(f"upload  {local} -> {remote}")
                batch.put_file(local, "/" + remote)
    if missing:
        print("not found locally (use download_models or add --local-roots):")
        for path in missing:
            print(f"  {path}")


def _wait_for_port(port: int, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError(f"ComfyUI did not listen on port {port} within {timeout:.0f}s")
