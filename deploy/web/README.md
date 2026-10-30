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

## 刷新动作分类视图（pn_* / stn_*）

`pn_*`、`stn_*` 是本地生成的链接视图，**不在 Git 里**。新机器 clone 完直接起服务，动作池会是空的。

两个自带入口已经带上这个参数，不用手动加：

| 入口 | 实际传参 |
| :--- | :--- |
| `scripts/dev_web.py`（本地开发） | `--refresh-category-view`（与服务器一致：先 `git pull --ff-only` 再补链） |
| `deploy/web/promptatelier-web.service`（服务器） | `--refresh-category-view`（先 `git pull --ff-only` 再补链） |

手动起服务时：

```bash
# 推荐：先 git pull 拿最新 manifest，再按 manifest 增量复刻链接（不改 manifest，秒级完成）
python -m tags_machine_core.web --config configs/server.yaml \
    --refresh-category-view

# 要重新解析 classify.yaml、重算分桶时（会重写 Git 跟踪的 manifest，仅限本机调规则时用）
python -m tags_machine_core.web --config configs/server.yaml \
    --refresh-category-view=rebuild

# 离线 / 不想联网
    --skip-category-view-pull

# 配置文件里没有 legacy.design_root 时显式指定
    --category-view-root /root/project/tags_machine/design/动作改2
```

### 拉取的超时与停滞检测

`git pull` 的超时是**总耗时上限**（每个仓库 300s），不是"多久没响应"。真正的停滞判定交给传输层，用 `git -c` 注入、跟着代码走，换机器无需另配：

| 传输 | 注入参数 | 行为 |
| :--- | :--- | :--- |
| HTTPS | `http.lowSpeedLimit=1000` + `http.lowSpeedTime=20` | 速度低于 1KB/s 持续 20s → 中止 |
| SSH | `core.sshCommand="ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"` | 连不上 10s 放弃；连接静默 45s 放弃；无 TTY 不弹密码 |

已配置 `core.sshCommand` 的机器（如 Windows 用 plink）不会被覆盖，保持用户自己的设置。

慢但在传的拉取会一直传下去；真断流几十秒就退出并降级使用本地 manifest。被强制中止时若 `.git` 下残留 `*.lock`，会上报到报告的 `stale_locks` 字段并给出删除提示，**不会自动删除**（可能有其他 git 进程在操作）。

行为要点：

- 刷新在 uvicorn 启动**之前**同步执行，保证动作池第一次扫描就是完整的。
- `git pull` 走 `--ff-only`，不做先验脏判断：本地有改动但远端没碰这些文件时照常拉取并保留改动；只有远端会覆盖本地改动、或分支已分叉时 git 才中止，报告里给 `reason` 和 `dirty` 文件清单，绝不覆盖本地内容。
- 刷新失败只打印告警，**不影响 Web 启动**；加 `--category-view-strict` 则变为失败即退出（部署校验 / CI 用）。
- 单个链接失败（权限、Windows 路径超长、junction 被占用）只跳过该条，其余照建，报告里 `partial: true` + `stats.errors` 给出前 10 条原因；下次启动自动补。
- 锁等待有截止时间（900s），拿不到锁抛 `TimeoutError` 并降级为告警，不会无声挂住启动。
- 与每天 20:30 的重建任务共用 `动作改2/.category_view.lock`，不会互相删链接。
- 服务器上 `new` 指向 action 仓库；Windows 上必须是 `mklink /J new <action路径>`。
- `--refresh-category-view=rebuild` 中途失败可能留下脏 manifest；报告里会给 `dirty_manifest` + `hint`，按提示 `git checkout -- category_view_manifest.json` 回滚。

## 本地生成服装节点库（服装）

`design/服装` 是 refactor 里 `role=clothing` 池的数据源（`nodes/role_paths.py` 的
`"clothing": ("服装", ...)`）。它由 `动作改2/tools/extract_action_clothes.py` 从动作节点
抽出来，**不入库**——`design/.gitignore` 里已忽略，新机器 clone 完自己生成。

跟分类视图同一个开关：启动时带 `--refresh-category-view` 就会顺带刷新，顺序在
relink 之后（relink 先保证节点可见，再抽服装）。

判断是否要跑只看时间戳：动作库没有新的 `tags.txt` / `classify.yaml` 就跳过（约 1s），
有变化才重跑（约 7s，脚本幂等，已有节点全部 skip）。失败只打一行 `[clothing-pool]` 告警，
Web 照常启动。

| 参数 | 作用 |
| :--- | :--- |
| `--skip-clothing-pool` | 本次启动不生成（离线 / 只调前端时用） |
| `--refresh-clothing-pool` | 忽略时间戳，强制重跑 |
| `--clothing-pool-dir` | 换生成目录；默认 `动作改2` 的兄弟目录 `服装` |

手动重建：

```bash
# 在 design/ 目录下执行
python 动作改2/tools/extract_action_clothes.py --export --export-dir 服装
```

- 锁是独立的 `动作改2/.clothing_pool.lock`（等待上限 120s），不与分类视图锁互相阻塞。
- 生成成功但产出 0 个节点时按失败处理（源库可能为空），报告里给 `error`。

## 运维

```bash
systemctl status promptatelier-web
journalctl -u promptatelier-web -f
```

- 输出图片写在 `outputs/`，注意磁盘空间。
- 出图历史默认只列 `outputs/` 下的批次；`configs/server.yaml` 的 `web.history_roots` 可以追加目录（如定时跑图的 `design/auto`），每个日期子目录显示为 `auto · YYYYMMDD` 一批。stop.sh 上传后会删除本地图片，所以只能看到还没上传的那部分。
- ComfyUI Modal 目标需要 `TM_COMFYUI_MODAL_TOKEN`（写在 `.env`）；云端状态探测还需要 Modal SDK 凭据（`modal token new` 生成 `~/.modal.toml`）。
- “打开所在文件夹”只在 Windows 本地可用，服务器上会返回 501。
