"""契约校验器（§7）。每个校验器只读解析结果和来源节点，返回问题列表；结果不写进契约文件。

新增校验器：实现 `validate_frame` 和/或 `validate_contract`，用 `@register` 注册，
再在格式 profile 的 `validators` 里列出它的 id。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tags_machine_core.policies.rules.tag_conflict import DEFAULT_CONFLICTS, _load_legacy_masks
from tags_machine_core.policies.tokens import canonicalize_tag
from tags_machine_core.prompt_tokens import prompt_token_usage

from .models import (
    SIZE_CHOICES,
    ContractIssue,
    ParsedContract,
    ParsedFrame,
    PromptBlock,
)
from .parser import FRAME_ID_RE
from .profiles import FormatProfile
from .sources import ActionGroup, ActionMember
from .tokens import tag_keys, tokenize_prompt

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
# 动作库里的行内分角色写法 `::character A: … ::`（renderer 的 Auto 模式会拆出来）。
INLINE_CHARACTER_RE = re.compile(r"::character\s*([A-Za-z0-9_]+)\s*:", re.IGNORECASE)
# 这些分区多个角色常常共用（同一部作品），不用来判断「词属于哪个角色」。
SHARED_CHARACTER_SECTIONS = frozenset({"copyright", "role"})


@dataclass
class ValidationContext:
    contract: ParsedContract
    action_group: ActionGroup | None = None
    character_ids: list[str] = field(default_factory=list)
    references: dict[str, ActionMember | None] = field(default_factory=dict)
    conflict_rules: list[dict[str, list[str]]] = field(default_factory=lambda: list(DEFAULT_CONFLICTS))
    # 角色 id → 角色节点的词（归一化后），用来发现写错块的角色词。
    character_tags: dict[str, set[str]] = field(default_factory=dict)

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


_PAREN_WEIGHT_RE = re.compile(r":\s*-?\d+(?:\.\d+)?\s*\)")


def _text_for_count(text: str, profile: FormatProfile) -> str:
    submitted = profile.prompt_for_submit(text)
    if "paren" in profile.weight.syntaxes:
        # WebUI 数 token 前会去掉 (tag:1.2) 的括号和数值。
        submitted = re.sub(r"(?<!\\)[()]", "", _PAREN_WEIGHT_RE.sub(")", submitted))
    return submitted


def frame_token_usage(frame: ParsedFrame, profile: FormatProfile) -> dict | None:
    """一帧正向提示词的 token 用量：主提示词 + 各角色提示词（共用上限时加总）。"""
    if profile.length.tokenizer == "approx" and not profile.length.max_tokens:
        return None
    blocks = prompt_blocks(frame, "positive")
    if not blocks:
        return None
    main = next((block for block in blocks if not block.character), None)
    characters = [block for block in blocks if block.character]
    usage = prompt_token_usage(
        _text_for_count(main.text, profile) if main else "",
        [_text_for_count(block.text, profile) for block in characters],
        tokenizer=profile.length.tokenizer,
        limit=profile.length.max_tokens,
        shared=profile.length.shared_with_characters,
    )
    usage["blocks"] = {
        **({"positive": usage["base"]} if main else {}),
        **{block.key: count for block, count in zip(characters, usage["characters"])},
    }
    return usage


@register
class TokenLength(_Base):
    id = "token_length"

    def validate_frame(self, frame, profile, ctx):
        limit = profile.length.max_tokens
        usage = frame_token_usage(frame, profile)
        if not limit or not usage or not usage["over"]:
            return []
        exact = usage["exact"]
        severity = profile.length.over_limit if exact else "warn"
        amount = f"{usage['total']} token" if exact else f"约 {usage['total']} token（估算）"
        scope = "主提示词和角色提示词合计" if usage["shared"] and usage["characters"] else "正向提示词"
        tail = "；超出部分会被截断" if severity == "error" else "；可能被截断或效果变差"
        return [self.issue(
            severity,
            f"{scope} {amount}，超过 {profile.id} 的上限 {limit}{tail}。画风和质量词还会再占一部分",
            frame, block="positive",
        )]


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


def _count_tags(text: str, separator: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for tag in tokenize_prompt(text, separator):
        match = COUNT_TAG_RE.match(tag.key)
        if match:
            number = 6 if match.group(1) == "6+" else int(match.group(1))
            counts[match.group(2)] += number
    return counts


@register
class CharacterCount(_Base):
    id = "character_count"

    def validate_frame(self, frame, profile, ctx):
        positive = frame.positive
        if not positive:
            return []
        # 人数 tag 一般写在主提示词；主提示词没写时，按各角色块里的人数 tag 加总。
        counts = _count_tags(positive, profile.separator)
        if not counts:
            for block in prompt_blocks(frame, "positive"):
                if block.character:
                    counts.update(_count_tags(block.text, profile.separator))
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


def character_tag_keys(characters: dict[str, dict]) -> dict[str, set[str]]:
    """角色 id → 角色节点各分区的词（归一化），不含作品名等多个角色共用的分区。"""
    result: dict[str, set[str]] = {}
    for cid, summary in characters.items():
        keys: set[str] = set()
        for section, tags in (summary.get("sections") or {}).items():
            if section in SHARED_CHARACTER_SECTIONS:
                continue
            keys.update(tag_keys(", ".join(tags)))
        result[cid] = keys
    return result


@register
class CharacterBlocks(_Base):
    """分角色提示词（```positive cN）：主提示词写画面共用的部分，每个 cN 块写这个角色自己的全部内容。"""

    id = "character_blocks"

    def validate_frame(self, frame, profile, ctx):
        if not profile.multi_character.supported:
            return []
        issues = []
        blocks = [block for block in prompt_blocks(frame, "positive") if block.character]
        inline = sorted({match.group(1) for match in INLINE_CHARACTER_RE.finditer(frame.positive)})
        if inline and blocks:
            issues.append(self.issue(
                "error",
                f"主提示词里还有行内角色块（::character {'/'.join(inline)}: … ::），同时又写了 ```positive cN；行内块不会被拆出来，会原样提交",
                frame, block="positive",
                fix_hint="把行内块的内容挪进对应的 ```positive cN，主提示词里删掉 ::character …:: 这一段",
            ))
        elif inline:
            issues.append(self.issue(
                "info",
                f"主提示词里有行内角色块（::character {'/'.join(inline)}: … ::），出图时靠 Character Prompts 的 Auto 模式拆分",
                frame, block="positive",
                fix_hint="建议改写成 ```positive c1 / ```positive c2，分配更明确，Web 也能按角色显示",
            ))
        if not blocks:
            return issues

        if len(blocks) > profile.multi_character.max:
            issues.append(self.issue("error", f"角色块有 {len(blocks)} 个，超过 {profile.id} 的上限 {profile.multi_character.max}", frame))
        written = {block.character for block in blocks}
        for cid in frame.characters:
            if cid not in written:
                issues.append(self.issue("warn", f"本帧 characters 里有 {cid}，但没有 ```positive {cid}；这个角色只能靠主提示词描述", frame))
        if frame.characters:
            for cid in sorted(written - set(frame.characters)):
                issues.append(self.issue("warn", f"写了 ```positive {cid}，但本帧 characters 里没有 {cid}", frame, block=f"positive {cid}"))
        for block in prompt_blocks(frame, "negative"):
            if block.character and block.character not in written:
                issues.append(self.issue("warn", f"有 ```{block.key}，但没有 ```positive {block.character}", frame, block=block.key))

        tags = ctx.character_tags
        if not tags:
            return issues
        for block in blocks:
            own = tags.get(block.character or "", set())
            reported: set[str] = set()
            for tag in tokenize_prompt(block.text, profile.separator):
                if tag.key in own or tag.key in reported:
                    continue
                owner = next((cid for cid in sorted(tags) if cid != block.character and tag.key in tags[cid]), None)
                if owner:
                    reported.add(tag.key)
                    issues.append(self.issue(
                        "warn", f"「{tag.raw}」是 {owner} 的角色词，写在了 {block.character} 的块里", frame,
                        block=block.key, tag=tag.raw,
                    ))
        reported = set()
        for tag in tokenize_prompt(frame.positive, profile.separator):
            if tag.key in reported:
                continue
            owners = [cid for cid in sorted(written) if tag.key in tags.get(cid, set())]
            if len(owners) == 1 and not any(tag.key in tags.get(cid, set()) for cid in tags if cid != owners[0]):
                reported.add(tag.key)
                issues.append(self.issue(
                    "warn", f"「{tag.raw}」是 {owners[0]} 的角色词，写在了主提示词里；分角色时应写进 ```positive {owners[0]}", frame,
                    block="positive", tag=tag.raw,
                ))
        return issues


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


