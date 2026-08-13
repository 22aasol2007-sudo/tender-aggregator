"""Re-export score from freight_core."""

import app._bootstrap  # noqa: F401

from freight_core.score import (
    ScoreResult,
    format_card_html,
    format_full_html,
    score_load,
)

__all__ = [
    "ScoreResult",
    "format_card_html",
    "format_full_html",
    "score_load",
]
