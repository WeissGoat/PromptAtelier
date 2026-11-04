"""契约服务：把存储、来源节点、格式 profile、校验器和要求 prompt 组合成 CLI / Web 用的接口。"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from tags_machine_core.verification.image_params import read_png_text_chunks

from .models import CONTRACT_SCHEMA, ContractIssue, ParsedContract, ParsedFrame
from .parser import (
    ContractParseError,
    extract_import_frames,
    parse_contract,
    replace_body,
    replace_frame_prompts,
    set_front_matter_fields,
)
from .profiles import FormatProfile, load_format_profiles
from .prompts import render_standalone_prompt, render_tools_prompt
from .sources import ActionGroup, ActionMember, ContractSources
from .store import ContractConflictError, ContractStore, contract_summary
from .validators import (
    ValidationContext,
    character_tag_keys,
    coverage_report,
    frame_token_usage,
    load_conflict_rules,
    run_validators,
)


DEFAULT_FORMAT = "nai-v4.5"
RESULT_DIR_PREFIX = "contract_"
PICKS_DIR = ".contract_picks"
SKILL_PATH = ".agents/skills/compose-contract-author/SKILL.md"
PNG_INFO_KEY = "tags_machine_core"


def prompt_hash(positive: str, negative: str, characters: list[dict[str, str]] | None = None) -> str:
    """生成时该帧 positive + negative（+ 各角色提示词）的 hash，用来判断图是否用当前版本的提示词出的。

    没有角色块时和只按 positive + negative 算的结果相同，已有的图不会被误标成「提示词已改」。
    """
    payload: list[Any] = [positive.strip(), negative.strip()]
    if characters:
        payload.append([[item["id"], item["positive"].strip(), item["negative"].strip()] for item in characters])
    text = json.dumps(payload, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def frame_character_prompts(frame: ParsedFrame, character_order: list[str], profile: FormatProfile | None = None) -> list[dict[str, str]]:
    """本帧的分角色提示词，按契约角色顺序（c1、c2…）排列；只列有 ```positive cN 的角色。"""
    ids = [block.character for block in frame.blocks if block.character and block.kind == "positive"]
    ordered = [cid for cid in character_order if cid in ids] + [cid for cid in ids if cid not in character_order]
    convert = profile.prompt_for_submit if profile else (lambda text: text)
    result = []
    for cid in dict.fromkeys(ordered):
        positive = frame.block("positive", cid)
        negative = frame.block("negative", cid)
        result.append({
            "id": cid,
            "positive": convert(positive.text if positive else ""),
            "negative": convert(negative.text if negative else ""),
        })
    return result


class ContractService:
    def __init__(
        self,
        *,
        root: str | Path,
        design_root: str | Path,
        output_dir: str | Path | None = None,
        formats_dir: str | Path | None = None,
        cli: str = "uv run tm-core",
        config_path: str | Path | None = None,
        project_root: str | Path | None = None,
    ):
        self.store = ContractStore(root)
        self.sources = ContractSources(design_root)
        self.design_root = Path(design_root)
        self.output_dir = Path(output_dir) if output_dir else None
        self.profiles = load_format_profiles(formats_dir)
        self.cli = cli
        self.config_arg = f" --config {config_path}" if config_path else ""
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.conflict_rules = load_conflict_rules(design_root)
        self._png_cache: dict[tuple[str, int, int], dict | None] = {}
        self._png_lock = threading.Lock()

    # ---- 列表 ----

    def formats(self) -> list[dict[str, Any]]:
        return [profile.summary() for profile in self.profiles.values()]

    def profile(self, format_id: str) -> FormatProfile | None:
        return self.profiles.get(format_id)

    def list(self, *, node: str | None = None, status: str | None = None, target_format: str | None = None) -> list[dict]:
        items = self.store.summaries()
        if status:
            items = [item for item in items if item.get("status") == status]
        if target_format:
            items = [item for item in items if item.get("target_format") == target_format]
        if node:
            needles = {node.strip()}
            for role in ("character", "action", "clothing", "background"):
                try:
                    needles.add(self.sources.relative_ref(role, Path(node.strip())))
                except (OSError, ValueError):
                    continue
            items = [item for item in items if needles & _node_refs(item)]
        return items

    def action_groups(self, query: str | None = None) -> list[dict[str, Any]]:
        return self.sources.list_action_groups(query)

    def action_group(self, ref: str) -> dict[str, Any]:
        return self.sources.load_action_group(ref).summary()

    # ---- 创建 ----

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        group_ref = str(payload.get("action_group") or "").strip()
        if not group_ref:
            raise ValueError("新建契约需要选择一个动作组（st_* / stn_*）")
        group = self.sources.load_action_group(group_ref)
        if not group.members:
            raise ValueError(f"动作组 {group.name} 里没有动作节点（子目录里要有 meta.yaml / node.yaml / tags.txt）")
        character_refs = [str(ref).strip() for ref in payload.get("characters") or [] if str(ref).strip()]
        if not character_refs:
            raise ValueError("新建契约至少需要一个角色")
        target_format = str(payload.get("target_format") or DEFAULT_FORMAT)
        if self.profiles and target_format not in self.profiles:
            raise ValueError(f"未知的目标格式：{target_format}")

        characters: dict[str, dict[str, str]] = {}
        for index, ref in enumerate(character_refs, start=1):
            summary = self.sources.node_summary("character", ref)
            characters[f"c{index}"] = {
                "ref": self.sources.relative_ref("character", self.sources.resolve("character", ref)),
                "content_hash": summary["content_hash"],
            }
        optional: dict[str, dict[str, str] | None] = {}
        for role in ("clothing", "background"):
            ref = str(payload.get(role) or "").strip()
            if ref:
                summary = self.sources.node_summary(role, ref)
                optional[role] = {
                    "ref": self.sources.relative_ref(role, self.sources.resolve(role, ref)),
                    "content_hash": summary["content_hash"],
                }
            else:
                optional[role] = None
        options = payload.get("options") or {}
        now = datetime.now().astimezone()
        contract_id = self.store.unique_id(f"{now:%Y%m%d-%H%M}_{group.name}")
        text = render_new_contract(
            contract_id=contract_id,
            created_at=now.isoformat(timespec="seconds"),
            target_format=target_format,
            characters=characters,
            action_group={"ref": group.ref, "content_hash": group.content_hash()},
            clothing=optional["clothing"],
            background=optional["background"],
            requirements=str(payload.get("requirements") or ""),
            options={
                "keep_order": bool(options.get("keep_order", True)),
                "allow_new_frames": bool(options.get("allow_new_frames", True)),
                "max_new_frames": int(options.get("max_new_frames", 2)),
            },
        )
        parse_contract(text)  # 自检：写出去的文件必须能读回来
        self.store.write(contract_id, text, create=True)
        return self.detail(contract_id)

    # ---- 读取 ----

    def detail(self, contract_id: str) -> dict[str, Any]:
        file = self.store.read(contract_id)
        file_info = {"path": str(file.path), "hash": file.hash, "mtime": file.mtime}
        try:
            contract = parse_contract(file.text)
        except (ContractParseError, ValueError) as exc:
            return {
                "schema": "tags-machine-core.web.compose-contract/v1",
                "id": contract_id,
                "file": file_info,
                "parse_error": str(exc),
                "text": file.text,
            }
        loaded = self._load_sources(contract)
        profile = self.profiles.get(contract.request.target_format)
        issues = list(loaded["issues"])
        if profile is None:
            issues.append(ContractIssue(validator="profile", severity="warn", message=f"没有格式 profile：{contract.request.target_format}，只做结构校验"))
            profile = FormatProfile(id=contract.request.target_format, validators=["frame_structure", "source_exists", "coverage"])
        ctx = ValidationContext(
            contract=contract,
            action_group=loaded["group"],
            character_ids=list(contract.request.nodes.characters),
            references=loaded["reference_members"],
            conflict_rules=self.conflict_rules,
            character_tags=character_tag_keys(loaded["payload"]["characters"]),
        )
        issues.extend(run_validators(profile, ctx))
        group: ActionGroup | None = loaded["group"]
        coverage = None
        if group is not None:
            report = coverage_report(contract, group)
            coverage = {
                "total": report["total"],
                "used": report["used"],
                "missing": report["missing"],
                "custom_frames": report["custom_frames"],
            }
        return {
            "schema": "tags-machine-core.web.compose-contract/v1",
            "id": contract_id,
            "file": file_info,
            "summary": contract_summary(contract_id, contract, file.mtime),
            "request": contract.request.model_dump(mode="json", by_alias=True),
            "preamble": contract.preamble,
            "frames": [
                self._frame_payload(frame, group, profile, list(contract.request.nodes.characters))
                for frame in contract.frames
            ],
            "sources": loaded["payload"],
            "stale": loaded["stale"],
            "coverage": coverage,
            "issues": [issue.to_dict() for issue in issues],
            "issue_counts": _issue_counts(issues),
            "profile": profile.summary(),
        }

    def _frame_payload(
        self,
        frame: ParsedFrame,
        group: ActionGroup | None,
        profile: FormatProfile,
        character_order: list[str],
    ) -> dict[str, Any]:
        member = group.find_member(frame.source) if group is not None and not frame.is_custom else None
        prompts = frame.prompts()
        submit = {key: profile.prompt_for_submit(value) for key, value in prompts.items()}
        character_prompts = frame_character_prompts(frame, character_order, profile)
        return {
            "id": frame.id,
            "title": frame.title,
            "source": frame.source,
            "is_custom": frame.is_custom,
            "inspired_by": frame.inspired_by,
            "characters": frame.characters,
            "size": frame.size,
            "meta": frame.meta,
            "notes": frame.notes,
            "prompts": prompts,
            "submit": submit,
            # 提交生图用的分角色提示词（已按 profile 处理换行），按 c1、c2… 排列。
            "character_prompts": character_prompts,
            "member_ref": member.ref if member else None,
            "member_index": member.index if member else None,
            "prompt_hash": prompt_hash(
                frame.positive,
                frame.negative,
                frame_character_prompts(frame, character_order),
            ),
            "token_usage": frame_token_usage(frame, profile),
        }

    def _load_sources(self, contract: ParsedContract) -> dict[str, Any]:
        nodes = contract.request.nodes
        issues: list[ContractIssue] = []
        stale: list[dict[str, str]] = []
        payload: dict[str, Any] = {"characters": {}, "action_group": None, "clothing": None, "background": None, "references": {}}

        for key, entry in nodes.characters.items():
            try:
                summary = self.sources.node_summary("character", entry.ref)
            except (FileNotFoundError, ValueError) as exc:
                issues.append(ContractIssue(validator="source_exists", severity="error", message=f"角色 {key} 读取失败：{exc}"))
                continue
            payload["characters"][key] = summary
            if entry.content_hash and entry.content_hash != summary["content_hash"]:
                stale.append({"node": f"characters.{key}", "ref": entry.ref})
        group: ActionGroup | None = None
        if nodes.action_group:
            try:
                group = self.sources.load_action_group(nodes.action_group.ref)
                payload["action_group"] = group.summary()
                if nodes.action_group.content_hash and nodes.action_group.content_hash != group.content_hash():
                    stale.append({"node": "action_group", "ref": nodes.action_group.ref})
            except (FileNotFoundError, ValueError) as exc:
                issues.append(ContractIssue(validator="source_exists", severity="error", message=f"动作组读取失败：{exc}"))
        for role in ("clothing", "background"):
            entry = getattr(nodes, role)
            if not entry:
                continue
            try:
                summary = self.sources.node_summary(role, entry.ref)
            except (FileNotFoundError, ValueError) as exc:
                issues.append(ContractIssue(validator="source_exists", severity="error", message=f"{role} 读取失败：{exc}"))
                continue
            payload[role] = summary
            if entry.content_hash and entry.content_hash != summary["content_hash"]:
                stale.append({"node": role, "ref": entry.ref})

        reference_members: dict[str, ActionMember | None] = {}
        for frame in contract.frames:
            for ref in frame.inspired_by:
                if ref in reference_members:
                    continue
                try:
                    member = self.sources.load_action_node(ref)
                except (FileNotFoundError, ValueError):
                    member = None
                reference_members[ref] = member
                if member is not None:
                    payload["references"][ref] = member.summary()
        return {"payload": payload, "group": group, "issues": issues, "stale": stale, "reference_members": reference_members}

    def check(self, contract_id: str) -> dict[str, Any]:
        detail = self.detail(contract_id)
        if "parse_error" in detail:
            return {"id": contract_id, "ok": False, "issues": [{"validator": "frame_structure", "severity": "error", "message": detail["parse_error"]}]}
        return {
            "id": contract_id,
            "ok": detail["issue_counts"]["error"] == 0,
            "status": detail["request"]["status"],
            "frame_count": len(detail["frames"]),
            "issue_counts": detail["issue_counts"],
            "coverage": _compact_coverage(detail.get("coverage")),
            "stale": detail["stale"],
            "tokens": _compact_tokens(detail["frames"]),
            "issues": detail["issues"],
        }

    def show(self, contract_id: str) -> dict[str, Any]:
        detail = self.detail(contract_id)
        if "parse_error" in detail:
            return detail
        return {
            "id": contract_id,
            "path": detail["file"]["path"],
            "request": detail["request"],
            "format": detail["profile"],
            "frames": [
                {key: frame[key] for key in ("id", "title", "source", "inspired_by", "characters", "size", "prompts", "notes")}
                for frame in detail["frames"]
            ],
            "issue_counts": detail["issue_counts"],
        }

    def context(self, contract_id: str, *, member: int | None = None) -> dict[str, Any]:
        detail = self.detail(contract_id)
        if "parse_error" in detail:
            raise ValueError(detail["parse_error"])
        sources = detail["sources"]
        group = sources.get("action_group")
        if group and member is not None:
            members = [item for item in group["members"] if item["index"] == member]
            if not members:
                raise ValueError(f"动作组没有第 {member} 个成员（共 {group['member_count']} 个）")
            group = {**group, "members": members}
        if group:
            group = {**group, "members": [_member_for_agent(item) for item in group["members"]]}
        return {
            "id": contract_id,
            "target_format": detail["request"]["target_format"],
            "requirements": detail["request"]["requirements"],
            "options": detail["request"]["options"],
            "characters": sources["characters"],
            "action_group": group,
            "clothing": sources.get("clothing"),
            "background": sources.get("background"),
        }

    def prompt(self, contract_id: str, kind: str) -> dict[str, Any]:
        detail = self.detail(contract_id)
        if "parse_error" in detail:
            raise ValueError(detail["parse_error"])
        profile = self.profiles.get(detail["request"]["target_format"])
        if kind == "standalone":
            text = render_standalone_prompt(detail, profile)
        elif kind == "tools":
            text = render_tools_prompt(
                detail,
                profile,
                contract_path=detail["file"]["path"],
                cli=self.cli,
                config_arg=self.config_arg,
                skill_path=str(self.project_root / SKILL_PATH),
                project_root=str(self.project_root),
            )
        else:
            raise ValueError("kind 只能是 tools 或 standalone")
        return {"id": contract_id, "kind": kind, "text": text}

    # ---- 写回 ----

    def import_frames(self, contract_id: str, raw: str, *, expected_hash: str | None = None) -> dict[str, Any]:
        file = self.store.read(contract_id)
        body, extra = extract_import_frames(raw)
        parse_contract(f"---\nid: probe\n---\n\n{body}\n")
        text = replace_body(file.text, body)
        fields: dict[str, str] = {"status": "done"}
        contract = parse_contract(file.text)
        for key in ("title", "author"):
            if extra.get(key) and not getattr(contract.request, key):
                fields[key] = extra[key]
        text = set_front_matter_fields(text, fields)
        self.store.write(contract_id, text, expected_hash=expected_hash or file.hash)
        return self.detail(contract_id)

    def save_frame(self, contract_id: str, frame_id: str, prompts: dict[str, str], *, expected_hash: str) -> dict[str, Any]:
        file = self.store.read(contract_id)
        if file.hash != expected_hash:
            raise ContractConflictError(contract_id, file.hash)
        text = replace_frame_prompts(file.text, frame_id, prompts)
        self.store.write(contract_id, text, expected_hash=expected_hash)
        return self.detail(contract_id)

    def set_fields(self, contract_id: str, fields: dict[str, str], *, expected_hash: str | None = None) -> dict[str, Any]:
        allowed = {"status", "title", "author"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"只能修改 {', '.join(sorted(allowed))}")
        if "status" in fields and fields["status"] not in {"pending", "done"}:
            raise ValueError("status 只能是 pending 或 done")
        file = self.store.read(contract_id)
        text = set_front_matter_fields(file.text, fields)
        self.store.write(contract_id, text, expected_hash=expected_hash or file.hash)
        return self.detail(contract_id)

    # ---- 出图结果与采用 ----

    def results(self, contract_id: str) -> dict[str, Any]:
        detail = self.detail(contract_id)
        current = {frame["id"]: frame["prompt_hash"] for frame in detail.get("frames", [])}
        picks = self.picks(contract_id)
        frames: dict[str, list[dict[str, Any]]] = {}
        for image in self._contract_images(contract_id):
            frame_id = image["frame_id"]
            image["current"] = current.get(frame_id) == image.get("prompt_hash")
            image["picked"] = image["path"] in picks.get(frame_id, [])
            frames.setdefault(frame_id, []).append(image)
        for images in frames.values():
            images.sort(key=lambda item: item["created_at"], reverse=True)
        return {"id": contract_id, "frames": frames, "picks": picks}

    def _result_roots(self) -> list[Path]:
        if self.output_dir is None:
            return []
        return [self.output_dir, self.output_dir / "compares"]

    def _contract_images(self, contract_id: str) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for root in self._result_roots():
            if not root.is_dir():
                continue
            for run in root.iterdir():
                if not run.is_dir() or not run.name.startswith(RESULT_DIR_PREFIX):
                    continue
                for path in sorted(run.rglob("*.png")):
                    info = self._png_contract_info(path)
                    if not info or info.get("id") != contract_id or not info.get("frame_id"):
                        continue
                    stat = path.stat()
                    images.append(
                        {
                            "path": str(path.resolve()),
                            "run": run.name,
                            "frame_id": str(info["frame_id"]),
                            "prompt_hash": info.get("prompt_hash"),
                            "artist": info.get("artist"),
                            "seed": info.get("seed"),
                            "created_at": stat.st_mtime,
                        }
                    )
        return images

    def _png_contract_info(self, path: Path) -> dict | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._png_lock:
            if key in self._png_cache:
                return self._png_cache[key]
        info: dict | None = None
        try:
            chunks = read_png_text_chunks(path)
            core = json.loads(chunks.get(PNG_INFO_KEY) or "{}")
            contract = core.get("contract") if isinstance(core, dict) else None
            if isinstance(contract, dict):
                info = dict(contract)
                seed = _png_seed(chunks)
                if seed is not None:
                    info.setdefault("seed", seed)
        except (OSError, ValueError):
            info = None
        with self._png_lock:
            self._png_cache[key] = info
        return info

    def _picks_path(self, contract_id: str) -> Path:
        if self.output_dir is None:
            raise ValueError("没有配置出图目录，无法记录采用")
        self.store.path_for(contract_id)  # 校验 id
        return self.output_dir / PICKS_DIR / f"{contract_id}.json"

    def picks(self, contract_id: str) -> dict[str, list[str]]:
        try:
            path = self._picks_path(contract_id)
        except ValueError:
            return {}
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): [str(p) for p in v] for k, v in data.items() if isinstance(v, list)}

    def update_picks(self, contract_id: str, frame_id: str, *, add: list[str] = (), remove: list[str] = ()) -> dict[str, list[str]]:
        self.store.read(contract_id)
        path = self._picks_path(contract_id)
        picks = self.picks(contract_id)
        current = [item for item in picks.get(frame_id, []) if item not in set(remove)]
        for item in add:
            if item not in current:
                current.append(item)
        if current:
            picks[frame_id] = current
        else:
            picks.pop(frame_id, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8")
        return picks


def render_new_contract(
    *,
    contract_id: str,
    created_at: str,
    target_format: str,
    characters: dict[str, dict[str, str]],
    action_group: dict[str, str],
    clothing: dict[str, str] | None,
    background: dict[str, str] | None,
    requirements: str,
    options: dict[str, Any],
) -> str:
    def entry(value: dict[str, str] | None) -> str:
        if not value:
            return "null"
        return "{ ref: %s, content_hash: %s }" % (_q(value["ref"]), _q(value.get("content_hash") or ""))

    lines = [
        "---",
        f"schema: {CONTRACT_SCHEMA}",
        f"id: {contract_id}",
        'title: ""                          # Agent 选填：简短中文标题',
        "status: pending                    # Agent 写完并自检通过后改为 done",
        f"created_at: {_q(created_at)}",
        f"target_format: {target_format}",
        "nodes:",
        "  characters:",
        *[f"    {key}: {entry(value)}" for key, value in characters.items()],
        f"  action_group: {entry(action_group)}",
        f"  clothing: {entry(clothing)}",
        f"  background: {entry(background)}",
    ]
    text = requirements.replace("\r\n", "\n").strip()
    if not text:
        lines.append('requirements: ""')
    elif text[0].isspace():
        lines.append(f"requirements: {_q(text)}")
    else:
        lines.append("requirements: |")
        lines.extend(f"  {line}" if line.strip() else "" for line in text.split("\n"))
    lines.extend(
        [
            "options: { keep_order: %s, allow_new_frames: %s, max_new_frames: %d }"
            % (_b(options["keep_order"]), _b(options["allow_new_frames"]), options["max_new_frames"]),
            'author: ""                         # Agent 选填',
            "---",
            "",
            "<!-- 在下面按帧书写：每帧以「## f01 标题」开头，格式见 compose-contract-author Skill。 -->",
            "",
        ]
    )
    return "\n".join(lines)


def _q(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _b(value: bool) -> str:
    return "true" if value else "false"


def _compact_tokens(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """每帧正向 token 用量，供 Agent 自检：{"limit", "exact", "frames": {"F01": 123, ...}}。"""
    usages = [(frame["id"], frame.get("token_usage")) for frame in frames]
    usages = [(frame_id, usage) for frame_id, usage in usages if usage]
    if not usages:
        return None
    first = usages[0][1]
    return {
        "tokenizer": first["tokenizer"],
        "limit": first["limit"],
        "shared_with_characters": first["shared"],
        "exact": all(usage["exact"] for _, usage in usages),
        "frames": {frame_id: usage["total"] for frame_id, usage in usages},
    }


def _issue_counts(issues: list[ContractIssue]) -> dict[str, int]:
    counts = {"error": 0, "warn": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] += 1
    return counts


def _compact_coverage(coverage: dict | None) -> dict | None:
    if not coverage:
        return None
    return {
        "total": coverage["total"],
        "used": len(coverage["used"]),
        "missing": [f"#{m['index']} {m['title']}" for m in coverage["missing"]],
        "custom_frames": coverage["custom_frames"],
    }


def _member_for_agent(member: dict[str, Any]) -> dict[str, Any]:
    return {
        key: member[key]
        for key in ("index", "title", "ref", "positive", "negative", "source_file", "classify", "character_scope", "clothing_state")
        if member.get(key) not in (None, "", {}, [])
    }


def _node_refs(summary: dict) -> set[str]:
    nodes = summary.get("nodes") or {}
    refs = set((nodes.get("characters") or {}).values())
    for key in ("action_group", "clothing", "background"):
        if nodes.get(key):
            refs.add(nodes[key])
    return refs


def _png_seed(chunks: dict[str, str]) -> int | None:
    comment = chunks.get("Comment")
    if comment:
        try:
            seed = json.loads(comment).get("seed")
            return int(seed) if seed is not None else None
        except (ValueError, TypeError, AttributeError):
            return None
    return None
