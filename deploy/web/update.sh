#!/usr/bin/env bash
# 拉取代码后重新安装依赖、构建前端并重启服务。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

uv sync --frozen
(cd web && npm ci && npm run build)
systemctl restart promptatelier-web

# 等服务真正可用；超时则打印日志并以失败退出，方便 start.sh 记录。
for _ in $(seq 1 30); do
    if curl -fsS -m 2 http://127.0.0.1:8766/api/health >/dev/null 2>&1; then
        echo "promptatelier-web is healthy"
        exit 0
    fi
    sleep 1
done
echo "promptatelier-web did not become healthy within 30s" >&2
journalctl -u promptatelier-web --no-pager -n 20 >&2
exit 1
