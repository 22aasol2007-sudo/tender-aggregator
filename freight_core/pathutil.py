"""Ensure repo-root freight_core is importable when running hub/bot as scripts."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_freight_core_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root
