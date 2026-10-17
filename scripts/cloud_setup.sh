#!/usr/bin/env bash
# 在 Linux 云端机器（如 Claude Code 云会话）上把 PromptAtelier 装成可跑状态：
#   1. 拉本仓库子模块（vendor/ai-image-gateway 等）
#   2. 选一个带 tkinter 的 Python 做 uv sync（task_tools 的测试会 import tkinter）
#   3. 装前端依赖
#   4. 拉 TagsHub 素材库及其子模块（画风 / 角色 / 动作改2 / 背景 / vibe）
#   5. 生成 configs/cloud.yaml，design_root 指向 TagsHub
#
# 用法：bash scripts/cloud_setup.sh
# 可重复执行，已经装好的步骤会跳过或增量更新。
#
# 环境变量：
#   TAGSHUB_DIR     素材库放哪，默认是本仓库同级的 TagsHub 目录
#   TAGSHUB_URL     素材库地址，默认 https://github.com/WeissGoat/TagsHub
#   TAGSHUB_PINNED  设为 1 时子模块用 TagsHub 记录的提交；默认拉各子仓库的最新分支
#
# 素材库子模块是私有仓库，机器上要有能读它们的 GitHub 权限。
# Claude Code 云会话里拉不下来时，让 Claude 把这几个仓库加到会话里再重跑本脚本。
#
# 不写任何 token：NovelAI 走 NAI_ACCESS_TOKEN，Modal 走 TM_COMFYUI_MODAL_TOKEN 环境变量。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
TAGSHUB_DIR="${TAGSHUB_DIR:-$(dirname "$ROOT")/TagsHub}"
TAGSHUB_URL="${TAGSHUB_URL:-https://github.com/WeissGoat/TagsHub}"
CONFIG_OUT="$ROOT/configs/cloud.yaml"
WARNINGS=()

step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; WARNINGS+=("$*"); }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v uv >/dev/null || die "缺少 uv"
command -v npm >/dev/null || die "缺少 npm"

step "本仓库子模块"
git -C "$ROOT" submodule update --init --recursive || die "子模块拉取失败（vendor/ai-image-gateway 是 uv sync 的依赖）"

step "选 Python 解释器"
has_tk() { "$1" -c "import tkinter" >/dev/null 2>&1; }
find_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null && has_tk "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}
PYTHON="$(find_python)"
if [ -z "$PYTHON" ] && command -v apt-get >/dev/null && [ "$(id -u)" = 0 ]; then
    echo "没有带 tkinter 的 Python，安装 python3-tk"
    apt-get install -y python3-tk >/dev/null 2>&1 \
        || { apt-get update >/dev/null 2>&1 && apt-get install -y python3-tk >/dev/null 2>&1; }
    PYTHON="$(find_python)"
fi
if [ -n "$PYTHON" ]; then
    echo "使用 $PYTHON"
    uv sync --python "$PYTHON" || die "uv sync 失败"
else
    warn "找不到带 tkinter 的 Python，task_tools 相关测试会失败"
    uv sync || die "uv sync 失败"
fi

step "前端依赖"
if [ ! -d "$ROOT/web/node_modules" ] || [ "$ROOT/web/package-lock.json" -nt "$ROOT/web/node_modules" ]; then
    (cd "$ROOT/web" && npm ci --no-audit --no-fund) || die "npm ci 失败"
else
    echo "web/node_modules 已是最新"
fi

step "TagsHub 素材库 -> $TAGSHUB_DIR"
export GIT_LFS_SKIP_SMUDGE=1
if [ -d "$TAGSHUB_DIR/.git" ]; then
    git -C "$TAGSHUB_DIR" pull --ff-only || warn "TagsHub 主仓库更新失败，继续用本地版本"
elif [ -e "$TAGSHUB_DIR" ]; then
    die "$TAGSHUB_DIR 已存在但不是 git 仓库"
else
    git clone --depth 1 "$TAGSHUB_URL" "$TAGSHUB_DIR" || die "TagsHub 克隆失败"
fi

submodule_args=(--init --depth 1)
[ "${TAGSHUB_PINNED:-0}" = 1 ] || submodule_args+=(--remote)
mapfile -t SUBMODULES < <(git -C "$TAGSHUB_DIR" config -f .gitmodules --get-regexp '\.path$' | cut -d' ' -f2-)
for path in "${SUBMODULES[@]}"; do
    if GIT_TERMINAL_PROMPT=0 git -C "$TAGSHUB_DIR" submodule update "${submodule_args[@]}" -- "$path" >/dev/null 2>&1; then
        printf '  %-10s %s\n' "$path" "$(git -C "$TAGSHUB_DIR/$path" rev-parse --short HEAD)"
    else
        url="$(git -C "$TAGSHUB_DIR" config -f .gitmodules "submodule.$path.url")"
        warn "素材库子模块 $path 拉取失败（$url），检查是否有该私有仓库的读权限"
    fi
done

step "生成 $CONFIG_OUT"
# 以 local.example.yaml 为底；本机 local.yaml 里的 comfyui 目标（非密钥）一并带上，NovelAI token 不落盘。
TAGSHUB_DIR="$TAGSHUB_DIR" CONFIG_OUT="$CONFIG_OUT" uv run --no-sync python - <<'PY' || die "生成配置失败"
import os
from pathlib import Path

import yaml

root = Path.cwd()
config = yaml.safe_load((root / "configs/local.example.yaml").read_text(encoding="utf-8"))
local = root / "configs/local.yaml"
if local.exists():
    comfyui = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}).get("comfyui")
    if comfyui:
        config["comfyui"] = comfyui
design_root = Path(os.environ["TAGSHUB_DIR"]).resolve()
config["legacy"] = {"tags_machine_root": str(design_root.parent), "design_root": str(design_root)}
# examples/project 下的集合文件写的是 Windows 本机路径，云端读不到。
config["web"]["project_requires"] = []
config["novelai"]["access_token"] = None
Path(os.environ["CONFIG_OUT"]).write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
)
PY
echo "design_root: $TAGSHUB_DIR"

step "完成"
for message in "${WARNINGS[@]}"; do
    echo "WARNING: $message"
done
[ -n "${NAI_ACCESS_TOKEN:-}" ] || echo "提示：未设置 NAI_ACCESS_TOKEN，NovelAI 只能 dry-run"
cat <<EOF
启动 Web：uv run python scripts/dev_web.py --no-reload-backend --config configs/cloud.yaml
命令行：  uv run python -m tags_machine_core render-plan-nodes --config configs/cloud.yaml ...
EOF
[ ${#WARNINGS[@]} -eq 0 ]
