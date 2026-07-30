"""
LLM week generator (PLAN.md build-order step 5).

The LLM fills in workout DETAIL (names, descriptions, step structure)
inside the constraint engine's hard skeleton — it never decides volume,
intensity, or training days. Every LLM answer goes through
validator.validate_week; on failure the error list is appended to the
prompt and the call retried (MAX_ATTEMPTS total). When all attempts fail,
or no LLM is configured at all, a deterministic rule-based week is built
straight from the SessionSlots — a valid week always exists
(`source: "llm" | "fallback"`).

Prompts live here as constants/functions. The llm client is injected (see
app/llm/client.py), so tests pass a fake and never touch a real API.
"""

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..llm.client import LLMClient
from ..profile.models import Profile
from .constraints import SessionSlot, WeekConstraints
from .validator import GeneratedWeek, GeneratedWorkout, WorkoutStep, validate_week

MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """\
You are an elite distance-running coach writing one week of workouts for an \
athlete whose data and guardrails are given below.

The week skeleton is FIXED by the constraint engine. You only fill in the \
details: workout names, descriptions, and step-by-step structure. You must \
never change which days have workouts, the session types, or exceed the \
distance/HR/pace ranges given for each day.

Respond with JSON ONLY — no prose, no markdown fences. Schema:
{
  "workouts": [
    {
      "name": string,             // short, e.g. "Threshold 5x4min"
      "date": "YYYY-MM-DD",       // exactly one workout per session day below
      "sport": "running",
      "duration_min": number,     // ≈ sum of step durations
      "description": string,      // 1-2 sentences: purpose + execution cues
      "steps": [
        {
          "type": "warmup" | "main" | "interval" | "recovery" | "cooldown" | "rest",
          "duration_min": number, // positive
          "target_zone": "Z1".."Z5" | null,
          "target_pace_min": int | null,  // faster bound, sec/km
          "target_pace_max": int | null,  // slower bound, sec/km
          "target_hr_min": int | null,    // bpm
          "target_hr_max": int | null     // bpm
        }
      ]
    }
  ]
}

Step-structure expectations:
- quality: warmup (10-15 min Z1-Z2), interval/recovery pairs for the main \
set (intervals at the day's HR/pace targets, recovery jogs Z1), cooldown.
- aerobic / long: warmup, one steady "main" step within the day's targets, \
cooldown (a single "main" step for the whole run is also acceptable).
- recovery: single easy step, or warmup/main/cooldown, all Z1.
Every target must stay inside the day's stated bpm and sec/km ranges.\
"""

_DAY_PROMPT_HEADER = """\
Regenerate ONE workout only, for {date} (the {slot_type} slot). Respond with \
a single workout JSON object (same schema as one element of "workouts"), \
not a full week.\
"""


@dataclass
class GenerationResult:
    week: GeneratedWeek
    source: str  # "llm" | "fallback"
    errors: list[str] = field(default_factory=list)  # last failed attempt's


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _fmt_pace(sec_per_km: int | None) -> str:
    if sec_per_km is None:
        return "n/a"
    return f"{sec_per_km // 60}:{sec_per_km % 60:02d}/km ({sec_per_km} s/km)"


def _slot_lines(slot: SessionSlot) -> str:
    hr = (
        f"{slot.hr_bpm_lo}-{slot.hr_bpm_hi} bpm"
        if slot.hr_bpm_lo is not None and slot.hr_bpm_hi is not None
        else "no HR bounds"
    )
    pace = (
        f"{_fmt_pace(slot.pace_lo_sec_per_km)} – {_fmt_pace(slot.pace_hi_sec_per_km)}"
        if slot.pace_lo_sec_per_km is not None
        else "no pace bounds"
    )
    return (
        f"- {slot.date} ({slot.date:%A}) — {slot.type.upper()}: "
        f"{slot.distance_km_lo}-{slot.distance_km_hi} km, "
        f"HR {slot.hr_zone_range} ({hr}), pace {pace}. {slot.rationale}"
    )


