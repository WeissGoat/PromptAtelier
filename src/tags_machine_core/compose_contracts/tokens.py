"""契约提示词分词：按分隔符和换行切分，剥离权重写法，归一化成「裸 tag + 权重」。

与 Web 端 `web/src/contracts/analysis.ts` 的规则保持一致（§5.1、§5.2）：
- 权重写法：`{x}` `[x]`（NovelAI 括号）、`1.2::x::`（NovelAI 数值，可跨多个 tag）、`(x:1.2)` / `(x)`（SD）；
- 归一化：去权重、`\\(` 反转义、小写、空格/连字符 → 下划线（同 policies.tokens.canonicalize_tag）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tags_machine_core.policies.tokens import canonicalize_tag


_NUMERIC_OPEN_RE = re.compile(r"^(-?\d+(?:\.\d+)?)::")
_PAREN_WEIGHT_RE = re.compile(r"^\((.*):\s*(-?\d+(?:\.\d+)?)\)$", re.DOTALL)
_ESCAPED_PAREN_RE = re.compile(r"\\([()\[\]{}])")
NAI_BRACE_STEP = 1.05
SD_PAREN_STEP = 1.1


@dataclass
class PromptTag:
    raw: str
    body: str
    key: str
    weight: float
    start: int
    end: int
    line: int
    syntaxes: set[str] = field(default_factory=set)


def normalize_tag(body: str) -> str:
    text = _ESCAPED_PAREN_RE.sub(r"\1", body.strip())
    return canonicalize_tag(text)


def tokenize_prompt(text: str, separator: str = ",") -> list[PromptTag]:
    """切分提示词。权重括号与数值权重可以跨多个 tag 生效（`{a, b}`、`1.2::a, b::`）。"""
    tags: list[PromptTag] = []
    brace_depth = 0  # {} 为 +1，[] 为 -1（NovelAI）
    numeric: float | None = None
    offset = 0
    for line_no, line in enumerate(str(text or "").split("\n")):
        position = 0
        for part in line.split(separator):
            start = offset + position + (len(part) - len(part.lstrip()))
            position += len(part) + len(separator)
            raw = part.strip()
            if not raw:
                continue
            syntaxes: set[str] = set()
            body = raw
            # 打开：数值权重
            numeric_here = numeric
            opened_numeric = False
            match = _NUMERIC_OPEN_RE.match(body)
            if match:
                numeric_here = float(match.group(1))
                body = body[match.end():]
                syntaxes.add("numeric")
                opened_numeric = True
            closes_numeric = False
            if body.endswith("::") and (numeric_here is not None):
                body = body[:-2]
                closes_numeric = True
                syntaxes.add("numeric")
            elif numeric is not None:
                syntaxes.add("numeric")
            # 括号权重
            lead_open = len(body) - len(body.lstrip("{["))
            opens = body[:lead_open]
            body = body[lead_open:]
            trail_close = len(body) - len(body.rstrip("}]"))
            closes = body[len(body) - trail_close:] if trail_close else ""
            body = body[: len(body) - trail_close] if trail_close else body
            depth_here = brace_depth + opens.count("{") - opens.count("[")
            if opens or closes or brace_depth:
                syntaxes.add("brace")
            # SD 括号权重
            sd_weight = 1.0
            paren = _PAREN_WEIGHT_RE.match(body)
            if paren:
                body = paren.group(1)
                sd_weight = float(paren.group(2))
                syntaxes.add("paren")
            else:
                while body.startswith("(") and body.endswith(")") and not body.startswith("\\("):
                    body = body[1:-1]
                    sd_weight *= SD_PAREN_STEP
                    syntaxes.add("paren")
            weight = (numeric_here if numeric_here is not None else 1.0) * (NAI_BRACE_STEP ** depth_here) * sd_weight
            body = body.strip()
            if body:
                tags.append(
                    PromptTag(
                        raw=raw,
                        body=body,
                        key=normalize_tag(body),
                        weight=round(weight, 4),
                        start=start,
                        end=start + len(raw),
                        line=line_no,
                        syntaxes=syntaxes,
                    )
                )
            brace_depth = depth_here - closes.count("}") + closes.count("]")
            if opened_numeric and not closes_numeric:
                numeric = numeric_here
            elif closes_numeric:
                numeric = None
        offset += len(line) + 1
    return tags


def tag_keys(text: str, separator: str = ",") -> list[str]:
    return [tag.key for tag in tokenize_prompt(text, separator) if tag.key]
