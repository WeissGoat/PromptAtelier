#!/usr/bin/env python3
"""按 manifest.yaml 安装 ComfyUI 和插件。

与云平台无关：Dockerfile 里调用它，也可以直接在一台 Linux GPU 主机上运行。
依赖：git、Python 3.11、PyYAML。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(HERE / "manifest.yaml"))
    parser.add_argument("--comfyui-dir", default=os.environ.get("COMFYUI_DIR", "/opt/ComfyUI"))
    parser.add_argument(
        "--models-dir",
        default=os.environ.get("COMFYUI_MODELS_DIR", "/models"),
        help="Models root written into extra_model_paths.yaml",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    comfyui_dir = Path(args.comfyui_dir)

    core = manifest["comfyui"]
    git_checkout(core["repo"], core["ref"], comfyui_dir)

    constraints = comfyui_dir / "tm-constraints.txt"
    torch = manifest.get("torch") or {}
    if torch.get("packages"):
        index = ["--index-url", torch["index_url"]] if torch.get("index_url") else []
        pip_install(*torch["packages"], *index)
    constraints.write_text(
        "\n".join([*(torch.get("packages") or []), *(manifest.get("python_constraints") or [])])
        + "\n",
        encoding="utf-8",
    )
    pip_install("-r", str(comfyui_dir / "requirements.txt"), "-c", str(constraints))

    for node in manifest.get("custom_nodes") or []:
        install_custom_node(node, comfyui_dir, constraints, base_dir=manifest_path.parent)

    write_extra_model_paths(comfyui_dir, args.models_dir, manifest.get("model_folders") or {})
    return 0


def install_custom_node(node: dict, comfyui_dir: Path, constraints: Path, *, base_dir: Path) -> None:
    dest = comfyui_dir / "custom_nodes" / node["name"]
    git_checkout(node["repo"], node["ref"], dest)
    if node.get("submodules"):
        run(["git", "-C", str(dest), "submodule", "update", "--init", "--recursive", "--depth", "1"])
    for patch in node.get("patches") or []:
        run(["git", "-C", str(dest), "apply", str(base_dir / patch)])

    requirements = dest / "requirements.txt"
    if not requirements.exists():
        return
    skipped = [str(item).lower() for item in node.get("skip_requirements") or []]
    lines = [
        line
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if not any(token in line.lower() for token in skipped)
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    try:
        pip_install("-r", handle.name, "-c", str(constraints))
    finally:
        os.unlink(handle.name)


def git_checkout(repo: str, ref: str, dest: Path) -> None:
    """按 commit 浅取；重复运行时用 --force 丢弃本地改动，再由补丁重新打上。"""
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q", str(dest)])
        run(["git", "-C", str(dest), "remote", "add", "origin", repo])
    run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1", "origin", ref])
    run(["git", "-C", str(dest), "-c", "advice.detachedHead=false", "checkout", "-q", "--force", "FETCH_HEAD"])


def write_extra_model_paths(comfyui_dir: Path, models_dir: str, folders: dict[str, str]) -> None:
    lines = [
        "# 由 deploy/comfyui/install_comfyui.py 按 manifest.yaml 生成。",
        "tm_models:",
        f"  base_path: {models_dir}",
        "  is_default: true",
        *(f"  {name}: {path}" for name, path in folders.items()),
    ]
    (comfyui_dir / "extra_model_paths.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def pip_install(*args: str) -> None:
    run([sys.executable, "-m", "pip", "install", "--no-cache-dir", *args])


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    sys.exit(main())
