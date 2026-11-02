"""契约校验器（§7）。每个校验器只读解析结果和来源节点，返回问题列表；结果不写进契约文件。

新增校验器：实现 `validate_frame` 和/或 `validate_contract`，用 `@register` 注册，
再在格式 profile 的 `validators` 里列出它的 id。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tags_machine_core.policies.rules.tag_conflict import DEFAULT_CONFLICTS, _load_legacy_masks
from tags_machine_core.policies.tokens import canonicalize_tag

from .models import (
    CUSTOM_SOURCE,
    SIZE_CHOICES,
    ContractIssue,
    ParsedContract,
    ParsedFrame,
    PromptBlock,
)
from .parser import FRAME_ID_RE
from .profiles import FormatProfile
from .sources import ActionGroup, ActionMember
from .tokens import tokenize_prompt


QUALITY_TAGS = frozenset(
    canonicalize_tag(tag)
    for tag in (
        "masterpiece", "best quality", "high quality", "good quality", "normal quality",
        "amazing quality", "very aesthetic", "aesthetic", "absurdres", "highres", "ultra-detailed",
        "very awa", "newest", "year 2024", "year 2025", "score_9", "score_8_up", "score_7_up",
        "location", "no text",
    )
)
ARTIST_PREFIX_RE = re.compile(r"^artist\s*:", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]")
COUNT_TAG_RE = re.compile(r"^(\d+|6\+)(girl|boy|other)s?$")
CAST_RE = re.compile(r"(\d+)(girl|boy|other)s?")


@dataclass
class ValidationContext:
    contract: ParsedContract
    action_group: ActionGroup | None = None
    character_ids: list[str] = field(default_factory=list)
    references: dict[str, ActionMember | None] = field(default_factory=dict)
    conflict_rules: list[dict[str, list[str]]] = field(default_factory=lambda: list(DEFAULT_CONFLICTS))

    def member_for(self, frame: ParsedFrame) -> ActionMember | None:
        if self.action_group is None or frame.is_custom:
            return None
        return self.action_group.find_member(frame.source)


class ContractValidator(Protocol):
    id: str

    def validate_frame(self, frame: ParsedFrame, profile: FormatProfile, ctx: ValidationContext) -> list[ContractIssue]: ...

    def validate_contract(self, profile: FormatProfile, ctx: ValidationContext) -> list[ContractIssue]: ...


REGISTRY: dict[str, ContractValidator] = {}


def register(cls: type) -> type:
    instance = cls()
    REGISTRY[instance.id] = instance
    return cls


class _Base:
    id = ""

    def validate_frame(self, frame, profile, ctx) -> list[ContractIssue]:
        return []

    def validate_contract(self, profile, ctx) -> list[ContractIssue]:
        return []

    def issue(self, severity, message, frame: ParsedFrame | None = None, **extra) -> ContractIssue:
        return ContractIssue(
            validator=self.id,
            severity=severity,
            message=message,
            frame_id=frame.id if frame else None,
            **extra,
        )


def run_validators(profile: FormatProfile, ctx: ValidationContext) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    ids = profile.validators or list(REGISTRY)
    for error in ctx.contract.parse_errors:
        issues.append(ContractIssue(validator="frame_structure", severity="error", message=error))
    for validator_id in ids:
        validator = REGISTRY.get(validator_id)
        if validator is None:
            issues.append(ContractIssue(validator=validator_id, severity="info", message=f"未知校验器 {validator_id}，已跳过"))
            continue
        issues.extend(validator.validate_contract(profile, ctx))
        for frame in ctx.contract.frames:
            issues.extend(validator.validate_frame(frame, profile, ctx))
    order = {"error": 0, "warn": 1, "info": 2}
    frame_order = {frame.id: index for index, frame in enumerate(ctx.contract.frames)}
    issues.sort(key=lambda item: (frame_order.get(item.frame_id or "", -1), order[item.severity]))
    return issues


def prompt_blocks(frame: ParsedFrame, kind: str | None = "positive") -> list[PromptBlock]:
    return [block for block in frame.blocks if kind is None or block.kind == kind]


@register
class FrameStructure(_Base):
    id = "frame_structure"

    def validate_contract(self, profile, ctx):
        issues = []
        if not ctx.contract.frames:
            if ctx.contract.request.status == "done":
                issues.append(self.issue("error", "契约标记为 done，但没有任何帧"))
            return issues
        counts = Counter(frame.id for frame in ctx.contract.frames)
        for frame_id, count in counts.items():
            if count > 1:
                issues.append(self.issue("error", f"帧 id {frame_id} 重复 {count} 次；帧 id 用于回挂出图结果，必须唯一"))
        return issues

    def validate_frame(self, frame, profile, ctx):
        issues = [self.issue("error", error, frame) for error in frame.parse_errors]
        if not FRAME_ID_RE.match(frame.id):
            issues.append(self.issue("error", f"帧 id「{frame.id}」只能用字母、数字、下划线、点和连字符", frame))
        if not frame.source:
            issues.append(self.issue("error", "缺少 source:（动作 ref，或 custom）", frame, fix_hint="在帧标题下一行写 source: <动作 ref>"))
        if not frame.positive.strip():
            issues.append(self.issue("error", "缺少 ```positive 代码块或内容为空", frame))
        if frame.size and frame.size not in SIZE_CHOICES:
            issues.append(self.issue("error", f"size 只能是 {' / '.join(SIZE_CHOICES)}，现在是 {frame.size}", frame))
        declared = set(ctx.character_ids)
        for character in frame.characters:
            if declared and character not in declared:
                issues.append(self.issue("error", f"characters 中的 {character} 不在契约的角色列表（{', '.join(sorted(declared))}）里", frame))
        for block in frame.blocks:
            if block.character:
                if not profile.multi_character.supported:
                    issues.append(self.issue("error", f"格式 {profile.id} 不支持分角色提示词（```{block.key}）", frame, block=block.key))
                elif declared and block.character not in declared:
                    issues.append(self.issue("error", f"```{block.key} 的角色 {block.character} 不在契约的角色列表里", frame, block=block.key))
        seen = Counter(block.key for block in frame.blocks)
        for key, count in seen.items():
            if count > 1:
                issues.append(self.issue("error", f"```{key} 代码块重复 {count} 次", frame, block=key))
        return issues


@register
class WeightSyntax(_Base):
    id = "weight_syntax"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        allowed = set(profile.weight.syntaxes)
        low, high = profile.weight.range
        for block in frame.blocks:
            reported: set[str] = set()
            for tag in tokenize_prompt(block.text, profile.separator):
                for syntax in tag.syntaxes - allowed:
                    if syntax in reported:
                        continue
                    reported.add(syntax)
                    issues.append(self.issue(
                        "error",
                        f"格式 {profile.id} 不支持 {_SYNTAX_LABEL[syntax]} 权重写法（如「{tag.raw}」）",
                        frame, block=block.key, tag=tag.raw,
                        fix_hint=f"改用 {', '.join(_SYNTAX_LABEL[s] for s in profile.weight.syntaxes)}",
                    ))
                if "numeric" in tag.syntaxes and "numeric" in allowed:
                    match = re.match(r"^(-?\d+(?:\.\d+)?)::", tag.raw)
                    if match and not (low <= float(match.group(1)) <= high):
                        issues.append(self.issue("warn", f"权重 {match.group(1)} 超出 {low}~{high}", frame, block=block.key, tag=tag.raw))
                if "paren" in tag.syntaxes and "paren" in allowed:
                    match = re.search(r":\s*(-?\d+(?:\.\d+)?)\)$", tag.raw)
                    if match and not (low <= float(match.group(1)) <= high):
                        issues.append(self.issue("warn", f"权重 {match.group(1)} 超出 {low}~{high}", frame, block=block.key, tag=tag.raw))
        return issues


_SYNTAX_LABEL = {"brace": "{tag}/[tag]", "numeric": "1.2::tag::", "paren": "(tag:1.2)"}


@register
class BracketBalance(_Base):
    id = "bracket_balance"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        for block in frame.blocks:
            text = re.sub(r"\\[()\[\]{}]", "", block.text)
            for open_char, close_char in (("{", "}"), ("[", "]"), ("(", ")")):
                depth = 0
                broken = False
                for char in text:
                    if char == open_char:
                        depth += 1
                    elif char == close_char:
                        depth -= 1
                        if depth < 0:
                            broken = True
                            break
                if broken or depth != 0:
                    issues.append(self.issue("error", f"{open_char}{close_char} 括号没有配平", frame, block=block.key))
            if "numeric" in profile.weight.syntaxes and text.count("::") % 2:
                issues.append(self.issue("error", "数值权重 :: 没有配平（每个 1.2:: 需要一个结尾 ::）", frame, block=block.key))
        return issues


def estimate_tokens(text: str, tokenizer: str) -> int:
    """没有真实分词器时的估算：英文词按 ~4 字符一个 token，标点各 1 个；CJK 每字 1~2 个。"""
    count = 0
    for word in re.findall(r"[A-Za-z0-9']+|[^\sA-Za-z0-9']", text):
        if word[0].isalnum() or word[0] == "'":
            count += max(1, math.ceil(len(word) / (4 if tokenizer == "t5" else 5)))
        elif CJK_RE.match(word):
            count += 2
        else:
            count += 1
    return count


@register
class TokenLength(_Base):
    id = "token_length"

    def validate_frame(self, frame, profile, ctx):
        limit = profile.length.max_tokens
        if not limit:
            return []
        issues = []
        for block in prompt_blocks(frame, "positive"):
            submitted = profile.prompt_for_submit(block.text)
            tokens = estimate_tokens(submitted, profile.length.tokenizer)
            if tokens > limit:
                issues.append(self.issue(
                    "warn",
                    f"约 {tokens} token（估算），超过 {profile.id} 的上限 {limit}；超出部分可能被截断",
                    frame, block=block.key,
                ))
        return issues


@register
class Language(_Base):
    id = "language"

    def validate_frame(self, frame, profile, ctx):
        if profile.language.allow_cjk:
            return []
        issues = []
        for block in frame.blocks:
            for tag in tokenize_prompt(block.text, profile.separator):
                if CJK_RE.search(tag.raw):
                    issues.append(self.issue("error", f"格式 {profile.id} 不支持中文/日文：「{tag.raw}」", frame, block=block.key, tag=tag.raw))
        return issues


@register
class ForbiddenTags(_Base):
    id = "forbidden_tags"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        for block in prompt_blocks(frame, "positive"):
            for tag in tokenize_prompt(block.text, profile.separator):
                if profile.forbid.artist_tags and ARTIST_PREFIX_RE.match(tag.body):
                    issues.append(self.issue("error", f"不要写画师：「{tag.raw}」，画风由生图时选的画风节点叠加", frame, block=block.key, tag=tag.raw))
                elif profile.forbid.quality_tags not in (False, "allow") and tag.key in QUALITY_TAGS:
                    issues.append(self.issue("warn", f"质量词「{tag.raw}」由画风 / renderer 叠加，契约里不用写", frame, block=block.key, tag=tag.raw))
        return issues


@register
class DuplicateTags(_Base):
    id = "duplicate_tags"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        for block in frame.blocks:
            counts = Counter(tag.key for tag in tokenize_prompt(block.text, profile.separator) if tag.key)
            for key, count in counts.items():
                if count > 1:
                    issues.append(self.issue("warn", f"「{key}」出现了 {count} 次", frame, block=block.key, tag=key))
        return issues


@register
class TagConflict(_Base):
    id = "tag_conflict"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        for block in prompt_blocks(frame, "positive"):
            keys = {tag.key for tag in tokenize_prompt(block.text, profile.separator)}
            reported: set[str] = set()
            for rule in ctx.conflict_rules:
                trigger = next((key for key in (canonicalize_tag(v) for v in rule.get("when_any", [])) if key in keys), None)
                if not trigger:
                    continue
                keep = {canonicalize_tag(v) for v in rule.get("keep", [])}
                for removed in (canonicalize_tag(v) for v in rule.get("remove", [])):
                    if removed in keys and removed not in keep and removed not in reported:
                        reported.add(removed)
                        issues.append(self.issue("warn", f"「{trigger}」与「{removed}」冲突", frame, block=block.key, tag=removed))
        return issues


@register
class CharacterCount(_Base):
    id = "character_count"

    def validate_frame(self, frame, profile, ctx):
        positive = frame.positive
        if not positive:
            return []
        counts: Counter[str] = Counter()
        for tag in tokenize_prompt(positive, profile.separator):
            match = COUNT_TAG_RE.match(tag.key)
            if match:
                number = 6 if match.group(1) == "6+" else int(match.group(1))
                counts[match.group(2)] += number
        issues = []
        total = sum(counts.values())
        declared = len(frame.characters)
        if declared and total and total < declared:
            issues.append(self.issue("warn", f"characters 声明了 {declared} 个角色，但人数 tag 只有 {total} 人", frame))
        member = ctx.member_for(frame)
        cast = str((member.classify.get("cast") if member else "") or "")
        expected: Counter[str] = Counter()
        for number, kind in CAST_RE.findall(cast):
            expected[kind] += int(number)
        if expected and counts and expected != counts:
            issues.append(self.issue(
                "info",
                f"人数 tag（{_format_counts(counts)}）和来源动作的 cast（{cast}）不一致；确认是有意调整",
                frame,
            ))
        return issues


def _format_counts(counts: Counter[str]) -> str:
    return " ".join(f"{n}{kind}" for kind, n in sorted(counts.items()))


@register
class SourceExists(_Base):
    id = "source_exists"

    def validate_frame(self, frame, profile, ctx):
        issues = []
        if frame.source and not frame.is_custom and ctx.action_group is not None:
            if ctx.action_group.find_member(frame.source) is None:
                issues.append(self.issue(
                    "error",
                    f"source「{frame.source}」不是动作组 {ctx.action_group.name} 的成员",
                    frame,
                    fix_hint="写成员 ref（contract context 输出里的 ref），自定义帧写 source: custom",
                ))
        if frame.inspired_by and not frame.is_custom:
            issues.append(self.issue("info", "inspired_by 只对 source: custom 的帧有意义", frame))
        for ref in frame.inspired_by:
            if ctx.references.get(ref) is None:
                issues.append(self.issue("warn", f"inspired_by 中的「{ref}」找不到对应的动作节点", frame, tag=ref))
        return issues


@register
class Coverage(_Base):
    id = "coverage"

    def validate_contract(self, profile, ctx):
        group = ctx.action_group
        if group is None or not ctx.contract.frames:
            return []
        report = coverage_report(ctx.contract, group)
        issues = []
        for member in report["missing"]:
            issues.append(self.issue("warn", f"动作组成员 #{member['index']} {member['title']} 没有被任何帧使用"))
        options = ctx.contract.request.options
        custom = report["custom_frames"]
        if custom and not options.allow_new_frames:
            issues.append(self.issue("warn", f"契约不允许新增帧，但有 {len(custom)} 个 custom 帧"))
        elif len(custom) > options.max_new_frames:
            issues.append(self.issue("warn", f"新增了 {len(custom)} 帧，超过 max_new_frames={options.max_new_frames}"))
        if options.keep_order:
            indexes = [index for index in report["frame_member_index"] if index is not None]
            if indexes != sorted(indexes):
                issues.append(self.issue("info", "帧顺序和动作组成员顺序不一致（keep_order: true）"))
        return issues


def coverage_report(contract: ParsedContract, group: ActionGroup) -> dict[str, object]:
    used: dict[str, list[str]] = {}
    frame_member_index: list[int | None] = []
    custom_frames: list[str] = []
    for frame in contract.frames:
        if frame.is_custom:
            custom_frames.append(frame.id)
            frame_member_index.append(None)
            continue
        member = group.find_member(frame.source)
        frame_member_index.append(member.index if member else None)
        if member:
            used.setdefault(member.ref, []).append(frame.id)
    missing = [
        {"index": m.index, "ref": m.ref, "title": m.title}
        for m in group.members
        if m.ref not in used
    ]
    return {
        "total": len(group.members),
        "used": used,
        "missing": missing,
        "custom_frames": custom_frames,
        "frame_member_index": frame_member_index,
    }


def load_conflict_rules(design_root: str | Path | None) -> list[dict[str, list[str]]]:
    rules = list(DEFAULT_CONFLICTS)
    if design_root:
        masks = Path(design_root) / "masks.txt"
        if masks.is_file():
            try:
                rules.extend(_load_legacy_masks(masks))
            except (OSError, ValueError):
                pass
    return rules


