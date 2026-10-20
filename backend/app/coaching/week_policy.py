"""
Week-level decisions of the constraint engine (see constraints.py).

Turns a TrainingState + Profile into the week's policy: training days
(with injury narrowing), race phase, 3:1 cycle position, fatigue veto,
volume target/ceiling and intensity budget. Every decision also produces
the human-readable rationale lines, in the order they are shown to the user.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..profile.models import Profile
from .constraint_schemas import CycleWeekType, Phase, TrainingState, WeeklyVolume

# --- Volume / cycle constants ------------------------------------------------
WEEKLY_CEILING_FACTOR = 1.10  # hard guardrail: ≤10% volume increase
DELOAD_TARGET_RATIO = 0.65  # deload volume = last complete week × this (0.6–0.7)
BUILD_STREAK_FOR_DELOAD = 3  # 3:1 cycle: 3 build weeks → next is deload
DELOAD_WEEK_RATIO = 0.72  # a week ≤72% of the previous one counts as a deload
MIN_WEEK_KM = 1.0  # below this a week counts as time off and resets the cycle

# --- Fatigue veto thresholds (PLAN.md safety guardrails) ---------------------
RHR_VETO_FRACTION = 0.10  # latest RHR >10% over 30-day median → no intensity
HRV_VETO_STATUSES = {"POOR", "LOW", "UNBALANCED"}
READINESS_VETO_LEVELS = {"LOW", "POOR"}

INTENSITY_BUDGET_FRACTION = 0.20  # 80/20 split

# Injuries that forbid back-to-back run days (case-insensitive substring).
RESTRICTIVE_INJURIES = ("achilles", "it band", "knee")

# Fallback training days when neither profile nor request provides any —
# plan_week's default Mon/Wed/Fri/Sat.
DEFAULT_DAYS = [0, 2, 4, 5]

# Race phase thresholds, in whole weeks from the target week's Monday to race
# day (race week itself = 0). Taper covers race week plus the two weeks
# before it; peak is the last hard block 3–4 weeks out; build 5–9; anything
# further out is base. A race already in the past maps to "recovery".
PHASE_TAPER_MAX_WEEKS = 2
PHASE_PEAK_MAX_WEEKS = 4
PHASE_BUILD_MAX_WEEKS = 9


@dataclass
class WeekPolicy:
    """Every week-level decision, plus the rationale lines that explain it."""

    days: list[date]
    injury_flags: list[str]
    phase: Phase | None
    weeks_to_race: int | None
    cycle: CycleWeekType
    fatigue_reasons: list[str]
    target_km: float
    ceiling_km: float
    budget_km: float
    easy_only: bool
    quality_allowed: bool
    rationale: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Training days & injury narrowing
# ---------------------------------------------------------------------------


def _allowed_weekdays(
    profile: Profile, days_override: list[int] | None
) -> tuple[list[int], list[str]]:
    """Request override > profile > plan_week default; sorted and deduped."""
    allowed = days_override if days_override else list(profile.preferred_days)
    notes = []
    if not allowed:
        allowed = DEFAULT_DAYS
        notes.append("No preferred days set; using default Mon/Wed/Fri/Sat.")
    return sorted(set(allowed)), notes


def _restrictive_injury_flags(profile: Profile) -> list[str]:
    return [
        entry
        for entry in (profile.injury_history or [])
        if any(key in entry.lower() for key in RESTRICTIVE_INJURIES)
    ]


def _drop_back_to_back_days(
    days: list[date], injury_flag: str
) -> tuple[list[date], list[str]]:
    """Injury narrowing: no back-to-back run days at all."""
    kept: list[date] = []
    notes = []
    for day in days:
        if kept and (day - kept[-1]).days == 1:
            notes.append(
                f"Injury flag '{injury_flag}': dropped {day:%A} to avoid "
                "back-to-back run days."
            )
            continue
        kept.append(day)
    return kept, notes


def _training_days(
    profile: Profile, week_monday: date, days_override: list[int] | None
) -> tuple[list[date], list[str], list[str]]:
    """(run dates, injury flags, rationale lines) for the target week."""
    allowed, notes = _allowed_weekdays(profile, days_override)
    injury_flags = _restrictive_injury_flags(profile)
    days = [week_monday + timedelta(days=d) for d in allowed]
    if not injury_flags:
        return days, injury_flags, notes
    days, dropped = _drop_back_to_back_days(days, injury_flags[0])
    return days, injury_flags, notes + dropped


# ---------------------------------------------------------------------------
# Phase & 3:1 cycle
# ---------------------------------------------------------------------------


def _phase(profile: Profile, week_monday: date) -> tuple[Phase | None, int | None]:
    """(phase, weeks_to_race). Health mode → (None, None): no periodization."""
    if profile.goal_mode != "race" or profile.goal_race_date is None:
        return None, None
    days = (profile.goal_race_date - week_monday).days
    if days < 0:
        return "recovery", None
    weeks = days // 7
    if weeks <= PHASE_TAPER_MAX_WEEKS:
        return "taper", weeks
    if weeks <= PHASE_PEAK_MAX_WEEKS:
        return "peak", weeks
    if weeks <= PHASE_BUILD_MAX_WEEKS:
        return "build", weeks
    return "base", weeks


def _phase_note(
    profile: Profile, phase: Phase | None, weeks_to_race: int | None
) -> str:
    if not phase:
        return "Health mode: no periodization, Z2-focused maintenance."
    return (
        f"Phase {phase}: {weeks_to_race} weeks to "
        f"{profile.goal_race_distance} on {profile.goal_race_date}."
    )


def _build_streak(volumes: list[WeeklyVolume]) -> int:
    """
    Consecutive build weeks ending at the most recent complete week.

    Walking backwards: a week counts as a build week unless it was itself a
    deload (≤ DELOAD_WEEK_RATIO of the previous week) or empty (< MIN_WEEK_KM,
    time off resets the cycle). Short/ambiguous history simply yields a short
    streak, and the caller defaults to a build week.
    """
    complete = [v for v in volumes if v.complete]
    streak = 0
    for i in range(len(complete) - 1, -1, -1):
        vol = complete[i].volume_km
        if vol < MIN_WEEK_KM:
            break
        prev = complete[i - 1].volume_km if i > 0 else None
        if prev is not None and prev >= MIN_WEEK_KM and vol <= DELOAD_WEEK_RATIO * prev:
            break  # most recent deload found; streak is what followed it
        streak += 1
    return streak


def _cycle_week(volumes: list[WeeklyVolume]) -> tuple[CycleWeekType, str]:
    """3:1 cycle position of the target week, plus its rationale line."""
    streak = _build_streak(volumes)
    if streak >= BUILD_STREAK_FOR_DELOAD:
        return "deload", (
            f"3:1 cycle: {streak} consecutive build weeks detected — "
            "this week is a deload (all easy)."
        )
    return "build", f"3:1 cycle: build week ({streak} into the current block)."


# ---------------------------------------------------------------------------
# Fatigue veto (PLAN.md: no intervals if RHR >10% over baseline, HRV secondary)
# ---------------------------------------------------------------------------


def _resting_hr_reason(state: TrainingState) -> str | None:
    latest, baseline = state.resting_hr_latest, state.resting_hr_baseline
    if latest is None or not baseline:
        return None
    if latest <= baseline * (1 + RHR_VETO_FRACTION):
        return None
    pct = round((latest / baseline - 1) * 100)
    return (
        f"Resting HR {latest} bpm is +{pct}% over the "
        f"30-day median ({baseline:.0f} bpm)"
    )


def _hrv_reason(state: TrainingState) -> str | None:
    if state.hrv_status and state.hrv_status.upper() in HRV_VETO_STATUSES:
        rmssd = f"{state.hrv_rmssd:.0f} ms" if state.hrv_rmssd is not None else "n/a"
        return f"HRV status {state.hrv_status} (RMSSD {rmssd})"
    if (
        state.hrv_rmssd is not None
        and state.hrv_baseline_lo is not None
        and state.hrv_rmssd < state.hrv_baseline_lo
    ):
        return (
            f"HRV {state.hrv_rmssd:.0f} ms below baseline floor "
            f"({state.hrv_baseline_lo:.0f} ms)"
        )
    return None


def _readiness_reason(state: TrainingState) -> str | None:
    level = state.readiness_level
    if not level or level.upper() not in READINESS_VETO_LEVELS:
        return None
    score = (
        f"{state.readiness_score}/100" if state.readiness_score is not None else "n/a"
    )
    return f"Training readiness {level} ({score})"


def fatigue_reasons(state: TrainingState) -> list[str]:
    """Every fatigue signal that vetoes intensity this week (empty = fresh).

    Example:
        >>> fatigue_reasons(state)
        ['HRV status LOW (RMSSD 38 ms)']
    """
    reasons = (_resting_hr_reason(state), _hrv_reason(state), _readiness_reason(state))
    return [r for r in reasons if r is not None]


# ---------------------------------------------------------------------------
# Volume target & intensity budget
# ---------------------------------------------------------------------------


def _adjusted_target(
    profile: Profile, state: TrainingState, cycle: CycleWeekType, avg: float
) -> float:
    """plan_week's status-based volume adjustment (before the hard ceiling)."""
    if cycle == "deload" and state.last_complete_week_km:
        return round(state.last_complete_week_km * DELOAD_TARGET_RATIO, 1)
    if profile.goal_mode != "race":
        return round(avg, 1)  # health mode: volume maintenance
    if (state.days_since_last_run or 0) >= 7 or state.training_status in (
        "DETRAINING",
        "RECOVERY",
    ):
        return round(avg * 0.85, 1)
    if state.training_status in ("PRODUCTIVE", "PEAKING"):
        return round(avg * 1.05, 1)
    return round(avg, 1)


