from __future__ import annotations

from pathlib import Path


PROVIDER_NAME = "anr_plugin_auto_mosaics"
DEFAULT_MODEL_DIRECTORY = Path("models") / "anr_plugin_auto_mosaics"
MODEL_STATUS_READY = "ready"
MODEL_STATUS_MISSING = "missing"
MODEL_STATUS_CHECKSUM_MISMATCH = "checksum_mismatch"

__all__ = [
    "DEFAULT_MODEL_DIRECTORY",
    "MODEL_STATUS_CHECKSUM_MISMATCH",
    "MODEL_STATUS_MISSING",
    "MODEL_STATUS_READY",
    "PROVIDER_NAME",
]
