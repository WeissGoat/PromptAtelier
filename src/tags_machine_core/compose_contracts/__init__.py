"""Agent 拼接契约（Compose Contract）：Markdown 契约文件的解析、写回、校验与要求 prompt。

设计见 docs/agent_compose_contract_spec_v1.md。提示词全部由 Agent 写；这里只负责
读写文件、读取来源节点、校验和生成给 Agent 的要求 prompt，不生成提示词内容。
"""

from .models import (
    CONTRACT_SCHEMA,
    ContractIssue,
    ContractRequest,
    ParsedContract,
    ParsedFrame,
)
from .parser import parse_contract
from .profiles import FormatProfile, load_format_profiles
from .service import ContractService
from .store import ContractConflictError, ContractStore

__all__ = [
    "CONTRACT_SCHEMA",
    "ContractConflictError",
    "ContractIssue",
    "ContractRequest",
    "ContractService",
    "ContractStore",
    "FormatProfile",
    "ParsedContract",
    "ParsedFrame",
    "load_format_profiles",
    "parse_contract",
]