def _volume_target(
    profile: Profile, state: TrainingState, cycle: CycleWeekType
) -> tuple[float, float, str]:
    """(target km, ceiling km, rationale line): adjustment + hard ceiling."""
    avg = state.avg_weekly_km or profile.current_weekly_volume_km or 0.0
    ceiling = round(avg * WEEKLY_CEILING_FACTOR, 2)
    target = round(min(_adjusted_target(profile, state, cycle, avg), ceiling), 1)
    note = (
        f"Volume target {target} km (recent avg {avg:.1f} km, "
        f"hard ceiling {ceiling} km = avg × {WEEKLY_CEILING_FACTOR})."
    )
    return target, ceiling, note


def _intensity_budget(target: float, easy_only: bool) -> tuple[float, str]:
    """80/20 budget; zero on deload or fatigue veto."""
    if easy_only:
        return 0.0, "Intensity budget 0 km — all sessions easy."
    budget = round(INTENSITY_BUDGET_FRACTION * target, 2)
    return budget, f"Intensity budget {budget} km (20% of target)."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _quality_allowed(profile: Profile, phase: Phase | None, easy_only: bool) -> bool:
    # Health mode is all-Z2 (no quality). In race mode quality is kept through
    # the taper (intensity retained while volume drops); only post-race
    # recovery drops it entirely.
    return not easy_only and profile.goal_mode == "race" and phase != "recovery"


