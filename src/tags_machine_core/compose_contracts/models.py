from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CONTRACT_SCHEMA = "tags-machine.compose-contract/v1"
ContractStatus = Literal["pending", "done"]
Severity = Literal["error", "warn", "info"]
SIZE_CHOICES = ("portrait", "landscape", "square")
FRAME_META_KEYS = ("source", "inspired_by", "characters", "size")
CUSTOM_SOURCE = "custom"


class NodeRefEntry(BaseModel):
    ref: str
    content_hash: str | None = None


class ContractNodes(BaseModel):
    characters: dict[str, NodeRefEntry] = Field(default_factory=dict)
    action_group: NodeRefEntry | None = None
    clothing: NodeRefEntry | None = None
    background: NodeRefEntry | None = None


class ContractOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    keep_order: bool = True
    allow_new_frames: bool = True
    max_new_frames: int = 2


class ContractRequest(BaseModel):
    """契约 front matter：请求部分由 Web 创建；Agent 只改 title / author / status。"""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    schema_id: str = Field(default=CONTRACT_SCHEMA, alias="schema")
    id: str
    title: str = ""
    status: ContractStatus = "pending"
    created_at: str = ""
    target_format: str = "nai-v4.5"
    nodes: ContractNodes = Field(default_factory=ContractNodes)
    requirements: str = ""
    options: ContractOptions = Field(default_factory=ContractOptions)
    author: str = ""


class PromptBlock(BaseModel):
    """帧里的一个提示词代码块：kind 为 positive / negative，character 为空表示主提示词。"""

    kind: Literal["positive", "negative"]
    character: str | None = None
    text: str
    # 代码块内容在文件中的行范围（不含围栏行），0 起，左闭右开；用于按帧写回。
    start_line: int
    end_line: int

    @property
    def key(self) -> str:
        return self.kind if not self.character else f"{self.kind} {self.character}"


class ParsedFrame(BaseModel):
    id: str
    title: str = ""
    source: str | None = None
    inspired_by: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    size: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)
    blocks: list[PromptBlock] = Field(default_factory=list)
    notes: str = ""
    # 帧在文件中的行范围：标题行到下一帧标题前，0 起，左闭右开。
    start_line: int
    end_line: int
    # 帧标题之后、但不是合法帧元数据或代码块的结构问题（如未闭合的代码块）。
    parse_errors: list[str] = Field(default_factory=list)

    @property
    def is_custom(self) -> bool:
        return (self.source or "").strip().lower() == CUSTOM_SOURCE

    def block(self, kind: str, character: str | None = None) -> PromptBlock | None:
        for block in self.blocks:
            if block.kind == kind and (block.character or None) == (character or None):
                return block
        return None

    @property
    def positive(self) -> str:
        block = self.block("positive")
        return block.text if block else ""

    @property
    def negative(self) -> str:
        block = self.block("negative")
        return block.text if block else ""

    def prompts(self) -> dict[str, str]:
        return {block.key: block.text for block in self.blocks}


class ParsedContract(BaseModel):
    request: ContractRequest
    frames: list[ParsedFrame] = Field(default_factory=list)
    preamble: str = ""
    front_matter_end_line: int = 0
    parse_errors: list[str] = Field(default_factory=list)

    def frame(self, frame_id: str) -> ParsedFrame | None:
        return next((frame for frame in self.frames if frame.id == frame_id), None)


class ContractIssue(BaseModel):
    validator: str
    severity: Severity
    message: str
    frame_id: str | None = None
    block: str | None = None
    tag: str | None = None
    fix_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
