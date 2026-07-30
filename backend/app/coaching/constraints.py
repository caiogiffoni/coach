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

from datetime import date, timedelta
from statistics import median
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ingestion.models import (
    Activity,
    DailyWellness,
    Hrv,
    Sleep,
    TrainingHistory,
    TrainingLoad,
    TrainingReadiness,
)
from ..profile.models import Profile
from ..profile.seed import RUN_TYPES
from .zones import compute_zones

SessionType = Literal["aerobic", "quality", "recovery", "long"]
CycleWeekType = Literal["build", "deload"]
Phase = Literal["base", "build", "peak", "taper", "recovery"]

# --- Volume / cycle constants ------------------------------------------------
VOLUME_WINDOW_WEEKS = 8  # recent-volume window, same as seed.py
WEEKLY_CEILING_FACTOR = 1.10  # hard guardrail: ≤10% volume increase
DELOAD_TARGET_RATIO = 0.65  # deload volume = last complete week × this (0.6–0.7)
BUILD_STREAK_FOR_DELOAD = 3  # 3:1 cycle: 3 build weeks → next is deload
DELOAD_WEEK_RATIO = 0.72  # a week ≤72% of the previous one counts as a deload
MIN_WEEK_KM = 1.0  # below this a week counts as time off and resets the cycle

# --- Fatigue veto thresholds (PLAN.md safety guardrails) ---------------------
RHR_BASELINE_DAYS = 30
RHR_VETO_FRACTION = 0.10  # latest RHR >10% over 30-day median → no intensity
HRV_VETO_STATUSES = {"POOR", "LOW", "UNBALANCED"}
READINESS_VETO_LEVELS = {"LOW", "POOR"}
SLEEP_LOOKBACK_NIGHTS = 7

# --- Hard-session classification (ported plan_week avg-HR/TE approach) -------
HARD_AEROBIC_TE = 3.5
HARD_ANAEROBIC_TE = 1.5
HARD_HR_LTHR_FRACTION = 0.90  # avg HR ≥90% of LTHR ≈ Z3+ in zones.py terms
HARD_LOOKBACK_DAYS = 60

# --- Session allocation ------------------------------------------------------
LONG_RUN_FRACTION = 0.27  # ≤ LONG_RUN_CAP_FRACTION after the +10% hi bound
LONG_RUN_CAP_FRACTION = 0.30  # PLAN.md: long run ≤30% of weekly volume
QUALITY_FRACTION = 0.25
INTENSITY_BUDGET_FRACTION = 0.20  # 80/20 split
MAX_QUALITY_SESSIONS = 2
SLOT_RANGE_FRACTION = 0.10  # per-slot distance range ±10%

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


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


class WeeklyVolume(BaseModel):
    week_start: date  # Monday of the ISO week
    volume_km: float
    complete: bool  # Sunday of the week is within data coverage


class TrainingState(BaseModel):
    """Snapshot of every metric that drives the constraint decisions."""

    as_of: date | None  # latest date present in the imported data
    weekly_volumes: list[WeeklyVolume]
    avg_weekly_km: float
    last_complete_week_km: float | None
    days_since_last_run: int | None
    days_since_last_hard: int | None
    training_status: str | None  # PRODUCTIVE / MAINTAINING / RECOVERY / …
    acwr: float | None
    acwr_status: str | None
    acute_load: int | None
    chronic_load: int | None
    readiness_score: int | None
    readiness_level: str | None
    hrv_rmssd: float | None
    hrv_status: str | None
    hrv_baseline_lo: float | None
    hrv_baseline_hi: float | None
    resting_hr_latest: int | None
    resting_hr_baseline: float | None  # 30-day median
    sleep_avg_hours_7d: float | None
    sleep_avg_score_7d: float | None


class SessionSlot(BaseModel):
    date: date
    weekday: int  # 0=Mon..6=Sun
    type: SessionType
    distance_km_lo: float
    distance_km_hi: float
    hr_zone_range: str  # e.g. "Z1-Z2"
    hr_bpm_lo: int | None
    hr_bpm_hi: int | None
    pace_zone: str | None  # easy | marathon | threshold | …
    pace_lo_sec_per_km: int | None  # faster bound
    pace_hi_sec_per_km: int | None  # slower bound
    rationale: str