def decide_week_policy(
    profile: Profile,
    state: TrainingState,
    week_monday: date,
    days_override: list[int] | None,
) -> WeekPolicy:
    """Make every week-level decision for the week starting ``week_monday``.

    Example:
        >>> policy = decide_week_policy(profile, state, date(2026, 6, 1), None)
        >>> policy.cycle, policy.target_km
        ('build', 30.0)
    """
    days, injury_flags, rationale = _training_days(profile, week_monday, days_override)
    phase, weeks_to_race = _phase(profile, week_monday)
    rationale.append(_phase_note(profile, phase, weeks_to_race))
    cycle, cycle_note = _cycle_week(state.weekly_volumes)
    rationale.append(cycle_note)
    reasons = fatigue_reasons(state)
    rationale.extend(f"Fatigue veto: {r} — intensity removed." for r in reasons)
    target, ceiling, volume_note = _volume_target(profile, state, cycle)
    easy_only = bool(reasons) or cycle == "deload"
    budget, budget_note = _intensity_budget(target, easy_only)
    rationale.extend([volume_note, budget_note])
    return WeekPolicy(
        days=days,
        injury_flags=injury_flags,
        phase=phase,
        weeks_to_race=weeks_to_race,
        cycle=cycle,
        fatigue_reasons=reasons,
        target_km=target,
        ceiling_km=ceiling,
        budget_km=budget,
        easy_only=easy_only,
        quality_allowed=_quality_allowed(profile, phase, easy_only),
        rationale=rationale,
    )
