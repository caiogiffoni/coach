"""
Constraint engine — ported state computation of temp/utils.py::plan_week.

Given the athlete profile, the imported Garmin data and a target week, compute
the hard constraints the LLM plan generator must obey (PLAN.md build-order
step 4, "never let the LLM freestyle"). Pure-ish module: takes a DB session +
plain inputs and returns Pydantic models. No HTTP here (see router.py).

What was ported from plan_week / _current_state / _build_sessions, and what
changed:

- Weekly volumes, ACWR, readiness, HRV, sleep averages, days-since-run: ported
  almost verbatim, but read from the SQLAlchemy store instead of the pandas
  loaders, and every recency window anchors to the latest date in the data
  (same convention as profile/seed.py), never to wall-clock.
- Volume target: same status-based adjustment (DETRAINING/long gap ×0.85,
  PRODUCTIVE/PEAKING ×1.05), now additionally capped by the zones.py ceiling
  (recent avg × 1.10) — plan_week had no hard cap.
- Session roles: same slot map (easy/quality/flush/long), renamed to the
  validator vocabulary (aerobic/quality/recovery/long). plan_week's 38%
  long-run share is reduced to ≤30% of weekly volume per PLAN.md guardrails.
- New on top of plan_week: race-phase periodization, 3:1 cycle detection,
  fatigue veto (RHR / HRV / readiness), injury-driven day narrowing, and
  per-slot HR/pace ranges sourced from zones.py instead of ad-hoc bpm strings.
"""

from datetime import date

from sqlalchemy.orm import Session

from ..profile.models import Profile
from .constraint_schemas import (
    CycleWeekType,
    Phase,
    SessionSlot,
    SessionType,
    TrainingState,
    WeekConstraints,
    WeeklyVolume,
)
from .slots import (
    LONG_RUN_CAP_FRACTION,
    LONG_RUN_FRACTION,
    MAX_QUALITY_SESSIONS,
    QUALITY_FRACTION,
    SLOT_RANGE_FRACTION,
    plan_session_slots,
)
from .training_state import (
    HARD_AEROBIC_TE,
    HARD_ANAEROBIC_TE,
    HARD_HR_LTHR_FRACTION,
    HARD_LOOKBACK_DAYS,
    RHR_BASELINE_DAYS,
    SLEEP_LOOKBACK_NIGHTS,
    VOLUME_WINDOW_WEEKS,
    compute_training_state,
    iso_monday,
)
from .week_policy import (
    BUILD_STREAK_FOR_DELOAD,
    DEFAULT_DAYS,
    DELOAD_TARGET_RATIO,
    DELOAD_WEEK_RATIO,
    HRV_VETO_STATUSES,
    INTENSITY_BUDGET_FRACTION,
    MIN_WEEK_KM,
    PHASE_BUILD_MAX_WEEKS,
    PHASE_PEAK_MAX_WEEKS,
    PHASE_TAPER_MAX_WEEKS,
    READINESS_VETO_LEVELS,
    RESTRICTIVE_INJURIES,
    RHR_VETO_FRACTION,
    WEEKLY_CEILING_FACTOR,
    WeekPolicy,
    decide_week_policy,
)
from .zones import compute_zones

# Re-exported so existing `from app.coaching.constraints import X` keeps
# working after the split into constraint_schemas / training_state /
# week_policy / slots.
__all__ = [
    "BUILD_STREAK_FOR_DELOAD",
    "DEFAULT_DAYS",
    "DELOAD_TARGET_RATIO",
    "DELOAD_WEEK_RATIO",
    "HARD_AEROBIC_TE",
    "HARD_ANAEROBIC_TE",
    "HARD_HR_LTHR_FRACTION",
    "HARD_LOOKBACK_DAYS",
    "HRV_VETO_STATUSES",
    "INTENSITY_BUDGET_FRACTION",
    "LONG_RUN_CAP_FRACTION",
    "LONG_RUN_FRACTION",
    "MAX_QUALITY_SESSIONS",
    "MIN_WEEK_KM",
    "PHASE_BUILD_MAX_WEEKS",
    "PHASE_PEAK_MAX_WEEKS",
    "PHASE_TAPER_MAX_WEEKS",
    "QUALITY_FRACTION",
    "READINESS_VETO_LEVELS",
    "RESTRICTIVE_INJURIES",
    "RHR_BASELINE_DAYS",
    "RHR_VETO_FRACTION",
    "SLEEP_LOOKBACK_NIGHTS",
    "SLOT_RANGE_FRACTION",
    "VOLUME_WINDOW_WEEKS",
    "WEEKLY_CEILING_FACTOR",
    "CycleWeekType",
    "Phase",
    "SessionSlot",
    "SessionType",
    "TrainingState",
    "WeekConstraints",
    "WeeklyVolume",
    "compute_constraints",
]


def _assemble_constraints(
    week_monday: date,
    profile: Profile,
    state: TrainingState,
    policy: WeekPolicy,
    sessions: list[SessionSlot],
) -> WeekConstraints:
    return WeekConstraints(
        week_start=week_monday,
        goal_mode=profile.goal_mode,
        phase=policy.phase,
        weeks_to_race=policy.weeks_to_race,
        cycle_week_type=policy.cycle,
        weekly_volume_target_km=policy.target_km,
        weekly_volume_ceiling_km=policy.ceiling_km,
        intensity_budget_km=policy.budget_km,
        allowed_days=[d.weekday() for d in policy.days],
        fatigue_veto=bool(policy.fatigue_reasons),
        fatigue_reasons=policy.fatigue_reasons,
        injury_flags=policy.injury_flags,
        sessions=sessions,
        state=state,
        rationale=policy.rationale,
    )


def compute_constraints(
    db: Session,
    profile: Profile,
    week: date,
    days_override: list[int] | None = None,
) -> WeekConstraints:
    """
    Compute the hard constraints for the week containing `week`.

    `week` may be any date (normalized to its Monday) and may lie in the
    future relative to the data: state windows always anchor to the latest
    imported data, while phase and slot dates follow the target week.

    Example:
        >>> c = compute_constraints(db, profile, date(2026, 6, 3), [0, 2, 5])
        >>> c.week_start, c.allowed_days
        (datetime.date(2026, 6, 1), [0, 2, 5])
    """
    week_monday = iso_monday(week)
    state = compute_training_state(db, profile)
    policy = decide_week_policy(profile, state, week_monday, days_override)
    sessions, spacing_notes = plan_session_slots(policy, compute_zones(profile))
    policy.rationale.extend(spacing_notes)
    return _assemble_constraints(week_monday, profile, state, policy, sessions)
