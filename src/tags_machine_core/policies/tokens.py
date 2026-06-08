from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


OutputStyle = Literal["underscore", "preserve"]


_NUMERIC_WEIGHT_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?::)(.*)(::)$")
_SPACE_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_+")


@dataclass(frozen=True)
class PromptToken:
    raw: str
    body: str
    canonical: str
    weight_prefix: str = ""
    weight_suffix: str = ""
    separator: str = ","

    def with_body(self, body: str) -> "PromptToken":
        return PromptToken(
            raw=self.raw,
            body=body,
            canonical=canonicalize_tag(body),
            weight_prefix=self.weight_prefix,
            weight_suffix=self.weight_suffix,
            separator=self.separator,
        )

    def render(self, output_style: OutputStyle = "underscore") -> str:
        body = self.body.strip()
        if output_style == "underscore":
            body = canonicalize_tag(body)
        return f"{self.weight_prefix}{body}{self.weight_suffix}"

    def weight_strength(self) -> float:
        if self.weight_prefix.endswith("::"):
            try:
                return float(self.weight_prefix.removesuffix("::"))
            except ValueError:
                return 1.0
        return 1.0 + self.weight_prefix.count("{") - (self.weight_prefix.count("[") * 0.25)


def canonicalize_tag(value: str) -> str:
    text = value.strip().lower()
    text = _SPACE_RE.sub("_", text)
    text = text.replace("-", "_")
    text = _UNDERSCORE_RE.sub("_", text)
    return text.strip("_")


def parse_prompt_tokens(prompt: str) -> list[PromptToken]:
    tokens: list[PromptToken] = []
    for raw_part in str(prompt or "").split(","):
        raw = raw_part.strip()
        if not raw:
            continue
        tokens.append(parse_prompt_token(raw))
    return tokens


def parse_prompt_token(raw: str) -> PromptToken:
    numeric = _NUMERIC_WEIGHT_RE.match(raw)
    if numeric:
        prefix, body, suffix = numeric.groups()
        return PromptToken(
            raw=raw,
            body=body.strip(),
            canonical=canonicalize_tag(body),
            weight_prefix=prefix,
            weight_suffix=suffix,
        )

    prefix, body, suffix = _strip_bracket_weight(raw)
    return PromptToken(
        raw=raw,
        body=body.strip(),
        canonical=canonicalize_tag(body),
        weight_prefix=prefix,
        weight_suffix=suffix,
    )


def render_prompt_tokens(
    tokens: list[PromptToken],
    output_style: OutputStyle = "underscore",
) -> str:
    return ", ".join(token.render(output_style) for token in tokens if token.body.strip())


def _strip_bracket_weight(raw: str) -> tuple[str, str, str]:
    if not raw:
        return "", raw, ""
    open_char = raw[0]
    if open_char not in "{[":
        return "", raw, ""
    close_char = "}" if open_char == "{" else "]"
    prefix_len = 0
    for char in raw:
        if char == open_char:
            prefix_len += 1
        else:
            break
    suffix_len = 0
    for char in reversed(raw):
        if char == close_char:
            suffix_len += 1
        else:
            break
    if prefix_len == 0 or suffix_len == 0:
        return "", raw, ""
    weight_len = min(prefix_len, suffix_len)
    prefix = raw[:weight_len]
    suffix = raw[len(raw) - weight_len :]
    body = raw[weight_len : len(raw) - weight_len]
    if not body:
        return "", raw, ""
    return prefix, body, suffix