class WeekConstraints(BaseModel):
    """The structure the LLM generator consumes."""

    week_start: date  # Monday of the target week
    goal_mode: str
    phase: Phase | None  # None in health mode (no periodization)
    weeks_to_race: int | None
    cycle_week_type: CycleWeekType
    weekly_volume_target_km: float
    weekly_volume_ceiling_km: float
    intensity_budget_km: float
    allowed_days: list[int]  # weekday ints, 0=Mon
    fatigue_veto: bool
    fatigue_reasons: list[str]
    injury_flags: list[str]  # injury entries matched as restrictive
    sessions: list[SessionSlot]
    state: TrainingState
    rationale: list[str]


# ---------------------------------------------------------------------------
# Training state (port of temp/utils.py::_current_state)
# ---------------------------------------------------------------------------


def _iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _latest_data_date(db: Session) -> date | None:
    """Most recent date across every table the engine reads."""
    candidates: list[date] = []
    latest_run = db.scalar(
        select(func.max(Activity.start_time_local)).where(
            Activity.activity_type.in_(RUN_TYPES)
        )
    )
    if latest_run is not None:
        candidates.append(latest_run.date())
    for model in (DailyWellness, Sleep, Hrv, TrainingLoad, TrainingReadiness):
        latest = db.scalar(select(func.max(model.calendar_date)))
        if latest is not None:
            candidates.append(latest)
    return max(candidates) if candidates else None


def _weekly_volumes(
    db: Session, anchor: date, weeks: int = VOLUME_WINDOW_WEEKS
) -> list[WeeklyVolume]:
    """Running km per ISO week for the `weeks` weeks ending at `anchor`."""
    first_monday = _iso_monday(anchor) - timedelta(weeks=weeks - 1)
    runs = db.scalars(
        select(Activity).where(
            Activity.activity_type.in_(RUN_TYPES),
            Activity.start_time_local >= first_monday,
            Activity.distance_km > 0,
        )
    )
    by_monday: dict[date, float] = {}
    for run in runs:
        monday = _iso_monday(run.start_time_local.date())
        by_monday[monday] = by_monday.get(monday, 0.0) + run.distance_km
    return [
        WeeklyVolume(
            week_start=first_monday + timedelta(weeks=i),
            volume_km=round(by_monday.get(first_monday + timedelta(weeks=i), 0.0), 2),
            # A week is complete once its Sunday is within data coverage.
            complete=(first_monday + timedelta(weeks=i) + timedelta(days=6)) <= anchor,
        )
        for i in range(weeks)
    ]


def _is_hard_run(run: Activity, threshold_hr: int | None) -> bool:
    """plan_week-style classification: training effect first, avg HR vs LTHR."""
    if run.aerobic_training_effect and run.aerobic_training_effect >= HARD_AEROBIC_TE:
        return True
    if (
        run.anaerobic_training_effect
        and run.anaerobic_training_effect >= HARD_ANAEROBIC_TE
    ):
        return True
    if (
        run.avg_hr
        and threshold_hr
        and run.avg_hr >= HARD_HR_LTHR_FRACTION * threshold_hr
    ):
        return True
    return False


