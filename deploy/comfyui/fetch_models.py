#!/usr/bin/env python3
"""按 models.yaml 把模型放进 models 目录并校验 sha256。

与云平台无关：在云端容器里运行时 --dest 指向挂载的持久存储；
在本机或裸主机上可以用 --local-root 从已有目录复制。
来源依次是：--local-root、自己的模型仓库（models.yaml 的 mirrors，rclone remote）、
每个模型的 source（civitai 按 sha256 查 Civitai，读取 CIVITAI_TOKEN；url 直接下载）。
依赖：PyYAML、requests；用仓库时还要有 rclone 命令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import requests
import yaml


HERE = Path(__file__).resolve().parent
CIVITAI_BY_HASH_URL = "https://civitai.com/api/v1/model-versions/by-hash/{sha256}"
CHUNK_SIZE = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=str(HERE / "models.yaml"), help="Model list file")
    parser.add_argument("--dest", help="Models root, e.g. /models")
    parser.add_argument(
        "--local-root",
        action="append",
        default=[],
        help="Existing local models root to copy from (repeatable)",
    )
    parser.add_argument(
        "--mirror",
        action="append",
        help="rclone remote of your own model store, e.g. tmgdrive:tm-models "
        "(repeatable; replaces the mirrors in the model list)",
    )
    parser.add_argument("--no-mirrors", action="store_true", help="Do not use model stores")
    parser.add_argument(
        "--check-mirrors",
        action="store_true",
        help="Only compare the model stores with the model list, without downloading",
    )
    parser.add_argument("--only", action="append", default=[], help="Only this manifest path")
    parser.add_argument("--verify", action="store_true", help="Re-hash files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would happen")
    args = parser.parse_args()

    models = select_models(load_models(args.models), args.only)
    remotes = [] if args.no_mirrors else args.mirror or load_mirrors(args.models)
    mirrors = [Mirror(remote) for remote in remotes]
    if args.check_mirrors:
        return check_mirrors(models, mirrors)
    if not args.dest:
        parser.error("--dest is required")
    dest_root = Path(args.dest)
    local_roots = [Path(item) for item in args.local_root]
    failures = 0
    for model in models:
        try:
            sync_model(
                model,
                dest_root,
                local_roots,
                mirrors=mirrors,
                verify=args.verify,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001 - 汇总所有失败后再退出
            failures += 1
            print(f"FAILED  {model['path']}: {exc}", file=sys.stderr, flush=True)
    return 1 if failures else 0


def load_models(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(data.get("models") or [])


def load_mirrors(path: str | Path) -> list[str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [str(item["rclone"]) for item in data.get("mirrors") or [] if item.get("rclone")]


class Mirror:
    """自己的模型仓库：一个 rclone remote（谷歌云盘、R2、B2……），目录结构和 models.yaml 的 path 一致。

    连接信息不写在清单里：本机用 rclone config，云端用 RCLONE_CONFIG_<NAME>_* 环境变量。
    """

    def __init__(self, remote: str):
        self.remote = remote.rstrip("/")
        self._files: dict[str, dict] | None = None

    def files(self) -> dict[str, dict]:
        """仓库里的文件（path -> rclone lsjson 条目）；第一次用到时列一次，连不上时为空。"""
        if self._files is None:
            try:
                self._files = self.list_files()
            except RuntimeError as exc:
                print(f"skip    mirror {self.remote}: {exc}", flush=True)
                self._files = {}
        return self._files

    def list_files(self, *, hashes: bool = False) -> dict[str, dict]:
        command = ["lsjson", "--recursive", "--files-only", self.remote]
        if hashes:
            command.insert(1, "--hash")
        output = _rclone(command)
        return {item["Path"]: item for item in json.loads(output or "[]")}

    def has(self, model: dict) -> bool:
        item = self.files().get(model["path"])
        return item is not None and item.get("Size") == model["size"]

    def fetch(self, relative_path: str, target: Path) -> None:
        _rclone(
            [
                "copyto",
                f"{self.remote}/{relative_path}",
                str(target),
                "--stats",
                "10s",
                "--stats-one-line",
                "--stats-log-level",
                "NOTICE",
            ],
            capture=False,
        )


def _rclone(arguments: list[str], *, capture: bool = True) -> str:
    executable = shutil.which("rclone")
    if executable is None:
        raise RuntimeError("rclone is not installed")
    result = subprocess.run(
        [executable, *arguments],
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        detail = (result.stderr or "").strip().splitlines()
        raise RuntimeError(f"rclone {arguments[0]} failed" + (f": {detail[-1]}" if detail else ""))
    return result.stdout or ""


def check_mirrors(models: list[dict], mirrors: list[Mirror]) -> int:
    """对比仓库和清单：缺文件、大小不对，或仓库给出的 sha256 不对都算问题。不下载。"""
    if not mirrors:
        print("no mirrors configured", file=sys.stderr)
        return 1
    problems = 0
    for mirror in mirrors:
        try:
            files = mirror.list_files(hashes=True)
        except RuntimeError as exc:
            print(f"FAILED  {mirror.remote}: {exc}", file=sys.stderr, flush=True)
            problems += 1
            continue
        for model in models:
            item = files.get(model["path"])
            remote_sha256 = str(((item or {}).get("Hashes") or {}).get("sha256") or "").lower()
            if item is None:
                status = "missing"
            elif item.get("Size") != model["size"]:
                status = f"size {item.get('Size')} != manifest {model['size']}"
            elif remote_sha256 and remote_sha256 != model["sha256"]:
                status = f"sha256 {remote_sha256} != manifest"
            else:
                print(f"ok      {mirror.remote}/{model['path']}" + ("" if remote_sha256 else " (size only)"))
                continue
            problems += 1
            print(f"FAILED  {mirror.remote}/{model['path']}: {status}", file=sys.stderr, flush=True)
    return 1 if problems else 0


def select_models(models: list[dict], only: list[str]) -> list[dict]:
    if not only:
        return models
    wanted = {item.replace("\\", "/") for item in only}
    unknown = wanted - {model["path"] for model in models}
    if unknown:
        raise SystemExit("Not in manifest: " + ", ".join(sorted(unknown)))
    return [model for model in models if model["path"] in wanted]


def find_local_model(relative_path: str, roots: list[Path]) -> Path | None:
    for root in roots:
        candidate = root / relative_path
        if candidate.is_file():
            return candidate
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_model(
    model: dict,
    dest_root: Path,
    local_roots: list[Path],
    *,
    mirrors: list[Mirror] | None = None,
    verify: bool,
    dry_run: bool,
) -> None:
    dest = dest_root / model["path"]
    if dest.is_file() and dest.stat().st_size == model["size"]:
        if not verify or sha256_file(dest) == model["sha256"]:
            print(f"ok      {model['path']}", flush=True)
            return
        print(f"hash mismatch, replacing {model['path']}", flush=True)

    local = find_local_model(model["path"], local_roots)
    mirror = None if local else next((item for item in mirrors or [] if item.has(model)), None)
    if dry_run:
        action = "copy" if local else f"pull from {mirror.remote}" if mirror else "download"
        print(f"would {action} {model['path']}", flush=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    if local is not None:
        print(f"copy    {local} -> {model['path']}", flush=True)
        shutil.copyfile(local, partial)
    elif mirror is not None:
        print(f"pull    {mirror.remote}/{model['path']} ({model['size'] / 1024**2:.0f} MB)", flush=True)
        mirror.fetch(model["path"], partial)
    else:
        url, headers = resolve_download(model)
        print(f"fetch   {model['path']} ({model['size'] / 1024**2:.0f} MB)", flush=True)
        download(url, headers, partial)
    check_file(partial, model)
    os.replace(partial, dest)
    print(f"done    {model['path']}", flush=True)


def resolve_download(model: dict) -> tuple[str, dict[str, str]]:
    source = model.get("source")
    if source in (None, "mirror"):
        raise RuntimeError("not in any model store or local root, and it has no public source")
    if source == "url":
        return model["url"], {}
    if source == "civitai":
        token = os.environ.get("CIVITAI_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(
            CIVITAI_BY_HASH_URL.format(sha256=model["sha256"]), headers=headers, timeout=60
        )
        response.raise_for_status()
        version = response.json()
        for item in version.get("files") or []:
            hashes = {key.lower(): str(value).lower() for key, value in (item.get("hashes") or {}).items()}
            if hashes.get("sha256") == model["sha256"] and item.get("downloadUrl"):
                return item["downloadUrl"], headers
        raise RuntimeError("Civitai has no file with this sha256 (removed or private?)")
    raise RuntimeError(f"Unsupported model source: {source!r}")


def download(url: str, headers: dict[str, str], partial: Path) -> None:
    # requests 跨域重定向时会去掉 Authorization，不会把 token 带到 CDN。
    with requests.get(url, headers=headers, stream=True, timeout=(30, 300)) as response:
        if response.status_code in {401, 403}:
            raise RuntimeError(
                f"download rejected with HTTP {response.status_code}; "
                "set CIVITAI_TOKEN for Civitai models"
            )
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        written = 0
        next_report = time.monotonic() + 10
        with partial.open("wb") as handle:
            for chunk in response.iter_content(CHUNK_SIZE):
                handle.write(chunk)
                written += len(chunk)
                if time.monotonic() >= next_report:
                    percent = f" ({written * 100 / total:.0f}%)" if total else ""
                    print(f"        {written / 1024**2:.0f} MB{percent}", flush=True)
                    next_report = time.monotonic() + 10


def check_file(path: Path, model: dict) -> None:
    size = path.stat().st_size
    if size != model["size"]:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"size {size} != manifest {model['size']}")
    digest = sha256_file(path)
    if digest != model["sha256"]:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"sha256 {digest} != manifest {model['sha256']}")


if __name__ == "__main__":
    sys.exit(main())