def build_user_prompt(
    constraints: WeekConstraints, profile: Profile, notes: str | None
) -> str:
    """Hard constraints + athlete context + strict output instruction."""
    state = constraints.state
    sections = ["# HARD CONSTRAINTS (never violate)"]
    sections.append(
        f"Week of {constraints.week_start}. Cycle: {constraints.cycle_week_type}."
        f"\nWeekly volume target: {constraints.weekly_volume_target_km} km "
        f"(do not exceed the per-day upper bounds below)."
        f"\nIntensity budget (quality-session distance): "
        f"{constraints.intensity_budget_km} km."
    )
    if constraints.fatigue_veto:
        reasons = "; ".join(constraints.fatigue_reasons)
        sections.append(
            f"FATIGUE VETO ACTIVE: {reasons}. Nothing above Z2 anywhere this week."
        )
    if constraints.injury_flags:
        sections.append(
            f"INJURY FLAGS: {', '.join(constraints.injury_flags)} — "
            "keep impact conservative, no back-to-back run days."
        )
    sections.append("\n# SESSION DAYS (exactly one workout per date)")
    sections.extend(_slot_lines(s) for s in constraints.sessions)

    sections.append("\n# ATHLETE CONTEXT")
    goal = f"Goal mode: {constraints.goal_mode}"
    if profile.goal_mode == "race" and profile.goal_race_date:
        goal += (
            f" — {profile.goal_race_distance} on {profile.goal_race_date}"
            f" (phase: {constraints.phase}, {constraints.weeks_to_race} weeks out)"
        )
    sections.append(goal)
    sections.append(
        "Recent state: "
        f"status {state.training_status or 'n/a'}, "
        f"ACWR {state.acwr if state.acwr is not None else 'n/a'}, "
        f"readiness {state.readiness_score or 'n/a'}"
        f" ({state.readiness_level or 'n/a'}), "
        f"resting HR {state.resting_hr_latest or 'n/a'} bpm "
        f"(baseline {state.resting_hr_baseline or 'n/a'}), "
        f"HRV {state.hrv_status or 'n/a'}, "
        f"sleep avg {state.sleep_avg_hours_7d or 'n/a'} h."
    )
    if notes:
        sections.append(f"\n# NOTES FROM THE ATHLETE\n{notes.strip()}")
    sections.append("\nRespond with the JSON week only, matching the schema exactly.")
    return "\n".join(sections)


def build_day_prompt(
    slot: SessionSlot,
    constraints: WeekConstraints,
    profile: Profile,
    notes: str | None,
) -> str:
    """Single-day variant: full context, but ask for one workout object."""
    header = _DAY_PROMPT_HEADER.format(date=slot.date, slot_type=slot.type)
    return header + "\n\n" + build_user_prompt(constraints, profile, notes)


