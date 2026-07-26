from __future__ import annotations

from pathlib import Path


ROLE_DIRS: dict[str, tuple[str, ...]] = {
    "artist": ("画风", "artist", "artists"),
    "character": ("角色", "character", "characters"),
    "action": ("动作改2", "动作", "action", "actions"),
    "background": ("背景", "background", "backgrounds"),
}


def role_dir_names(role: str) -> tuple[str, ...]:
    normalized = role.strip().lower()
    return ROLE_DIRS.get(normalized, (normalized,))


def role_roots(design_root: str | Path, role: str) -> list[Path]:
    root = Path(design_root).resolve()
    return [root / name for name in role_dir_names(role)]


def primary_role_root(design_root: str | Path, role: str) -> Path:
    roots = role_roots(design_root, role)
    return next((root for root in roots if root.is_dir()), roots[0])


def resolve_role_relative_path(design_root: str | Path, role: str, value: str) -> Path:
    raw = Path(value.strip())
    if raw.is_absolute():
        raise ValueError(f"随机节点路径必须相对 {role} 根目录")

    root = primary_role_root(design_root, role).resolve()
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"随机节点路径必须位于 {role} 根目录内") from exc
    return resolved
