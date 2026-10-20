"""
Session skeleton — port of temp/utils.py::_build_sessions slot map.

Assigns a role to every training day, keeps hard days apart, splits the
weekly volume across the days and attaches per-slot HR/pace ranges sourced
from zones.py (see constraints.py for the full engine).
"""

from dataclasses import dataclass
from datetime import date
from typing import cast

from .constraint_schemas import SessionSlot, SessionType
from .week_policy import WeekPolicy
from .zones import HrZone, PaceZone

# --- Session allocation ------------------------------------------------------
LONG_RUN_FRACTION = 0.27  # ≤ LONG_RUN_CAP_FRACTION after the +10% hi bound
LONG_RUN_CAP_FRACTION = 0.30  # PLAN.md: long run ≤30% of weekly volume
QUALITY_FRACTION = 0.25
MAX_QUALITY_SESSIONS = 2
SLOT_RANGE_FRACTION = 0.10  # per-slot distance range ±10%

_HARD_TYPES = {"quality", "long"}  # for back-to-back spacing

# type → (lo HR zone, hi HR zone, pace zone). Ranges come from zones.py.
_TYPE_ZONES: dict[str, tuple[str, str, str]] = {
    "recovery": ("Z1", "Z1", "easy"),
    "aerobic": ("Z1", "Z2", "easy"),
    "long": ("Z2", "Z3", "marathon"),
    "quality": ("Z3", "Z4", "threshold"),
}
_EASY_ZONES = ("Z1", "Z2", "easy")  # deload / fatigue veto: everything easy

_TYPE_RATIONALES = {
    "aerobic": "Aerobic base. Fully conversational, HR is the ceiling not pace.",
    "quality": "Quality session — the week's main intensity stimulus.",
    "recovery": "Recovery flush. Truly easy; its only job is prep for the next hard day.",
    "long": "Aerobic capstone of the week. Steady even effort, no surges.",
}


@dataclass(frozen=True)
class _SlotZones:
    """Zone lookups + week-wide flags shared by every slot of one week."""

    hr_zones: dict[str, HrZone]
    pace_zones: dict[str, PaceZone]
    easy_only: bool
    long_cap_km: float


def _session_roles(n: int, quality_allowed: bool) -> list[SessionType]:
    """plan_week's roles_map, extended: 5+ days add a second quality + easy days."""
    if n <= 1:
        roles = ["long"]
    elif n == 2:
        roles = ["quality", "long"]
    elif n == 3:
        roles = ["quality", "recovery", "long"]
    elif n == 4:
        roles = ["aerobic", "quality", "recovery", "long"]
    else:
        roles = (
            ["aerobic", "quality", "recovery"]
            + ["aerobic"] * (n - 5)
            + [
                "quality",
                "long",
            ]
        )
    if not quality_allowed:
        roles = ["aerobic" if r == "quality" else r for r in roles]
    return cast(list[SessionType], roles)


def _enforce_hard_spacing(roles: list[SessionType], days: list[date]) -> list[str]:
    """No back-to-back hard days; on conflict the quality session goes easy."""
    notes = []
    for i in range(1, len(roles)):
        adjacent = (days[i] - days[i - 1]).days == 1
        if not (adjacent and roles[i] in _HARD_TYPES and roles[i - 1] in _HARD_TYPES):
            continue
        if roles[i - 1] == "quality":
            roles[i - 1] = "aerobic"
            notes.append(
                f"{days[i - 1]:%a} quality → aerobic: would be back-to-back "
                f"with the {days[i]:%a} {roles[i]}"
            )
        else:
            roles[i] = "aerobic"
            notes.append(
                f"{days[i]:%a} quality → aerobic: would be back-to-back "
                f"with the {days[i - 1]:%a} {roles[i - 1]}"
            )
    return notes


def _assign_role_distance(
    distances: list[float], roles: list[SessionType], role: str, km: float
) -> None:
    for i, r in enumerate(roles):
        if r == role:
            distances[i] = km


