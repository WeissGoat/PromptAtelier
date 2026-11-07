from __future__ import annotations

from pathlib import Path

from fastapi import Request

from tags_machine_core.nodes.role_paths import role_roots
from tags_machine_core.style_lab.library import LibraryIndex


# 这些角色的行为都写在节点定义文件里，可以安全地按内容合并副本目录。
# artist 的 ComfyUI 工作流还可能放在其他文件里，不能只看 node.yaml。
DEDUPE_ROLES = frozenset({"character", "action", "background", "clothing"})


def node_library_index(request: Request) -> LibraryIndex:
    """Custom 节点搜索和 Style Lab 素材搜索共用的去重索引。"""
    state = request.app.state
    index = getattr(state, "node_library_index", None)
    if index is None:
        workspace = state.node_workspace
        index = LibraryIndex(
            lambda role: role_roots(workspace.design_root, role),
            lambda path: workspace.previews.preview_for(path) is not None,
            cache_path=Path(state.style_lab_store.runtime_dir) / "library_index.json",
        )
        state.node_library_index = index
    return index
