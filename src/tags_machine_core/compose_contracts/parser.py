"""契约 Markdown 的解析与按帧写回。

格式（§4）：YAML front matter + 每帧一个 `## <帧id> <标题>` 小节；标题下的 `key: value`
行是帧元数据；```positive / ```negative（多角色时 ```positive c2）代码块是提示词；
其余文字都算该帧备注。写回时只替换目标代码块或 front matter 中的个别字段，其余原样保留。
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from .models import (
    FRAME_META_KEYS,
    ContractRequest,
    ParsedContract,
    ParsedFrame,
    PromptBlock,
)


FRAME_HEADER_RE = re.compile(r"^##(?!#)\s+(\S+)(?:\s+(.*?))?\s*$")
FRAME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})\s*(?P<info>.*?)\s*$")
META_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_]+)\s*:\s*(?P<value>.*?)\s*$")
PROMPT_INFO_RE = re.compile(r"^(?P<kind>positive|negative)(?:\s+(?P<character>[A-Za-z0-9_\-]+))?$", re.IGNORECASE)


class ContractParseError(ValueError):
    pass


def split_front_matter(text: str) -> tuple[dict[str, Any], list[str], int]:
    """返回 (front matter 数据, 全文行列表, 正文起始行号)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractParseError("契约文件必须以 YAML front matter（--- 行）开头")
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            raw = "\n".join(lines[1:index])
            try:
                data = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                raise ContractParseError(f"front matter 不是合法 YAML：{exc}") from exc
            if not isinstance(data, dict):
                raise ContractParseError("front matter 必须是 YAML 映射")
            return data, lines, index + 1
    raise ContractParseError("front matter 没有结束的 --- 行")


def parse_contract(text: str) -> ParsedContract:
    data, lines, body_start = split_front_matter(text)
    data = dict(data)
    for key in ("title", "author", "requirements"):
        if data.get(key) is None:
            data[key] = ""
        elif not isinstance(data[key], str):
            data[key] = str(data[key])
    data["requirements"] = str(data.get("requirements") or "").strip()
    if data.get("created_at") is not None and not isinstance(data["created_at"], str):
        data["created_at"] = str(data["created_at"])
    request = ContractRequest.model_validate(data)
    frames, preamble, errors = _parse_frames(lines, body_start)
    return ParsedContract(
        request=request,
        frames=frames,
        preamble=preamble,
        front_matter_end_line=body_start,
        parse_errors=errors,
    )


def _parse_frames(lines: list[str], start: int) -> tuple[list[ParsedFrame], str, list[str]]:
    header_rows: list[int] = []
    fence: tuple[str, int] | None = None
    for index in range(start, len(lines)):
        match = FENCE_RE.match(lines[index])
        if fence is not None:
            if match and match.group("fence")[0] == fence[0] and len(match.group("fence")) >= fence[1] and not match.group("info"):
                fence = None
            continue
        if match:
            fence = (match.group("fence")[0], len(match.group("fence")))
            continue
        if FRAME_HEADER_RE.match(lines[index]):
            header_rows.append(index)

    first = header_rows[0] if header_rows else len(lines)
    preamble = "\n".join(lines[start:first]).strip()
    frames: list[ParsedFrame] = []
    errors: list[str] = []
    for position, row in enumerate(header_rows):
        end = header_rows[position + 1] if position + 1 < len(header_rows) else len(lines)
        frames.append(_parse_frame(lines, row, end))
    return frames, preamble, errors


def _parse_frame(lines: list[str], start: int, end: int) -> ParsedFrame:
    header = FRAME_HEADER_RE.match(lines[start])
    assert header is not None
    frame_id = header.group(1)
    title = (header.group(2) or "").strip()
    meta: dict[str, str] = {}
    blocks: list[PromptBlock] = []
    note_lines: list[str] = []
    errors: list[str] = []

    index = start + 1
    # 帧元数据：标题下方连续的 key: value 行（允许先空行）。
    while index < end and not lines[index].strip():
        index += 1
    while index < end:
        match = META_LINE_RE.match(lines[index].strip())
        if not match or match.group("key").lower() not in FRAME_META_KEYS:
            break
        meta[match.group("key").lower()] = match.group("value")
        index += 1

    while index < end:
        line = lines[index]
        match = FENCE_RE.match(line)
        if not match:
            note_lines.append(line)
            index += 1
            continue
        fence_char = match.group("fence")[0]
        fence_len = len(match.group("fence"))
        info = match.group("info")
        close = None
        for probe in range(index + 1, end):
            closing = FENCE_RE.match(lines[probe])
            if closing and closing.group("fence")[0] == fence_char and len(closing.group("fence")) >= fence_len and not closing.group("info"):
                close = probe
                break
        if close is None:
            errors.append(f"第 {index + 1} 行的代码块没有闭合")
            note_lines.extend(lines[index:end])
            break
        prompt_info = PROMPT_INFO_RE.match(info)
        if prompt_info:
            blocks.append(
                PromptBlock(
                    kind=prompt_info.group("kind").lower(),
                    character=prompt_info.group("character") or None,
                    text="\n".join(lines[index + 1 : close]).strip("\n"),
                    start_line=index + 1,
                    end_line=close,
                )
            )
        else:
            note_lines.extend(lines[index : close + 1])
        index = close + 1

    return ParsedFrame(
        id=frame_id,
        title=title,
        source=(meta.get("source") or "").strip() or None,
        inspired_by=_split_list(meta.get("inspired_by")),
        characters=_split_list(meta.get("characters")),
        size=(meta.get("size") or "").strip().lower() or None,
        meta=meta,
        blocks=blocks,
        notes="\n".join(note_lines).strip(),
        start_line=start,
        end_line=end,
        parse_errors=errors,
    )


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，]", value) if item.strip()]


