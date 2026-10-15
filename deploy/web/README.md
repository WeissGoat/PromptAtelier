# PromptAtelier Web 服务器部署

在 Linux 服务器上长期运行 PromptAtelier Web。与本地开发（`scripts/dev_web.py`，Vite + 热重载）不同，服务器上只跑一个 uvicorn 进程：前端先构建成静态文件，由后端用 `--static-dir` 同源托管，浏览器通过相对路径 `/api` 调后端，不涉及跨域。

服务只监听 `127.0.0.1:8766`。API 没有鉴权，能访问它就能写回节点源文件、消耗 NovelAI 额度，**不要直接绑定 `0.0.0.0` 暴露到公网**。

## 首次安装

在 `refactor` 目录执行：

```bash
# 1. 服务器配置：Linux 路径，ComfyUI 默认走 Modal。configs/server.yaml 不提交。
cp configs/server.example.yaml configs/server.yaml
#    填写 novelai.access_token，或在 .env 中设置 NAI_ACCESS_TOKEN。

# 2. 依赖与前端构建
uv sync --frozen
(cd web && npm ci && npm run build)

# 3. systemd
cp deploy/web/promptatelier-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now promptatelier-web
```

8765 在当前服务器上已被其他服务占用，因此使用 8766。

## 访问

在自己的电脑上开 SSH 隧道，然后浏览器打开 <http://127.0.0.1:8766>：

```bash
ssh -N -L 8766:127.0.0.1:8766 root@<服务器>
```

需要免隧道访问时，在前面加一层带登录的入口（Cloudflare Tunnel + Cloudflare Access、Tailscale 等），不要裸露端口。

## 更新

```bash
git pull && git submodule update
deploy/web/update.sh
```

`update.sh` 会同步 Python 依赖、重新构建前端、重启服务并等待健康检查通过。服务器上的 `../start.sh`（cron 每天 02:00）在拉取代码后会自动调用它。

## 运维

```bash
systemctl status promptatelier-web
journalctl -u promptatelier-web -f
```

- 输出图片写在 `outputs/`，注意磁盘空间。
- ComfyUI Modal 目标需要 `TM_COMFYUI_MODAL_TOKEN`（写在 `.env`）；云端状态探测还需要 Modal SDK 凭据（`modal token new` 生成 `~/.modal.toml`）。
- “打开所在文件夹”只在 Windows 本地可用，服务器上会返回 501。