def _retry_suffix(errors: list[str]) -> str:
    listing = "\n".join(f"- {e}" for e in errors)
    return (
        "\n\n# VALIDATION ERRORS IN YOUR PREVIOUS ANSWER\n"
        f"{listing}\nFix ALL of these and respond with corrected JSON only."
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Pull the JSON payload out of a raw LLM response (fences tolerated)."""
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_week(raw: str) -> GeneratedWeek:
    """Raw LLM text → GeneratedWeek. Raises ValueError with a readable msg."""
    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc
    try:
        return GeneratedWeek.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        raise ValueError(f"Response does not match the week schema: {msgs}") from exc


def parse_workout(raw: str) -> GeneratedWorkout:
    """Single-workout variant for per-day regeneration."""
    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc
    try:
        return GeneratedWorkout.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        raise ValueError(f"Response does not match the workout schema: {msgs}") from exc


# ---------------------------------------------------------------------------
# Deterministic fallback — a valid week straight from the SessionSlots
# ---------------------------------------------------------------------------

_DEFAULT_EASY_PACE_SEC_PER_KM = 360  # 6:00/km when no pace zones exist


def _mid_pace(slot: SessionSlot) -> float:
    if slot.pace_lo_sec_per_km is not None and slot.pace_hi_sec_per_km is not None:
        return (slot.pace_lo_sec_per_km + slot.pace_hi_sec_per_km) / 2
    return _DEFAULT_EASY_PACE_SEC_PER_KM


def fallback_workout(slot: SessionSlot) -> GeneratedWorkout:
    """
    Rule-based workout for one slot: 10-min Z1 warmup, main set sized so
    the derived distance lands mid-range at the slot's targets, 5-min Z1
    cooldown. Always passes the validator against its own slot.
    """
    mid_km = (slot.distance_km_lo + slot.distance_km_hi) / 2
    pace = _mid_pace(slot)
    total_min = mid_km * pace / 60
    warmup_min = min(10.0, total_min * 0.25)
    cooldown_min = min(5.0, total_min * 0.15)
    main_min = max(total_min - warmup_min - cooldown_min, 5.0)

    hi_zone = slot.hr_zone_range.split("-")[-1]  # e.g. "Z1-Z2" → "Z2"
    main_type = "interval" if slot.type == "quality" else "main"
    names = {
        "aerobic": "Easy aerobic run",
        "quality": "Quality session",
        "recovery": "Recovery jog",
        "long": "Long run",
    }

    steps = [
        WorkoutStep(
            type="warmup",
            duration_min=round(warmup_min, 1),
            target_zone="Z1",
            target_pace_min=slot.pace_lo_sec_per_km,
            target_pace_max=slot.pace_hi_sec_per_km,
            target_hr_min=slot.hr_bpm_lo,
            target_hr_max=slot.hr_bpm_hi,
        ),
        WorkoutStep(
            type=main_type,
            duration_min=round(main_min, 1),
            target_zone=hi_zone,
            target_pace_min=slot.pace_lo_sec_per_km,
            target_pace_max=slot.pace_hi_sec_per_km,
            target_hr_min=slot.hr_bpm_lo,
            target_hr_max=slot.hr_bpm_hi,
        ),
        WorkoutStep(
            type="cooldown",
            duration_min=round(cooldown_min, 1),
            target_zone="Z1",
            target_pace_min=slot.pace_lo_sec_per_km,
            target_pace_max=slot.pace_hi_sec_per_km,
            target_hr_min=slot.hr_bpm_lo,
            target_hr_max=slot.hr_bpm_hi,
        ),
    ]
    return GeneratedWorkout(
        name=names[slot.type],
        date=slot.date,
        sport="running",
        duration_min=round(warmup_min + main_min + cooldown_min, 1),
        description=slot.rationale,
        steps=steps,
    )


def fallback_week(constraints: WeekConstraints) -> GeneratedWeek:
    return GeneratedWeek(
        workouts=[fallback_workout(slot) for slot in constraints.sessions]
    )


# ---------------------------------------------------------------------------
# Generation with retry + fallback
# ---------------------------------------------------------------------------


def generate_week(
    constraints: WeekConstraints,
    profile: Profile,
    notes: str | None,
    llm: LLMClient | None,
) -> GenerationResult:
    """
    LLM-generate a week with validator-in-the-loop retries, falling back to
    the deterministic week after MAX_ATTEMPTS failures or when `llm` is None.
    """
    if llm is not None:
        prompt = build_user_prompt(constraints, profile, notes)
        errors: list[str] = []
        for _ in range(MAX_ATTEMPTS):
            raw = llm.generate(
                SYSTEM_PROMPT, prompt + (_retry_suffix(errors) if errors else "")
            )
            try:
                week = parse_week(raw)
                errors = validate_week(week, constraints)
            except ValueError as exc:
                errors = [str(exc)]
            if not errors:
                return GenerationResult(week=week, source="llm")
    week = fallback_week(constraints)
    return GenerationResult(
        week=week, source="fallback", errors=validate_week(week, constraints)
    )


def generate_day(
    slot: SessionSlot,
    constraints: WeekConstraints,
    profile: Profile,
    notes: str | None,
    llm: LLMClient | None,
    current_week: GeneratedWeek,
) -> GenerationResult:
    """
    Regenerate a single day's workout. The candidate is validated as part of
    the full week (replacing that date's workout) so week-level guardrails
    still hold; on failure the slot's deterministic workout is used.
    """

    def _swap(workout: GeneratedWorkout) -> GeneratedWeek:
        others = [w for w in current_week.workouts if w.date != slot.date]
        return GeneratedWeek(workouts=sorted(others + [workout], key=lambda w: w.date))

    if llm is not None:
        prompt = build_day_prompt(slot, constraints, profile, notes)
        errors: list[str] = []
        for _ in range(MAX_ATTEMPTS):
            raw = llm.generate(
                SYSTEM_PROMPT, prompt + (_retry_suffix(errors) if errors else "")
            )
            try:
                candidate = parse_workout(raw)
                candidate.date = slot.date  # the slot date wins over the LLM's
                errors = validate_week(_swap(candidate), constraints)
            except ValueError as exc:
                errors = [str(exc)]
            if not errors:
                return GenerationResult(week=_swap(candidate), source="llm")
    week = _swap(fallback_workout(slot))
    return GenerationResult(
        week=week, source="fallback", errors=validate_week(week, constraints)
    )
