"""把 NovelAI 写法的提示词转换成 ComfyUI（CLIPTextEncode）写法。

节点里普遍用 NovelAI 加权：{x} 每层 ×1.05，[x] 每层 ÷1.05，1.2::x:: 是数值加权；
NovelAI 里圆括号只是普通字符。ComfyUI 用 (x:1.05) 表示加权，圆括号需要转义。
"""

from __future__ import annotations

import re


EMPHASIS_STEP = 1.05
_NUMERIC_WEIGHT = re.compile(r"(-?\d+(?:\.\d+)?)::")
_UNESCAPED_PAREN = re.compile(r"(?<!\\)([()])")
_RUN_EDGES = re.compile(r"^([\s,]*)(.*?)([\s,]*)$", re.S)


def novelai_to_comfyui_prompt(text: str) -> str:
    if not text:
        return text
    return "".join(_render_runs(_weighted_runs(text)))


def _weighted_runs(text: str) -> list[tuple[str, float]]:
    runs: list[tuple[str, float]] = []
    position = 0
    while position < len(text):
        match = _NUMERIC_WEIGHT.search(text, position)
        if match is None:
            runs.extend(_bracket_runs(text[position:], 1.0))
            break
        runs.extend(_bracket_runs(text[position:match.start()], 1.0))
        end = text.find("::", match.end())
        inner_end = len(text) if end < 0 else end
        runs.extend(_bracket_runs(text[match.end():inner_end], float(match.group(1))))
        position = len(text) if end < 0 else end + 2
    return runs


def _bracket_runs(text: str, base: float) -> list[tuple[str, float]]:
    runs: list[tuple[str, float]] = []
    braces = brackets = 0
    current: list[str] = []

    def flush() -> None:
        if current:
            weight = base * EMPHASIS_STEP ** (braces - brackets)
            runs.append(("".join(current), weight))
            current.clear()

    for char in text:
        if char in "{[":
            flush()
            if char == "{":
                braces += 1
            else:
                brackets += 1
        elif char in "}]":
            flush()
            # 多余的闭合括号直接丢弃；未闭合的开括号一直作用到末尾，和 NovelAI 一致。
            if char == "}" and braces:
                braces -= 1
            elif char == "]" and brackets:
                brackets -= 1
        else:
            current.append(char)
    flush()
    return runs


def _render_runs(runs: list[tuple[str, float]]) -> list[str]:
    output: list[str] = []
    for text, weight in runs:
        escaped = _UNESCAPED_PAREN.sub(r"\\\1", text)
        rounded = round(weight, 2)
        lead, core, trail = _RUN_EDGES.match(escaped).groups()
        if not core or rounded == 1:
            output.append(escaped)
            continue
        output.append(f"{lead}({core}:{_format_weight(rounded)}){trail}")
    return output


def _format_weight(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