def _training_state(db: Session, profile: Profile) -> TrainingState:
    as_of = _latest_data_date(db)

    # Volumes anchor to the latest run; all other signals anchor to as_of.
    latest_run_dt = db.scalar(
        select(func.max(Activity.start_time_local)).where(
            Activity.activity_type.in_(RUN_TYPES)
        )
    )
    last_run_date = latest_run_dt.date() if latest_run_dt else None
    volumes = _weekly_volumes(db, last_run_date) if last_run_date else []
    run_weeks = [v.volume_km for v in volumes if v.volume_km > 0]
    avg_weekly_km = round(sum(run_weeks) / len(run_weeks), 2) if run_weeks else 0.0
    complete = [v for v in volumes if v.complete]
    last_complete_week_km = complete[-1].volume_km if complete else None

    days_since_last_run = (
        (as_of - last_run_date).days if (as_of and last_run_date) else None
    )

    days_since_last_hard = None
    if as_of and last_run_date:
        cutoff = last_run_date - timedelta(days=HARD_LOOKBACK_DAYS)
        recent = db.scalars(
            select(Activity).where(
                Activity.activity_type.in_(RUN_TYPES),
                Activity.start_time_local >= cutoff,
            )
        )
        hard_dates = [
            r.start_time_local.date()
            for r in recent
            if _is_hard_run(r, profile.threshold_hr)
        ]
        if hard_dates:
            days_since_last_hard = (as_of - max(hard_dates)).days

    def _latest(model):
        return db.scalars(select(model).order_by(model.calendar_date.desc())).first()

    load = _latest(TrainingLoad)
    readiness = _latest(TrainingReadiness)
    history = db.scalars(
        select(TrainingHistory)
        .where(TrainingHistory.sport == "RUNNING")
        .order_by(TrainingHistory.calendar_date.desc())
    ).first() or _latest(TrainingHistory)
    hrv = db.scalars(
        select(Hrv).where(Hrv.source == "daily").order_by(Hrv.calendar_date.desc())
    ).first()

    resting_hr_latest = resting_hr_baseline = None
    if as_of:
        rows = db.scalars(
            select(DailyWellness.resting_hr)
            .where(
                DailyWellness.calendar_date <= as_of,
                DailyWellness.calendar_date
                >= as_of - timedelta(days=RHR_BASELINE_DAYS),
                DailyWellness.resting_hr.is_not(None),
            )
            .order_by(DailyWellness.calendar_date)
        ).all()
        if rows:
            resting_hr_baseline = median(rows)
            resting_hr_latest = rows[-1]

    sleep_hours = sleep_score = None
    nights = db.scalars(
        select(Sleep).order_by(Sleep.calendar_date.desc()).limit(SLEEP_LOOKBACK_NIGHTS)
    ).all()
    if nights:
        totals = [n.total_sleep_s for n in nights if n.total_sleep_s]
        scores = [n.overall_score for n in nights if n.overall_score is not None]
        if totals:
            sleep_hours = round(sum(totals) / len(totals) / 3600, 1)
        if scores:
            sleep_score = round(sum(scores) / len(scores), 1)

    return TrainingState(
        as_of=as_of,
        weekly_volumes=volumes,
        avg_weekly_km=avg_weekly_km,
        last_complete_week_km=last_complete_week_km,
        days_since_last_run=days_since_last_run,
        days_since_last_hard=days_since_last_hard,
        training_status=history.training_status if history else None,
        acwr=load.acwr if load else None,
        acwr_status=load.acwr_status if load else None,
        acute_load=load.acute_load if load else None,
        chronic_load=load.chronic_load if load else None,
        readiness_score=readiness.score if readiness else None,
        readiness_level=readiness.level if readiness else None,
        hrv_rmssd=hrv.rmssd if hrv else None,
        hrv_status=hrv.hrv_status if hrv else None,
        hrv_baseline_lo=hrv.baseline_lo if hrv else None,
        hrv_baseline_hi=hrv.baseline_hi if hrv else None,
        resting_hr_latest=resting_hr_latest,
        resting_hr_baseline=(
            round(resting_hr_baseline, 1) if resting_hr_baseline is not None else None
        ),
        sleep_avg_hours_7d=sleep_hours,
        sleep_avg_score_7d=sleep_score,
    )


# ---------------------------------------------------------------------------
# Fatigue veto (PLAN.md: no intervals if RHR >10% over baseline, HRV secondary)
# ---------------------------------------------------------------------------


def _fatigue_reasons(state: TrainingState) -> list[str]:
    reasons = []
    if (
        state.resting_hr_latest is not None
        and state.resting_hr_baseline
        and state.resting_hr_latest
        > state.resting_hr_baseline * (1 + RHR_VETO_FRACTION)
    ):
        pct = round((state.resting_hr_latest / state.resting_hr_baseline - 1) * 100)
        reasons.append(
            f"Resting HR {state.resting_hr_latest} bpm is +{pct}% over the "
            f"30-day median ({state.resting_hr_baseline:.0f} bpm)"
        )
    if state.hrv_status and state.hrv_status.upper() in HRV_VETO_STATUSES:
        rmssd = f"{state.hrv_rmssd:.0f} ms" if state.hrv_rmssd is not None else "n/a"
        reasons.append(f"HRV status {state.hrv_status} (RMSSD {rmssd})")
    elif (
        state.hrv_rmssd is not None
        and state.hrv_baseline_lo is not None
        and state.hrv_rmssd < state.hrv_baseline_lo
    ):
        reasons.append(
            f"HRV {state.hrv_rmssd:.0f} ms below baseline floor "
            f"({state.hrv_baseline_lo:.0f} ms)"
        )
    if state.readiness_level and state.readiness_level.upper() in READINESS_VETO_LEVELS:
        score = (
            f"{state.readiness_score}/100"
            if state.readiness_score is not None
            else "n/a"
        )
        reasons.append(f"Training readiness {state.readiness_level} ({score})")
    return reasons


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


