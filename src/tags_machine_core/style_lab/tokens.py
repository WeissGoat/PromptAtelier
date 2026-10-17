"""NovelAI 提示词的无损分词。

和 web/src/styleLab/tokens.ts 是同一套规则，两边共用 tests/fixtures/prompt_tokens.json 的用例：

- 按逗号（含全角）、竖线、换行切开；
- 成对的 {} [] () 内部不切，"artist:[[a, b]]" 是一个 token；没配对的括号当普通字符；
- "1.2::a, b::" 这类权重组整体是一个 token（支持嵌套，"数字::" 开、单独的 "::" 关）；没闭合的权重不成组；
- 每个 token 记住它前面的原始分隔符，原样拼回去和原文逐字节相同。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


SEPARATORS = frozenset(",，|\n")
_OPENERS = {"{": "}", "[": "]", "(": ")"}
_WEIGHT_OPEN_RE = re.compile(r"-?\d+(?:\.\d+)?::")
_SD_WEIGHT_RE = re.compile(r":-?\d+(?:\.\d+)?$")
_DEFAULT_SEP = ", "


@dataclass
class Token:
    text: str
    sep: str = ""


@dataclass
class TokenList:
    leading: str = ""
    tokens: list[Token] = field(default_factory=list)
    trailing: str = ""

    def texts(self) -> list[str]:
        return [token.text for token in self.tokens]


def tokenize(text: str) -> TokenList:
    text = text or ""
    protected = _protected_mask(text)
    segments: list[tuple[int, int]] = []
    start = 0
    for index, char in enumerate(text):
        if char in SEPARATORS and not protected[index]:
            segments.append((start, index))
            start = index + 1
    segments.append((start, len(text)))

    result = TokenList()
    cursor = 0
    for seg_start, seg_end in segments:
        raw = text[seg_start:seg_end]
        stripped = raw.strip()
        if not stripped:
            continue
        token_start = seg_start + (len(raw) - len(raw.lstrip()))
        token_end = token_start + len(stripped)
        gap = text[cursor:token_start]
        if result.tokens:
            result.tokens.append(Token(text=stripped, sep=gap))
        else:
            result.leading = gap
            result.tokens.append(Token(text=stripped, sep=""))
        cursor = token_end
    if result.tokens:
        result.trailing = text[cursor:]
    else:
        result.leading = text
    return result


def serialize(tokens: TokenList) -> str:
    """拼回字符串。第一个 token 不带分隔符；新加或挪动后没有分隔符的 token 用 ", "。"""
    if not tokens.tokens:
        return tokens.leading + tokens.trailing
    parts = [tokens.leading, tokens.tokens[0].text]
    for token in tokens.tokens[1:]:
        parts.append(token.sep if _has_separator(token.sep) else _DEFAULT_SEP)
        parts.append(token.text)
    parts.append(tokens.trailing)
    return "".join(parts)


def join_token_texts(texts: list[str]) -> str:
    return _DEFAULT_SEP.join(text for text in texts if text)


def inner_tags(token_text: str) -> list[str]:
    """把一个 token（可能是权重组或括号组）拆成用于统计和翻译的普通 tag，已规范化。"""
    text = _WEIGHT_OPEN_RE.sub(",", token_text)
    text = text.replace("::", ",")
    for char in "{}[]":
        text = text.replace(char, ",")
    tags: list[str] = []
    for part in re.split(r"[,，|\n]", text):
        tag = part.strip()
        if tag.startswith("(") and ")" not in tag:
            tag = tag[1:].strip()
        if tag.endswith(")") and "(" not in tag:
            tag = tag[:-1].strip()
        tag = _SD_WEIGHT_RE.sub("", tag).strip()
        tag = re.sub(r"\s+", " ", tag.replace("_", " ")).strip().lower()
        tag = re.sub(r"^artist:\s*", "", tag)
        if tag and not tag.endswith(":"):
            tags.append(tag)
    return tags


def _has_separator(sep: str) -> bool:
    return any(char in SEPARATORS for char in sep)


def _protected_mask(text: str) -> list[bool]:
    protected = [False] * len(text)
    for start, end in _bracket_ranges(text) + _weight_ranges(text):
        for index in range(start, end):
            protected[index] = True
    return protected


def _bracket_ranges(text: str) -> list[tuple[int, int]]:
    """配对的括号范围（含括号本身）；没配对的开括号或闭括号忽略。"""
    ranges: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        if char in _OPENERS:
            stack.append((char, index))
        elif char in _OPENERS.values():
            for depth in range(len(stack) - 1, -1, -1):
                if _OPENERS[stack[depth][0]] == char:
                    opener_index = stack[depth][1]
                    del stack[depth:]
                    ranges.append((opener_index, index + 1))
                    break
    return ranges


def _weight_ranges(text: str) -> list[tuple[int, int]]:
    """权重组范围：从 "数字::" 到配对的单独 "::"（含）。"""
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        # 紧跟在上一个权重组后面（只隔空格）的也算组的开头："1.2::a,:: -2::b, c,::"。
        after_group = bool(ranges) and not text[ranges[-1][1] : index].strip(" \t")
        start = after_group or _is_token_start(text, index)
        match = _WEIGHT_OPEN_RE.match(text, index) if start else None
        if not match:
            index += 1
            continue
        end = _weight_close(text, match.end())
        if end is None:
            index = match.end()
            continue
        ranges.append((index, end))
        index = end
    return ranges


def _weight_close(text: str, position: int) -> int | None:
    depth = 1
    index = position
    while index < len(text) - 1:
        if text.startswith("::", index):
            opener = _opener_ending_at(text, index)
            if opener:
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return index + 2
            index += 2
            continue
        index += 1
    return None


def _opener_ending_at(text: str, colon_index: int) -> bool:
    """colon_index 处的 "::" 前面紧跟数字，说明它是新的权重开头而不是闭合。"""
    match = re.search(r"-?\d+(?:\.\d+)?$", text[:colon_index])
    return bool(match)


def _is_token_start(text: str, index: int) -> bool:
    before = text[:index].rstrip(" \t")
    return not before or before[-1] in SEPARATORS or before[-1] in "{[("
