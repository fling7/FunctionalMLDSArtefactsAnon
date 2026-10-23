from __future__ import annotations

from typing import Dict


BACKEND_VERSION = "1.0.0"
API_VERSION = "1.0"


def backend_version_payload() -> Dict[str, str]:
    """Return the single public health/version representation of this backend."""

    return {
        "status": "ok",
        "backend_version": BACKEND_VERSION,
        "api_version": API_VERSION,
    }