# ---------------------------------------------------------------------------
# Session skeleton (port of temp/utils.py::_build_sessions slot map)
# ---------------------------------------------------------------------------

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
    return roles


def _enforce_hard_spacing(roles: list[SessionType], days: list[date]) -> list[str]:
    """No back-to-back hard days; on conflict the quality session goes easy."""
    notes = []
    for i in range(1, len(roles)):
        adjacent = (days[i] - days[i - 1]).days == 1
        if adjacent and roles[i] in _HARD_TYPES and roles[i - 1] in _HARD_TYPES:
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


def _allocate_distances(
    target_km: float, roles: list[SessionType], budget_km: float
) -> list[float]:
    """Split the weekly target across slots (long ≤30%, quality within budget)."""
    distances = [0.0] * len(roles)
    if target_km <= 0:
        return distances
    for i, role in enumerate(roles):
        if role == "long":
            distances[i] = round(LONG_RUN_FRACTION * target_km, 1)
    n_quality = roles.count("quality")
    if n_quality:
        each = min(
            round(QUALITY_FRACTION * target_km, 1), round(budget_km / n_quality, 1)
        )
        for i, role in enumerate(roles):
            if role == "quality":
                distances[i] = each
    easy_idx = [i for i, r in enumerate(roles) if r in ("aerobic", "recovery")]
    if easy_idx:
        each = round((target_km - sum(distances)) / len(easy_idx), 1)
        for i in easy_idx:
            distances[i] = max(each, 0.0)
    return distances


