"""Unit tests for the pure zone calculators in app/coaching/zones.py."""

import pytest

from app.coaching.zones import (
    hr_zones_from_lthr,
    hr_zones_karvonen,
    intensity_budget_km,
    pace_zones,
    threshold_pace_from_race,
    weekly_ceiling_km,
)


def test_lthr_zones_ordered_and_sane():
    zones = hr_zones_from_lthr(185)
    assert [z.zone for z in zones] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    for z in zones:
        assert z.min_bpm < z.max_bpm
    # Strictly increasing bounds, and Z4 must contain the LTHR itself (95–99%).
    mins = [z.min_bpm for z in zones]
    assert mins == sorted(mins)
    assert zones[3].min_bpm <= 185 <= zones[3].max_bpm + 2
    # Spot-check Friel percentages: Z2 = 85–89% of 185.
    assert zones[1].min_bpm == round(185 * 0.85)
    assert zones[1].max_bpm == round(185 * 0.89)


def test_lthr_z5_capped_by_max_hr():
    zones = hr_zones_from_lthr(185, max_hr=192)
    assert zones[4].max_bpm == 192
    # Without max_hr, Z5 tops out at 106% of LTHR.
    assert hr_zones_from_lthr(185)[4].max_bpm == round(185 * 1.06)


def test_karvonen_fallback():
    zones = hr_zones_karvonen(max_hr=190, resting_hr=47)
    assert [z.zone for z in zones] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    reserve = 190 - 47
    # Z1 = 50–60% of HRR above resting.
    assert zones[0].min_bpm == round(47 + 0.50 * reserve)
    assert zones[0].max_bpm == round(47 + 0.60 * reserve)
    # Z5 reaches max HR.
    assert zones[4].max_bpm == 190
    mins = [z.min_bpm for z in zones]
    assert mins == sorted(mins)
    for z in zones:
        assert z.min_bpm < z.max_bpm


def test_threshold_pace_from_5k_race():
    # 17:43 5K (1063 s) → race pace 212.6 s/km (3:33/km).
    pace = threshold_pace_from_race(5.0, 1063)
    # Threshold pace must be slower than race pace but clearly faster than easy.
    assert 213 < pace < 280


def test_threshold_pace_longer_race_slower_estimate():
    # A longer race at the same fitness implies a similar threshold pace
    # (Riegel consistency): 17:43 5K ≈ 2:49 marathon.
    from_5k = threshold_pace_from_race(5.0, 1063)
    from_marathon = threshold_pace_from_race(42.195, 10162)
    assert abs(from_5k - from_marathon) <= 3


def test_pace_zones_straddle_threshold():
    zones = {z.name: z for z in pace_zones(228)}  # 3:48/km threshold
    assert set(zones) == {"easy", "marathon", "threshold", "interval", "repetition"}
    # Threshold zone brackets the input pace.
    assert zones["threshold"].min_sec_per_km <= 228 <= zones["threshold"].max_sec_per_km
    # Ordered by speed: repetition fastest … easy slowest.
    ordered = ["repetition", "interval", "threshold", "marathon", "easy"]
    for faster, slower in zip(ordered, ordered[1:]):
        assert zones[faster].max_sec_per_km < zones[slower].min_sec_per_km
    for z in zones.values():
        assert z.min_sec_per_km < z.max_sec_per_km


def test_weekly_ceiling_is_110_percent():
    assert weekly_ceiling_km(40.0) == pytest.approx(44.0)


def test_intensity_budget_is_20_percent():
    assert intensity_budget_km(40.0) == pytest.approx(8.0)
