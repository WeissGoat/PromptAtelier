"""契约文件的存放：`<contract.root>/<id>.md`，平铺，一个任务一个文件（§3）。"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .models import ParsedContract
from .parser import ContractParseError, parse_contract


CONTRACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


class ContractConflictError(RuntimeError):
    """保存时文件已被外部修改（hash 不一致）。"""

    def __init__(self, contract_id: str, current_hash: str):
        self.contract_id = contract_id
        self.current_hash = current_hash
        super().__init__(f"契约 {contract_id} 已被其他程序修改，请重新载入后再保存")


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ContractFile:
    id: str
    path: Path
    text: str
    mtime: float

    @property
    def hash(self) -> str:
        return text_hash(self.text)


@dataclass
class _IndexEntry:
    mtime_ns: int
    size: int
    summary: dict


class ContractStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = threading.RLock()
        self._index: dict[str, _IndexEntry] = {}

    def path_for(self, contract_id: str) -> Path:
        if not CONTRACT_ID_RE.match(contract_id or ""):
            raise ValueError(f"无效的契约 id：{contract_id!r}")
        return self.root / f"{contract_id}.md"

    def exists(self, contract_id: str) -> bool:
        return self.path_for(contract_id).is_file()

    def read(self, contract_id: str) -> ContractFile:
        path = self.path_for(contract_id)
        if not path.is_file():
            raise FileNotFoundError(f"契约不存在：{contract_id}")
        text = path.read_text(encoding="utf-8")
        return ContractFile(id=contract_id, path=path, text=text, mtime=path.stat().st_mtime)

    def write(self, contract_id: str, text: str, *, expected_hash: str | None = None, create: bool = False) -> ContractFile:
        path = self.path_for(contract_id)
        with self._lock:
            if create:
                if path.exists():
                    raise FileExistsError(f"契约已存在：{contract_id}")
            elif expected_hash is not None:
                current = path.read_text(encoding="utf-8") if path.is_file() else ""
                if text_hash(current) != expected_hash:
                    raise ContractConflictError(contract_id, text_hash(current))
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.tmp")
            temp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(temp, path)
        return self.read(contract_id)

    def unique_id(self, base: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_.\-]+", "_", base).strip("_.-") or "contract"
        candidate = base
        suffix = 2
        while self.path_for(candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    # ---- 列表与索引（按 mtime 缓存解析结果，§5.5） ----

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            (path.stem for path in self.root.glob("*.md") if CONTRACT_ID_RE.match(path.stem)),
            reverse=True,
        )

    def summaries(self) -> list[dict]:
        result: list[dict] = []
        seen: set[str] = set()
        for contract_id in self.list_ids():
            seen.add(contract_id)
            summary = self._summary(contract_id)
            if summary is not None:
                result.append(summary)
        with self._lock:
            for stale in set(self._index) - seen:
                self._index.pop(stale, None)
        return result

    def changed_since(self, since: float) -> list[dict]:
        return [item for item in self.summaries() if item["mtime"] > since]

    def _summary(self, contract_id: str) -> dict | None:
        path = self.path_for(contract_id)
        try:
            stat = path.stat()
        except OSError:
            return None
        with self._lock:
            cached = self._index.get(contract_id)
            if cached and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
                return cached.summary
        try:
            contract = parse_contract(path.read_text(encoding="utf-8"))
            summary = contract_summary(contract_id, contract, stat.st_mtime)
        except (ContractParseError, ValueError, OSError) as exc:
            summary = {
                "id": contract_id,
                "title": "",
                "status": "invalid",
                "error": str(exc),
                "mtime": stat.st_mtime,
                "frame_count": 0,
                "nodes": {},
            }
        with self._lock:
            self._index[contract_id] = _IndexEntry(stat.st_mtime_ns, stat.st_size, summary)
        return summary


def contract_summary(contract_id: str, contract: ParsedContract, mtime: float) -> dict:
    request = contract.request
    nodes = request.nodes
    return {
        "id": contract_id,
        "title": request.title,
        "status": request.status,
        "created_at": request.created_at,
        "target_format": request.target_format,
        "frame_count": len(contract.frames),
        "mtime": mtime,
        "requirements": request.requirements,
        "nodes": {
            "characters": {key: entry.ref for key, entry in nodes.characters.items()},
            "action_group": nodes.action_group.ref if nodes.action_group else None,
            "clothing": nodes.clothing.ref if nodes.clothing else None,
            "background": nodes.background.ref if nodes.background else None,
        },
    }
