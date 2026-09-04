from __future__ import annotations

import math
from types import SimpleNamespace

from backend.razorpay_checkout import _advance_arrival_clock
from backend.supabase_store import _finite_or_none


def test_arrival_clock_strictly_advances_when_simulation_is_ahead() -> None:
    engine = SimpleNamespace(clock=2_000.0)

    first = _advance_arrival_clock(engine, now=1_000.0)
    second = _advance_arrival_clock(engine, now=1_000.0)

    assert first > 2_000.0
    assert second > first


def test_arrival_clock_prefers_real_time_when_wall_clock_is_ahead() -> None:
    engine = SimpleNamespace(clock=1_000.0)

    assigned = _advance_arrival_clock(engine, now=2_000.0)

    assert assigned == 2_000.0


def test_non_finite_operational_scores_become_null() -> None:
    assert _finite_or_none(float("nan")) is None
    assert _finite_or_none(float("inf")) is None
    assert _finite_or_none(float("-inf")) is None
    assert _finite_or_none(None) is None
    assert _finite_or_none("not-a-number") is None
    assert math.isclose(_finite_or_none("0.42") or 0.0, 0.42)
