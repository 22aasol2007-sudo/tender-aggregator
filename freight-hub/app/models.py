"""Re-export models from freight_core."""

import app._bootstrap  # noqa: F401

from freight_core.models import RawLoad

__all__ = ["RawLoad"]