def _build_slots(
    days: list[date],
    roles: list[SessionType],
    distances: list[float],
    zone_data: dict,
    easy_only: bool,
    target_km: float,
) -> list[SessionSlot]:
    hr_zones = (
        {z.zone: z for z in zone_data["hr_zones"]} if zone_data["hr_zones"] else {}
    )
    pace_zones = (
        {z.name: z for z in zone_data["pace_zones"]} if zone_data["pace_zones"] else {}
    )
    long_cap = round(LONG_RUN_CAP_FRACTION * target_km, 1)

    slots = []
    for day, role, dist in zip(days, roles, distances):
        lo_zone, hi_zone, pace_name = _EASY_ZONES if easy_only else _TYPE_ZONES[role]
        hr_lo = hr_zones[lo_zone].min_bpm if lo_zone in hr_zones else None
        hr_hi = hr_zones[hi_zone].max_bpm if hi_zone in hr_zones else None
        pace = pace_zones.get(pace_name)

        lo = round(dist * (1 - SLOT_RANGE_FRACTION), 1)
        hi = round(dist * (1 + SLOT_RANGE_FRACTION), 1)
        if role == "long":
            hi = min(hi, long_cap)

        rationale = _TYPE_RATIONALES[role]
        if easy_only and role in ("quality", "long"):
            rationale += " Capped at Z1-Z2 this week."
        slots.append(
            SessionSlot(
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
                rationale=rationale,
            )
        )
    return slots


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


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
    """
    week_monday = _iso_monday(week)
    rationale: list[str] = []

    state = _training_state(db, profile)

    # --- allowed days (request override > profile > plan_week default) ---
    allowed = days_override if days_override else list(profile.preferred_days)
    if not allowed:
        allowed = DEFAULT_DAYS
        rationale.append("No preferred days set; using default Mon/Wed/Fri/Sat.")
    allowed = sorted(set(allowed))

    # --- injury narrowing: no back-to-back run days at all ---
    injury_flags = [
        entry
        for entry in (profile.injury_history or [])
        if any(key in entry.lower() for key in RESTRICTIVE_INJURIES)
    ]
    days = [week_monday + timedelta(days=d) for d in allowed]
    if injury_flags:
        kept: list[date] = []
        for day in days:
            if kept and (day - kept[-1]).days == 1:
                rationale.append(
                    f"Injury flag '{injury_flags[0]}': dropped {day:%A} to avoid "
                    "back-to-back run days."
                )
                continue
            kept.append(day)
        days = kept

    # --- phase & cycle ---
    phase, weeks_to_race = _phase(profile, week_monday)
    if phase:
        rationale.append(
            f"Phase {phase}: {weeks_to_race} weeks to "
            f"{profile.goal_race_distance} on {profile.goal_race_date}."
        )
    else:
        rationale.append("Health mode: no periodization, Z2-focused maintenance.")

    streak = _build_streak(state.weekly_volumes)
    cycle: CycleWeekType = "deload" if streak >= BUILD_STREAK_FOR_DELOAD else "build"
    if cycle == "deload":
        rationale.append(
            f"3:1 cycle: {streak} consecutive build weeks detected — "
            "this week is a deload (all easy)."
        )
    else:
        rationale.append(f"3:1 cycle: build week ({streak} into the current block).")

    # --- fatigue veto ---
    fatigue_reasons = _fatigue_reasons(state)
    fatigue_veto = bool(fatigue_reasons)
    for reason in fatigue_reasons:
        rationale.append(f"Fatigue veto: {reason} — intensity removed.")

    # --- weekly volume target (plan_week adjustment + hard ceiling) ---
    avg = state.avg_weekly_km or profile.current_weekly_volume_km or 0.0
    ceiling = round(avg * WEEKLY_CEILING_FACTOR, 2)
    if cycle == "deload" and state.last_complete_week_km:
        target = round(state.last_complete_week_km * DELOAD_TARGET_RATIO, 1)
    elif profile.goal_mode != "race":
        target = round(avg, 1)  # health mode: volume maintenance
    elif (state.days_since_last_run or 0) >= 7 or state.training_status in (
        "DETRAINING",
        "RECOVERY",
    ):
        target = round(avg * 0.85, 1)
    elif state.training_status in ("PRODUCTIVE", "PEAKING"):
        target = round(avg * 1.05, 1)
    else:
        target = round(avg, 1)
    target = round(min(target, ceiling), 1)
    rationale.append(
        f"Volume target {target} km (recent avg {avg:.1f} km, "
        f"hard ceiling {ceiling} km = avg × {WEEKLY_CEILING_FACTOR})."
    )

    # --- intensity budget (80/20; zero on deload or fatigue veto) ---
    easy_only = fatigue_veto or cycle == "deload"
    budget = 0.0 if easy_only else round(INTENSITY_BUDGET_FRACTION * target, 2)
    rationale.append(
        "Intensity budget 0 km — all sessions easy."
        if easy_only
        else f"Intensity budget {budget} km (20% of target)."
    )

    # --- per-day skeleton ---
    # Health mode is all-Z2 (no quality). In race mode quality is kept through
    # the taper (intensity retained while volume drops); only post-race
    # recovery drops it entirely.
    quality_allowed = (
        not easy_only and profile.goal_mode == "race" and phase != "recovery"
    )
    roles = _session_roles(len(days), quality_allowed)
    spacing_notes = _enforce_hard_spacing(roles, days)
    rationale.extend(spacing_notes)
    distances = _allocate_distances(target, roles, budget)
    zone_data = compute_zones(profile)
    sessions = _build_slots(days, roles, distances, zone_data, easy_only, target)

    return WeekConstraints(
        week_start=week_monday,
        goal_mode=profile.goal_mode,
        phase=phase,
        weeks_to_race=weeks_to_race,
        cycle_week_type=cycle,
        weekly_volume_target_km=target,
        weekly_volume_ceiling_km=ceiling,
        intensity_budget_km=budget,
        allowed_days=[d.weekday() for d in days],
        fatigue_veto=fatigue_veto,
        fatigue_reasons=fatigue_reasons,
        injury_flags=injury_flags,
        sessions=sessions,
        state=state,
        rationale=rationale,
    )
