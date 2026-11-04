"""契约的来源节点：动作组（st_* / stn_*）及其成员、角色、服装、背景。

动作内容沿用 NodeReader 读取，不改读取规则（§0）：
- `stn_*` 成员（有 meta.yaml）：正面取 `tags.action`，负面取 `negative_prompt`；
- `st_*` 成员（只有 tags.txt）：正面取 `=` 之前的行，负面为空，`=` 之后的扩展行不解析。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes import NodeReader
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.role_paths import primary_role_root


ACTION_GROUP_PREFIXES = ("st_", "stn_")
NODE_FILES = ("node.yaml", "meta.yaml", "tags.txt")
CLASSIFY_SUMMARY_KEYS = ("phase", "cast", "pose", "environment", "clothing", "domain", "tone", "flags")
_LEADING_NUMBER_RE = re.compile(r"^(\d+)[_\-\s]*")


def content_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def node_content_hash(node: NodeDocument) -> str:
    return content_hash(node.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"path"}))


def has_node_file(path: Path) -> bool:
    return any((path / name).exists() for name in NODE_FILES)


def is_action_group_name(name: str) -> bool:
    return name.startswith(ACTION_GROUP_PREFIXES)


def _natural_key(name: str) -> tuple[int, str]:
    match = _LEADING_NUMBER_RE.match(name)
    return (int(match.group(1)) if match else 1_000_000, name)


def _strip_order_prefix(name: str) -> str:
    stripped = _LEADING_NUMBER_RE.sub("", name, count=1)
    return stripped or name


@dataclass
class ActionMember:
    index: int
    name: str
    ref: str
    group_ref: str | None
    path: Path
    node: NodeDocument
    positive: str
    negative: str
    source_file: str
    classify: dict[str, Any] = field(default_factory=dict)
    # 成员链接指向的目录名（new/<id> 的 <id>），机器上没有 new/ 时也能按它找到成员。
    link_name: str | None = None

    @property
    def title(self) -> str:
        # new/20260922_0028_01_俯身吐舌 → 俯身吐舌；01_推门进教室 → 推门进教室
        tail = self.name
        match = re.match(r"^\d{8}_\d{4}_\d+_(.+)$", tail)
        if match:
            return match.group(1)
        return _strip_order_prefix(tail)

    @property
    def character_scope(self) -> str | None:
        return self.node.character_scope or (self.node.composition or {}).get("character_scope")

    @property
    def clothing_state(self) -> str | None:
        state = (self.node.clothing or {}).get("state")
        return str(state) if state else None

    def aliases(self) -> set[str]:
        values = {self.ref, self.name, self.ref.rsplit("/", 1)[-1], f"#{self.index}", str(self.index)}
        if self.link_name:
            values.add(self.link_name)
        if self.group_ref:
            values.add(self.group_ref)
        return {_normalize_ref(value) for value in values if value}

    def summary(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "title": self.title,
            "ref": self.ref,
            "group_ref": self.group_ref,
            "path": str(self.path),
            "positive": self.positive,
            "negative": self.negative,
            "source_file": self.source_file,
            "classify": self.classify,
            "character_scope": self.character_scope,
            "clothing_state": self.clothing_state,
        }


@dataclass
class ActionGroup:
    ref: str
    path: Path
    members: list[ActionMember]

    @property
    def name(self) -> str:
        return self.path.name

    def find_member(self, value: str | None) -> ActionMember | None:
        if not value:
            return None
        key = _normalize_ref(value)
        found = next((member for member in self.members if key in member.aliases()), None)
        if found is None and "/" in key:
            # 别的机器写的 ref（如 new/<id>）在本机换算不出来时，按最后一段再找一次。
            tail = key.rsplit("/", 1)[-1]
            found = next((member for member in self.members if tail in member.aliases()), None)
        return found

    def content_hash(self) -> str:
        return content_hash([[m.ref, m.positive, m.negative] for m in self.members])

    def summary(self, *, include_members: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ref": self.ref,
            "name": self.name,
            "path": str(self.path),
            "kind": "stn" if self.name.startswith("stn_") else "st",
            "member_count": len(self.members),
            "content_hash": self.content_hash(),
        }
        if include_members:
            data["members"] = [member.summary() for member in self.members]
        return data


def _normalize_ref(value: str) -> str:
    text = str(value).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def link_target(path: Path) -> Path | None:
    """符号链接或 Windows 目录联接（junction）指向的路径；不是链接时返回 None。"""
    try:
        target = os.readlink(path)
    except (OSError, ValueError):
        return None
    if target.startswith("\\\\?\\UNC\\"):
        target = "\\\\" + target[8:]
    elif target.startswith("\\\\?\\"):
        target = target[4:]
    return Path(target) if os.path.isabs(target) else Path(os.path.normpath(path.parent / target))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


class ContractSources:
    """按设计库目录读取契约用到的节点。ref 可以是相对角色根目录的路径或绝对路径。"""

    def __init__(self, design_root: str | Path, reader: NodeReader | None = None):
        self.design_root = Path(design_root)
        self.reader = reader or NodeReader()
        self._linked_action_dirs: dict[str, str] | None = None

    # ---- 路径 ----

    def role_root(self, role: str) -> Path:
        return primary_role_root(self.design_root, role)

    @property
    def action_root(self) -> Path:
        return self.role_root("action")

    def resolve(self, role: str, ref: str) -> Path:
        raw = Path(str(ref).strip())
        if raw.is_absolute():
            return raw
        root = self.role_root(role)
        candidate = Path(os.path.normpath(root / raw))
        try:
            candidate.relative_to(Path(os.path.normpath(root)))
        except ValueError as exc:
            raise ValueError(f"{role} ref 必须位于 {role} 根目录内：{ref}") from exc
        return candidate

    def relative_ref(self, role: str, path: str | Path) -> str:
        """存进契约的 ref：能相对角色根目录就写相对路径，否则保留绝对路径。"""
        path = Path(path)
        root = self.role_root(role)
        for base, candidate in ((root, path), (root.resolve(), path.resolve())):
            try:
                return candidate.relative_to(base).as_posix()
            except ValueError:
                continue
        return str(path)

    # ---- 动作组 ----

    def list_action_groups(self, query: str | None = None) -> list[dict[str, Any]]:
        root = self.action_root
        if not root.is_dir():
            return []
        needle = (query or "").strip().lower()
        groups: list[dict[str, Any]] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
            if not entry.is_dir() or not is_action_group_name(entry.name):
                continue
            if needle and needle not in entry.name.lower():
                continue
            members = self._member_entries(entry)
            if not members:
                # 没有动作节点的 st_/stn_ 目录（如只放了 AlbumPlan.yaml 的相册方案）不能当契约来源。
                continue
            groups.append(
                {
                    "ref": entry.name,
                    "name": entry.name,
                    "path": str(entry),
                    "kind": "stn" if entry.name.startswith("stn_") else "st",
                    "member_count": len(members),
                    "first_member": str(members[0]) if members else None,
                }
            )
        return groups

    def load_action_group(self, ref: str) -> ActionGroup:
        path = self.resolve("action", ref)
        if not path.is_dir():
            raise FileNotFoundError(f"动作组不存在：{ref}")
        if not is_action_group_name(path.name):
            raise ValueError(f"动作组必须是 st_* 或 stn_* 目录：{ref}")
        members = [
            self._load_member(entry, index=index, group_dir=path)
            for index, entry in enumerate(self._member_entries(path), start=1)
        ]
        return ActionGroup(ref=self.relative_ref("action", path), path=path, members=members)

    def load_action_node(self, ref: str) -> ActionMember:
        """读取单个动作节点（`inspired_by` 引用的参考动作）。"""
        path = self.resolve("action", ref)
        if not path.is_dir() or not has_node_file(path):
            raise FileNotFoundError(f"动作节点不存在：{ref}")
        return self._load_member(path, index=0, group_dir=None)

    def _member_entries(self, group_dir: Path) -> list[Path]:
        try:
            entries = [item for item in group_dir.iterdir() if item.is_dir() and has_node_file(item)]
        except OSError:
            return []
        return sorted(entries, key=lambda item: _natural_key(item.name))

    def _action_link_dirs(self) -> dict[str, str]:
        """动作根目录下本身是链接的普通目录（如 Windows 上 `new` → G:/GoogleDrive/action）：目标路径 → 目录名。"""
        if self._linked_action_dirs is None:
            self._linked_action_dirs = {}
            try:
                entries = list(self.action_root.iterdir())
            except OSError:
                entries = []
            for entry in entries:
                if is_action_group_name(entry.name):
                    continue
                target = link_target(entry)
                if target is not None:
                    self._linked_action_dirs.setdefault(_path_key(target), entry.name)
        return self._linked_action_dirs

    def canonical_action_ref(self, path: Path) -> str:
        """动作节点的 ref，与机器上用相对符号链接还是绝对链接 / junction 无关。

        Linux：成员 → ../new/<id>，直接得到 new/<id>。
        Windows：成员和 new 都是指向同一个外部目录（如 G:/GoogleDrive/action）的 junction，
        按 new 指向的目录换算回 new/<id>。
        """
        ref = self.relative_ref("action", path)
        if not Path(ref).is_absolute():
            return ref
        name = self._action_link_dirs().get(_path_key(path.parent))
        return f"{name}/{path.name}" if name else ref

    def _load_member(self, entry: Path, *, index: int, group_dir: Path | None) -> ActionMember:
        target = link_target(entry)
        canonical = target or entry
        ref = self.canonical_action_ref(canonical)
        if Path(ref).is_absolute() and group_dir is not None:
            ref = f"{group_dir.name}/{entry.name}"
        node = self.reader.read(entry)
        positive, negative, source_file = action_prompt(node, entry)
        return ActionMember(
            index=index,
            name=canonical.name if group_dir is None else entry.name,
            ref=ref,
            group_ref=f"{group_dir.name}/{entry.name}" if group_dir is not None else None,
            path=entry,
            node=node,
            positive=positive,
            negative=negative,
            source_file=source_file,
            classify=_classify_summary(entry),
            link_name=target.name if target is not None else None,
        )

    # ---- 角色 / 服装 / 背景 ----

    def load_node(self, role: str, ref: str) -> NodeDocument:
        path = self.resolve(role, ref)
        return self.reader.read(path)

    def node_summary(self, role: str, ref: str) -> dict[str, Any]:
        path = self.resolve(role, ref)
        node = self.reader.read(path)
        sections = {key: list(values) for key, values in node.tags.items() if values}
        positive_texts = node.positive_texts()
        if positive_texts and not sections:
            sections["prompt"] = positive_texts
        return {
            "ref": ref,
            "path": str(path),
            "id": node.id,
            "name": node.name or node.id,
            "character_id": node.character_id,
            "variant": node.variant,
            "sections": sections,
            "negative": list(node.negative_prompt) + node.negative_texts(),
            "content_hash": node_content_hash(node),
        }


def action_prompt(node: NodeDocument, node_dir: Path) -> tuple[str, str, str]:
    """动作节点的原始正向 / 负面提示词，以及读取自哪个文件。"""
    yaml_file = next((name for name in ("node.yaml", "meta.yaml") if (node_dir / name).exists()), None)
    negative = ", ".join([*node.negative_prompt, *node.negative_texts()])
    if yaml_file:
        action_tags = node.tags.get("action")
        if action_tags:
            return ", ".join(action_tags), negative, yaml_file
        texts = node.all_tags() + node.positive_texts()
        return ", ".join(texts), negative, yaml_file
    tags_file = "tags.compiled.txt" if (node_dir / "tags.compiled.txt").is_file() else "tags.txt"
    return "\n".join(node.positive_texts()), negative, tags_file


def _classify_summary(node_dir: Path) -> dict[str, Any]:
    path = node_dir / "classify.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in CLASSIFY_SUMMARY_KEYS if data.get(key) not in (None, [], "")}
