"""
Zone and load calculators — pure functions, no DB access.

Schemes used (documented for future tuning):

- HR zones from lactate-threshold HR (LTHR): Friel running zones as % of LTHR —
  Z1 <85% (min reported as 0 = "no floor"), Z2 85–89%, Z3 90–94%,
  Z4 95–99%, Z5 100%+ (capped at max_hr when known, else 106% of LTHR).
- HR fallback without LTHR: Karvonen / heart-rate reserve (HRR) —
  zone bound = resting_hr + pct * (max_hr - resting_hr) with the classic
  5-zone splits 50–60 / 60–70 / 70–80 / 80–90 / 90–100% of HRR.
- Pace zones: multipliers of threshold (≈1-hour race) pace, Daniels-style —
  easy ×1.25–1.40, marathon ×1.06–1.12, threshold ×0.98–1.02,
  interval ×0.90–0.95, repetition ×0.83–0.88.
- Race result → threshold pace: Riegel (exponent 1.06) to a 10K-equivalent
  time, then +3% to step down from ~40-min race pace to ~1-hour threshold pace.
- Intensity budget: 80/20 is classically time-based; we approximate it as
  20% of weekly *distance* because easy-pace variation is small for a single
  athlete, and distance is what the plan generator allocates.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HrZone:
    zone: str  # "Z1".."Z5"
    min_bpm: int
    max_bpm: int


@dataclass(frozen=True)
class PaceZone:
    name: str  # easy | marathon | threshold | interval | repetition
    min_sec_per_km: int  # faster bound
    max_sec_per_km: int  # slower bound


# Friel running HR zones, % of LTHR: (zone, lo, hi). Z1 has no lower bound,
# Z5 no upper bound — handled below.
_LTHR_ZONES = [
    ("Z1", None, 0.85),
    ("Z2", 0.85, 0.89),
    ("Z3", 0.90, 0.94),
    ("Z4", 0.95, 0.99),
    ("Z5", 1.00, None),
]

# Karvonen / HRR 5-zone splits, fraction of (max_hr - resting_hr).
_HRR_ZONES = [
    ("Z1", 0.50, 0.60),
    ("Z2", 0.60, 0.70),
    ("Z3", 0.70, 0.80),
    ("Z4", 0.80, 0.90),
    ("Z5", 0.90, 1.00),
]

# Daniels-style pace zones as multipliers of threshold pace (sec/km).
_PACE_ZONES = [
    ("easy", 1.25, 1.40),
    ("marathon", 1.06, 1.12),
    ("threshold", 0.98, 1.02),
    ("interval", 0.90, 0.95),
    ("repetition", 0.83, 0.88),
]

RIEGEL_EXPONENT = 1.06
WEEKLY_CEILING_FACTOR = 1.10  # hard guardrail: ≤10% volume increase
INTENSITY_BUDGET_FRACTION = 0.20  # 80/20 split


def hr_zones_from_lthr(lthr: int, max_hr: int | None = None) -> list[HrZone]:
    """Friel running zones as % of lactate-threshold HR."""
    z5_max = max_hr if max_hr is not None and max_hr > lthr else round(lthr * 1.06)
    zones = []
    for name, lo, hi in _LTHR_ZONES:
        zones.append(
            HrZone(
                zone=name,
                min_bpm=round(lthr * lo) if lo is not None else 0,
                max_bpm=round(lthr * hi) if hi is not None else z5_max,
            )
        )
    return zones


def hr_zones_karvonen(max_hr: int, resting_hr: int) -> list[HrZone]:
    """Fallback zones from heart-rate reserve when LTHR is unknown."""
    reserve = max_hr - resting_hr
    return [
        HrZone(zone=name, min_bpm=round(resting_hr + lo * reserve),
               max_bpm=round(resting_hr + hi * reserve))
        for name, lo, hi in _HRR_ZONES
    ]


def threshold_pace_from_race(distance_km: float, time_sec: int) -> int:
    """
    Estimate threshold (≈1-hour race) pace in sec/km from a race result.

    Riegel to a 10K-equivalent time, then +3% from ~10K race pace to
    threshold pace. E.g. 17:43 5K → ~228 s/km (3:48/km).
    """
    t10k_sec = time_sec * (10.0 / distance_km) ** RIEGEL_EXPONENT
    return round(t10k_sec / 10.0 * 1.03)


def pace_zones(threshold_pace_sec_per_km: int) -> list[PaceZone]:
    """Daniels-style pace zones from threshold pace (sec/km)."""
    return [
        PaceZone(name=name, min_sec_per_km=round(threshold_pace_sec_per_km * lo),
                 max_sec_per_km=round(threshold_pace_sec_per_km * hi))
        for name, lo, hi in _PACE_ZONES
    ]


def weekly_ceiling_km(current_weekly_volume_km: float) -> float:
    """Hard guardrail: next week may not exceed current volume +10%."""
    return round(current_weekly_volume_km * WEEKLY_CEILING_FACTOR, 2)


def intensity_budget_km(current_weekly_volume_km: float) -> float:
    """80/20 rule: 20% of weekly volume may be moderate/hard (see module docstring)."""
    return round(current_weekly_volume_km * INTENSITY_BUDGET_FRACTION, 2)


def compute_zones(profile) -> dict:
    """
    Compute everything the /zones endpoint returns from a Profile ORM row
    (used as a plain data holder — no DB access here).
    """
    if profile.threshold_hr:
        hr = hr_zones_from_lthr(profile.threshold_hr, profile.max_hr)
        hr_source = "lthr"
    elif profile.max_hr and profile.resting_hr:
        hr = hr_zones_karvonen(profile.max_hr, profile.resting_hr)
        hr_source = "karvonen"
    else:
        hr, hr_source = None, None

    if profile.threshold_pace_sec_per_km:
        t_pace, pace_source = profile.threshold_pace_sec_per_km, "profile"
    elif profile.recent_race_distance_km and profile.recent_race_time_sec:
        t_pace = threshold_pace_from_race(
            profile.recent_race_distance_km, profile.recent_race_time_sec
        )
        pace_source = "race_estimate"
    else:
        t_pace, pace_source = None, None

    volume = profile.current_weekly_volume_km
    return {
        "hr_zones": hr,
        "hr_source": hr_source,
        "pace_zones": pace_zones(t_pace) if t_pace else None,
        "threshold_pace_sec_per_km": t_pace,
        "threshold_pace_source": pace_source,
        "weekly_ceiling_km": weekly_ceiling_km(volume) if volume else None,
        "intensity_budget_km": intensity_budget_km(volume) if volume else None,
    }