# ---------------------------------------------------------------------------
# 写回
# ---------------------------------------------------------------------------


def replace_frame_prompts(text: str, frame_id: str, prompts: dict[str, str]) -> str:
    """只替换某一帧的提示词代码块内容。

    prompts 的键为 `positive` / `negative` / `positive c2` 等；值为空字符串时删除该代码块
    （positive 主代码块保留为空块）；该帧原来没有的代码块追加在最后一个代码块之后。
    """
    contract = parse_contract(text)
    frame = contract.frame(frame_id)
    if frame is None:
        raise KeyError(f"契约中没有帧 {frame_id}")
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")

    edits: list[tuple[int, int, list[str]]] = []
    existing = {block.key: block for block in frame.blocks}
    for key, value in prompts.items():
        normalized_key = _normalize_block_key(key)
        new_lines = _content_lines(value)
        block = existing.get(normalized_key)
        if block is not None:
            if not new_lines and normalized_key != "positive":
                # 删掉整个代码块（含围栏），以及紧跟着的一个空行。
                stop = block.end_line + 1
                if stop < len(lines) and not lines[stop].strip():
                    stop += 1
                edits.append((block.start_line - 1, stop, []))
            else:
                edits.append((block.start_line, block.end_line, new_lines))
    appended: list[str] = []
    for key, value in prompts.items():
        normalized_key = _normalize_block_key(key)
        if normalized_key in existing:
            continue
        new_lines = _content_lines(value)
        if not new_lines:
            continue
        appended.extend(["", f"```{normalized_key}", *new_lines, "```"])
    if appended:
        anchor = max((block.end_line for block in frame.blocks), default=None)
        if anchor is None:
            anchor = _frame_meta_end(lines, frame)
            edits.append((anchor, anchor, appended))
        else:
            edits.append((anchor + 1, anchor + 1, appended))

    for start, stop, replacement in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
        lines[start:stop] = replacement
    result = "\n".join(lines)
    return result + "\n" if trailing_newline or not result.endswith("\n") else result


def _frame_meta_end(lines: list[str], frame: ParsedFrame) -> int:
    """帧标题和元数据行之后的位置：没有代码块的帧，新代码块插在这里。"""
    index = frame.start_line + 1
    probe = index
    while probe < frame.end_line and not lines[probe].strip():
        probe += 1
    while probe < frame.end_line:
        match = META_LINE_RE.match(lines[probe].strip())
        if not match or match.group("key").lower() not in FRAME_META_KEYS:
            break
        probe += 1
        index = probe
    return index


def _normalize_block_key(key: str) -> str:
    parts = str(key).strip().split()
    if not parts or parts[0].lower() not in {"positive", "negative"} or len(parts) > 2:
        raise ValueError(f"无效的提示词代码块名：{key!r}")
    return " ".join([parts[0].lower(), *parts[1:]])


def _content_lines(value: str) -> list[str]:
    text = str(value or "").replace("\r\n", "\n").strip("\n")
    if not text.strip():
        return []
    lines = text.split("\n")
    for line in lines:
        if FENCE_RE.match(line):
            raise ValueError("提示词里不能包含 ``` 代码块围栏")
    return lines


def set_front_matter_fields(text: str, fields: dict[str, str]) -> str:
    """改 front matter 中的顶层标量字段（status / title / author），其余行原样保留。"""
    _, lines, body_start = split_front_matter(text)
    end = body_start - 1
    for key, value in fields.items():
        rendered = f"{key}: {_yaml_scalar(value)}"
        pattern = re.compile(rf"^{re.escape(key)}\s*:")
        row = next((i for i in range(1, end) if pattern.match(lines[i])), None)
        if row is not None:
            # 只替换单行标量；不处理多行块（这些字段 Web 创建时都是单行）。
            lines[row] = rendered
        else:
            lines.insert(end, rendered)
            end += 1
    result = "\n".join(lines)
    return result + "\n" if text.endswith("\n") or not result.endswith("\n") else result


def replace_body(text: str, body: str) -> str:
    """保留 front matter，替换其后的全部正文（导入帧内容时用）。"""
    _, lines, body_start = split_front_matter(text)
    head = "\n".join(lines[:body_start])
    return f"{head}\n\n{body.strip()}\n"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text and re.fullmatch(r"[A-Za-z0-9_.\-]+", text) and text.lower() not in {"null", "true", "false", "yes", "no", "on", "off", "~"}:
        return text
    return json.dumps(text, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 导入：外部 agent 输出的帧内容
# ---------------------------------------------------------------------------


def extract_import_frames(raw: str) -> tuple[str, dict[str, str]]:
    """从外部 agent 的输出里取出帧正文，以及可能附带的 title / author。

    兼容：整段包在 ```markdown 代码块里；带一份 front matter；帧前有说明文字。
    """
    text = str(raw or "").replace("\r\n", "\n").strip()
    outer = re.match(r"^(`{3,}|~{3,})[ \t]*(markdown|md)?[ \t]*\n(.*)\n\1[ \t]*$", text, re.DOTALL | re.IGNORECASE)
    if outer:
        text = outer.group(3).strip()
    extra: dict[str, str] = {}
    if text.startswith("---"):
        try:
            data, lines, body_start = split_front_matter(text)
        except ContractParseError:
            data, lines, body_start = {}, text.splitlines(), 0
        for key in ("title", "author"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                extra[key] = value.strip()
        text = "\n".join(lines[body_start:]).strip()
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if FRAME_HEADER_RE.match(line)), None)
    if first is None:
        raise ContractParseError("没有找到帧：每帧需要以「## f01 标题」这样的二级标题开头")
    return "\n".join(lines[first:]).strip(), extra
