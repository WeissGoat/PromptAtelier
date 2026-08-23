from __future__ import annotations

import re
from collections.abc import Mapping


_SHORTCUT_SUFFIX = re.compile(r"\s*-\s*快捷方式\s*$", re.IGNORECASE)
_DANBOORU_LINK_PREFIX = re.compile(r"^\d+a?(?=danbooru_)", re.IGNORECASE)


class NodeIdentityNormalizer:
    """将节点的显示名称归一化为用于分类的稳定身份。

    原始 Reader/Catalog 数据不会被改写。归一化只发生在节点值投影时，
    因此可以同时保留旧链接名称和真实节点路径用于追溯。
    """

    def __init__(
        self,
        aliases: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self._aliases = {
            (str(role).casefold(), str(value).casefold()): str(target).strip()
            for (role, value), target in (aliases or {}).items()
            if str(role).strip() and str(value).strip() and str(target).strip()
        }

    def normalize(self, role: str, value: str) -> str:
        text = str(value or "").strip()
        if not text or str(role).casefold() != "character":
            return text

        # 快捷方式节点通常在名称末尾追加这个标记。
        normalized = _SHORTCUT_SUFFIX.sub("", text).strip()
        # 特殊_next_select 中的角色快捷方式会在 danbooru 节点名前加 1a/2a 等编号。
        normalized = _DANBOORU_LINK_PREFIX.sub("", normalized).strip()
        alias_key = (str(role).casefold(), normalized.casefold())
        return self._aliases.get(alias_key, normalized)


DEFAULT_NODE_IDENTITY_NORMALIZER = NodeIdentityNormalizer()


def normalize_node_identity(role: str, value: str) -> str:
    return DEFAULT_NODE_IDENTITY_NORMALIZER.normalize(role, value)
