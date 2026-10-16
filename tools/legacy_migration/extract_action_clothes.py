"""Compatibility forwarding module.

The canonical implementation has moved to:
design/动作改2/tools/extract_action_clothes.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_CANONICAL_PATH = (
    Path(__file__).resolve().parents[3]
    / "design"
    / "动作改2"
    / "tools"
    / "extract_action_clothes.py"
)

if not _CANONICAL_PATH.exists():
    raise FileNotFoundError(f"Canonical script not found: {_CANONICAL_PATH}")

_spec = importlib.util.spec_from_file_location(
    "extract_action_clothes_canonical", str(_CANONICAL_PATH)
)
if _spec and _spec.loader:
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    for _name in dir(_module):
        if not _name.startswith("__"):
            globals()[_name] = getattr(_module, _name)

if __name__ == "__main__":
    if "main" in globals():
        raise SystemExit(globals()["main"]())
