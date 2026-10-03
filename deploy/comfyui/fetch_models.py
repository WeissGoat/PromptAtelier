#!/usr/bin/env python3
"""按 models.yaml 把模型放进 models 目录并校验 sha256。

与云平台无关：在云端容器里运行时 --dest 指向挂载的持久存储；
在本机或裸主机上可以用 --local-root 从已有目录复制。
来源：source: civitai 按 sha256 查 Civitai（读取 CIVITAI_TOKEN 环境变量）；source: url 直接下载。
依赖：PyYAML、requests。
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
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
    parser.add_argument("--dest", required=True, help="Models root, e.g. /models")
    parser.add_argument(
        "--local-root",
        action="append",
        default=[],
        help="Existing local models root to copy from (repeatable)",
    )
    parser.add_argument("--only", action="append", default=[], help="Only this manifest path")
    parser.add_argument("--verify", action="store_true", help="Re-hash files that already exist")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would happen")
    args = parser.parse_args()

    models = load_models(args.models)
    dest_root = Path(args.dest)
    local_roots = [Path(item) for item in args.local_root]
    failures = 0
    for model in select_models(models, args.only):
        try:
            sync_model(model, dest_root, local_roots, verify=args.verify, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001 - 汇总所有失败后再退出
            failures += 1
            print(f"FAILED  {model['path']}: {exc}", file=sys.stderr, flush=True)
    return 1 if failures else 0


def load_models(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(data.get("models") or [])


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
    if dry_run:
        print(f"would {'copy' if local else 'download'} {model['path']}", flush=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    if local is not None:
        print(f"copy    {local} -> {model['path']}", flush=True)
        shutil.copyfile(local, partial)
    else:
        url, headers = resolve_download(model)
        print(f"fetch   {model['path']} ({model['size'] / 1024**2:.0f} MB)", flush=True)
        download(url, headers, partial)
    check_file(partial, model)
    os.replace(partial, dest)
    print(f"done    {model['path']}", flush=True)


def resolve_download(model: dict) -> tuple[str, dict[str, str]]:
    source = model.get("source")
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
