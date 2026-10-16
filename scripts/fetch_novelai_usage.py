#!/usr/bin/env python3
"""NovelAI 会员与 V5 用量查询脚本。

使用方式:
    # 自动读取 configs/local.yaml 或 NAI_ACCESS_TOKEN 环境变量
    python scripts/fetch_novelai_usage.py

    # 显式传入 token
    python scripts/fetch_novelai_usage.py --token pst-xxxx

    # 以 JSON 格式输出
    python scripts/fetch_novelai_usage.py --json

    # 持续轮询监控 (如每 10 秒刷新一次)
    python scripts/fetch_novelai_usage.py --watch 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 将项目 src 添加到 sys.path，支持直接执行脚本
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tags_machine_core.config import load_config
from tags_machine_core.services.novelai_usage import (
    format_usage_summary,
    inquire_novelai_usage,
)


def resolve_token(explicit_token: str | None, config_path: str | None) -> tuple[str | None, str]:
    if explicit_token:
        return explicit_token, "command-line argument"

    env_token = os.environ.get("NAI_ACCESS_TOKEN")
    if env_token:
        return env_token, "environment variable NAI_ACCESS_TOKEN"

    cfg_file = Path(config_path) if config_path else (_REPO_ROOT / "configs" / "local.yaml")
    if not cfg_file.exists():
        cfg_file = _REPO_ROOT / "configs" / "local.example.yaml"

    if cfg_file.exists():
        try:
            cfg = load_config(cfg_file)
            token = cfg.novelai.access_token
            if token:
                return token, f"config file ({cfg_file})"
            token_env = cfg.novelai.access_token_env
            if token_env and os.environ.get(token_env):
                return os.environ.get(token_env), f"env {token_env} (via config {cfg_file})"
        except Exception:
            pass

    return None, "none"


def main():
    parser = argparse.ArgumentParser(description="获取 NovelAI 账号会员状态与 V5 用量监控情况")
    parser.add_argument("--token", "-t", type=str, default=None, help="NovelAI Access Token")
    parser.add_argument("--config", "-c", type=str, default=None, help="配置文件路径 (默认 configs/local.yaml)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--watch", "-w", type=int, default=None, metavar="SECONDS", help="持续轮询监控间隔秒数")
    args = parser.parse_args()

    token, source = resolve_token(args.token, args.config)

    def run_once():
        info = inquire_novelai_usage(token)
        if args.json:
            print(json.dumps(info.model_dump(), ensure_ascii=False, indent=2))
        else:
            print(format_usage_summary(info))
            if not token:
                print(f"  [来源: {source}]")

    if args.watch and args.watch > 0:
        try:
            while True:
                # 终端清屏或输出换行
                if sys.stdout.isatty():
                    os.system("cls" if os.name == "nt" else "clear")
                print(f"[监控运行中 · 刷新间隔 {args.watch}s · Ctrl+C 退出]")
                run_once()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n已退出监控。")
    else:
        run_once()


if __name__ == "__main__":
    main()
