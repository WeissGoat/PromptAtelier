"""把出图根目录搬到新位置，并改写记录里指向旧位置的路径。

步骤（每步可单独跑，重复跑不会出错）：
  copy     robocopy 复制（保留创建/修改时间，出图历史按创建时间排序），跳过缩略图缓存
  verify   对比两边的文件数和总大小（缩略图缓存不算）
  rewrite  改写新位置里 JSON/JSONL 中的旧路径（相对的 outputs/...、旧绝对路径），原文件备份到 .web/migration-<时间>/
  finalize 删除旧目录，在原位置建目录链接（junction）指向新位置，文档、PNG 元数据、浏览器缓存里的旧路径照样能打开

用法：
  uv run python tools/migrate_output_root.py all --src outputs --dst G:/ai_auto/output
迁移前先停掉网页后端，并等出图任务跑完。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# .web/thumbs：按图片绝对路径缓存的缩略图，换位置后会重新生成；.web/migration-*：本工具留下的备份
def _skip_web_dir(name: str) -> bool:
    return name == "thumbs" or name.startswith("migration-")
TEXT_SUFFIXES = {".json", ".jsonl"}


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy", str(src), str(dst), "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:2", "/MT:16",
        "/NFL", "/NDL", "/NP", "/XJ", "/XD", str(src / ".web" / "thumbs"),
    ]
    print("running:", " ".join(cmd), flush=True)
    code = subprocess.call(cmd)
    if code >= 8:  # robocopy：0-7 表示成功（含有文件被复制/跳过），8 以上是失败
        raise SystemExit(f"robocopy failed with exit code {code}")


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath).relative_to(root) == Path(".web"):
            dirnames[:] = [name for name in dirnames if not _skip_web_dir(name)]
        for name in filenames:
            yield Path(dirpath) / name


def tree_stats(root: Path) -> tuple[int, int]:
    count = size = 0
    for path in _walk(root):
        count += 1
        size += path.stat().st_size
    return count, size


def verify(src: Path, dst: Path) -> None:
    src_stats = tree_stats(src)
    dst_stats = tree_stats(dst)
    print(f"source: {src_stats[0]} files, {src_stats[1] / 1e9:.2f} GB")
    print(f"target: {dst_stats[0]} files, {dst_stats[1] / 1e9:.2f} GB")
    if src_stats[0] != dst_stats[0]:
        raise SystemExit("file counts differ, not safe to continue")
    if src_stats[1] != dst_stats[1]:
        print("note: total size differs (expected only after rewrite changed JSON files)")


class PathRewriter:
    def __init__(self, old_roots: list[str], new_root: Path):
        # 旧位置的写法：相对 outputs、仓库里的绝对路径；统一成 / 比较，不分大小写
        self.old_roots = sorted({root.replace("\\", "/").rstrip("/").lower() for root in old_roots}, key=len, reverse=True)
        self.new_root = new_root

    def rewrite_string(self, value: str) -> str:
        norm = value.replace("\\", "/")
        lower = norm.lower()
        for old in self.old_roots:
            if lower == old or lower.startswith(old + "/"):
                rest = norm[len(old):].lstrip("/")
                target = self.new_root.joinpath(*rest.split("/")) if rest else self.new_root
                return str(target)
        return value

    def rewrite(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.rewrite_string(data)
        if isinstance(data, list):
            return [self.rewrite(item) for item in data]
        if isinstance(data, dict):
            return {key: self.rewrite(value) for key, value in data.items()}
        return data


def _detect_encoding(path: Path) -> str:
    # PowerShell 写的 JSON 可能是带 BOM 的 UTF-16
    with path.open("rb") as handle:
        head = handle.read(2)
    return "utf-16" if head in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"


def rewrite_paths(src: Path, dst: Path) -> None:
    rewriter = PathRewriter(
        ["outputs", str(src.resolve()), src.resolve().as_posix()],
        dst.resolve(),
    )
    backup = dst / ".web" / f"migration-{time.strftime('%Y%m%d-%H%M%S')}"
    changed = 0
    for path in list(_walk(dst)):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        encoding = _detect_encoding(path)
        try:
            original = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            print(f"skip (unknown encoding): {path}")
            continue
        try:
            if path.suffix.lower() == ".jsonl":
                lines = original.splitlines()
                new_lines = [
                    json.dumps(rewriter.rewrite(json.loads(line)), ensure_ascii=False) if line.strip() else line
                    for line in lines
                ]
                updated = "\n".join(new_lines) + ("\n" if original.endswith("\n") else "")
                same = [json.loads(line) for line in lines if line.strip()] == [
                    json.loads(line) for line in new_lines if line.strip()
                ]
            else:
                data = json.loads(original)
                new_data = rewriter.rewrite(data)
                same = new_data == data
                updated = json.dumps(new_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print(f"skip (not valid JSON): {path}")
            continue
        if same:
            continue
        saved = backup / path.relative_to(dst)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        stat = path.stat()
        path.write_text(updated, encoding="utf-16" if encoding == "utf-16" else "utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # 保留修改时间，任务列表排序不变
        changed += 1
    print(f"rewrote {changed} JSON files; originals backed up to {backup}")


def _is_link(path: Path) -> bool:
    return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _force_remove(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def finalize(src: Path, dst: Path) -> None:
    if _is_link(src):
        print(f"{src} is already a link -> {os.readlink(src)}")
        return
    verify(src, dst)
    print(f"deleting {src} ...", flush=True)
    shutil.rmtree(src, onerror=_force_remove)
    subprocess.check_call(["cmd", "/c", "mklink", "/J", str(src), str(dst.resolve())])
    print(f"junction {src} -> {dst.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["copy", "verify", "rewrite", "finalize", "all"])
    parser.add_argument("--src", default="outputs")
    parser.add_argument("--dst", required=True)
    args = parser.parse_args()
    src, dst = Path(args.src).absolute(), Path(args.dst)
    if sys.platform != "win32":
        raise SystemExit("this tool uses robocopy and junctions, run it on Windows")
    if not src.is_dir():
        raise SystemExit(f"source not found: {src}")
    if args.step in {"copy", "all"} and _is_link(src):
        raise SystemExit(f"{src} is already a link, nothing to migrate")
    steps = ["copy", "verify", "rewrite", "finalize"] if args.step == "all" else [args.step]
    for step in steps:
        print(f"== {step}", flush=True)
        if step == "copy":
            copy_tree(src, dst)
        elif step == "verify":
            verify(src, dst)
        elif step == "rewrite":
            rewrite_paths(src, dst)
        elif step == "finalize":
            finalize(src, dst)


if __name__ == "__main__":
    main()
