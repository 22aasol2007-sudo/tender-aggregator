"""Re-export shared defaults from freight_core."""

import app._bootstrap  # noqa: F401

from freight_core.defaults import (
    DEFAULT_CHATS,
    DRIVER_OFFER_KEYWORDS,
    EXCLUDE_KEYWORDS,
    INCLUDE_KEYWORDS,
    PRESETS,
    PUBLIC_TG_CHANNELS,
)

__all__ = [
    "DEFAULT_CHATS",
    "DRIVER_OFFER_KEYWORDS",
    "EXCLUDE_KEYWORDS",
    "INCLUDE_KEYWORDS",
    "PRESETS",
    "PUBLIC_TG_CHANNELS",
]