def _allocate_distances(
    target_km: float, roles: list[SessionType], budget_km: float
) -> list[float]:
    """Split the weekly target across slots (long ≤30%, quality within budget)."""
    distances = [0.0] * len(roles)
    if target_km <= 0:
        return distances
    _assign_role_distance(
        distances, roles, "long", round(LONG_RUN_FRACTION * target_km, 1)
    )
    n_quality = roles.count("quality")
    if n_quality:
        each = min(
            round(QUALITY_FRACTION * target_km, 1), round(budget_km / n_quality, 1)
        )
        _assign_role_distance(distances, roles, "quality", each)
    easy_idx = [i for i, r in enumerate(roles) if r in ("aerobic", "recovery")]
    if easy_idx:
        each = round((target_km - sum(distances)) / len(easy_idx), 1)
        for i in easy_idx:
            distances[i] = max(each, 0.0)
    return distances


def _slot_zones(zone_data: dict, easy_only: bool, target_km: float) -> _SlotZones:
    hr = zone_data["hr_zones"]
    pace = zone_data["pace_zones"]
    return _SlotZones(
        hr_zones={z.zone: z for z in hr} if hr else {},
        pace_zones={z.name: z for z in pace} if pace else {},
        easy_only=easy_only,
        long_cap_km=round(LONG_RUN_CAP_FRACTION * target_km, 1),
    )


def _distance_range(
    dist: float, role: SessionType, long_cap_km: float
) -> tuple[float, float]:
    lo = round(dist * (1 - SLOT_RANGE_FRACTION), 1)
    hi = round(dist * (1 + SLOT_RANGE_FRACTION), 1)
    if role == "long":
        hi = min(hi, long_cap_km)
    return lo, hi


def _slot_rationale(role: SessionType, easy_only: bool) -> str:
    rationale = _TYPE_RATIONALES[role]
    if easy_only and role in ("quality", "long"):
        rationale += " Capped at Z1-Z2 this week."
    return rationale


def _build_slot(
    day: date, role: SessionType, dist: float, zones: _SlotZones
) -> SessionSlot:
    lo_zone, hi_zone, pace_name = _EASY_ZONES if zones.easy_only else _TYPE_ZONES[role]
    hr_lo = zones.hr_zones[lo_zone].min_bpm if lo_zone in zones.hr_zones else None
    hr_hi = zones.hr_zones[hi_zone].max_bpm if hi_zone in zones.hr_zones else None
    pace = zones.pace_zones.get(pace_name)
    lo, hi = _distance_range(dist, role, zones.long_cap_km)
    return SessionSlot(
        date=day,
        weekday=day.weekday(),
        type=role,
        distance_km_lo=lo,
        distance_km_hi=hi,
        hr_zone_range=f"{lo_zone}-{hi_zone}",
        hr_bpm_lo=hr_lo,
        hr_bpm_hi=hr_hi,
        pace_zone=pace.name if pace else None,
        pace_lo_sec_per_km=pace.min_sec_per_km if pace else None,
        pace_hi_sec_per_km=pace.max_sec_per_km if pace else None,
        rationale=_slot_rationale(role, zones.easy_only),
    )


def _build_slots(
    days: list[date],
    roles: list[SessionType],
    distances: list[float],
    zone_data: dict,
    easy_only: bool,
    target_km: float,
) -> list[SessionSlot]:
    zones = _slot_zones(zone_data, easy_only, target_km)
    return [
        _build_slot(day, role, dist, zones)
        for day, role, dist in zip(days, roles, distances)
    ]


def plan_session_slots(
    policy: WeekPolicy, zone_data: dict
) -> tuple[list[SessionSlot], list[str]]:
    """Per-day skeleton for the week, plus hard-spacing rationale lines.

    ``zone_data`` is the dict returned by ``zones.compute_zones``.

    Example:
        >>> slots, notes = plan_session_slots(policy, compute_zones(profile))
        >>> [s.type for s in slots]
        ['aerobic', 'quality', 'recovery', 'long']
    """
    roles = _session_roles(len(policy.days), policy.quality_allowed)
    spacing_notes = _enforce_hard_spacing(roles, policy.days)
    distances = _allocate_distances(policy.target_km, roles, policy.budget_km)
    sessions = _build_slots(
        policy.days, roles, distances, zone_data, policy.easy_only, policy.target_km
    )
    return sessions, spacing_notes
