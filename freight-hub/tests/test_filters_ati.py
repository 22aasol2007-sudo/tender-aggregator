"""Tests for ATI-adapted feed filters."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from app.filters_ati import (
    append_ati_filters,
    clamp_tonnage_band,
    freshness_cutoff,
    load_date_window,
)


def test_clamp_tonnage_respects_hard_band():
    lo, hi = clamp_tonnage_band(1, 20, hard_min=5, hard_max=12)
    assert lo == 5 and hi == 12
    lo, hi = clamp_tonnage_band(6, 10, hard_min=5, hard_max=12)
    assert lo == 6 and hi == 10


def test_freshness_cutoff():
    now = 1_000_000.0
    assert freshness_cutoff(None, now=now) is None
    assert freshness_cutoff(3, now=now) == now - 3 * 3600


def test_load_date_window_today():
    # 2026-08-13 15:00
    now = 1786633200.0
    d0, d1 = load_date_window("today", now=now)
    assert d0 is not None and d1 is not None
    assert d1 - d0 == 86400


def test_append_ppk_and_loading_filters():
    sql: list[str] = ["SELECT * FROM loads WHERE 1=1"]
    args: list = []
    append_ati_filters(
        sql,
        args,
        tonnage_min=5,
        tonnage_max=12,
        ppk_min=80,
        loading="rear",
        cargo_mode="ltl",
        hard_tonnage_min=5,
        hard_tonnage_max=12,
    )
    joined = " ".join(sql)
    assert "price_per_km" in joined
    assert "задн" in " ".join(str(a) for a in args) or any("задн" in str(a) for a in args)
    assert any("догруз" in str(a) for a in args)
    assert args[0] == 5 and args[1] == 12
    assert 80 in args


def test_exact_city_filter():
    sql: list[str] = ["SELECT * FROM loads WHERE 1=1"]
    args: list = []
    append_ati_filters(
        sql,
        args,
        exact_from=True,
        from_city="Видное",
        hard_tonnage_min=5,
        hard_tonnage_max=12,
    )
    assert "LOWER(COALESCE(from_city,'')) = ?" in " ".join(sql)
    assert "видное" in args
