# ComfyUI 运行环境（与云平台无关）。模型不打进镜像，运行时挂载到 /models。
#   docker build -t tm-comfyui deploy/comfyui
#   docker run --gpus all -p 8188:8188 -v /path/to/models:/models tm-comfyui
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFYUI_DIR=/opt/ComfyUI \
    COMFYUI_MODELS_DIR=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY manifest.yaml install_comfyui.py /opt/tm-comfyui/
COPY patches/ /opt/tm-comfyui/patches/
RUN pip install pyyaml requests \
    && python /opt/tm-comfyui/install_comfyui.py --manifest /opt/tm-comfyui/manifest.yaml

# fetch_models.py 先从自己的模型仓库（rclone remote）拉模型；单独一层，用 Docker 构建时不动上面的安装层。
RUN apt-get update \
    && apt-get install -y --no-install-recommends rclone \
    && rm -rf /var/lib/apt/lists/*

# 放在最后：用 Docker 构建时改模型清单或下载脚本只重跑这一层。
# Modal 把整个 Dockerfile 当成一步，所以 Modal 上不拷这两个文件，改为容器启动时挂载（见 providers/modal_app.py）。
# 容器里填充模型：python /opt/tm-comfyui/fetch_models.py --dest /models
# 仓库的连接信息用环境变量传入，例如 -e RCLONE_CONFIG_TMGDRIVE_TYPE=drive -e RCLONE_CONFIG_TMGDRIVE_TOKEN=...
COPY models.yaml fetch_models.py /opt/tm-comfyui/

WORKDIR /opt/ComfyUI
EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-auto-launch"]
