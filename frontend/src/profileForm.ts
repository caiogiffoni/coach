import { parseHms, parsePace, secToHms, secToMinSec } from './format'
import type { GoalMode, Profile, ProfileUpdate, RaceDistance } from './types'

export const RACE_DISTANCES: RaceDistance[] = ['5K', '10K', 'HM', 'MARATHON']

export interface FormState {
  max_hr: string
  resting_hr: string
  threshold_pace: string // m:ss/km
  threshold_hr: string
  recent_race_distance_km: string
  recent_race_time: string // h:mm:ss
  current_weekly_volume_km: string
  injury_history: string // comma-separated
  goal_mode: GoalMode
  goal_race_distance: RaceDistance | ''
  goal_race_date: string
  preferred_days: number[]
}

export type FieldErrors = Record<string, string>

export type SetFormField = <K extends keyof FormState>(key: K, value: FormState[K]) => void

export const EMPTY_FORM: FormState = {
  max_hr: '',
  resting_hr: '',
  threshold_pace: '',
  threshold_hr: '',
  recent_race_distance_km: '',
  recent_race_time: '',
  current_weekly_volume_km: '',
  injury_history: '',
  goal_mode: 'health',
  goal_race_distance: '',
  goal_race_date: '',
  preferred_days: [],
}

function numOrNull(s: string): number | null {
  const t = s.trim()
  if (t === '') return null
  const n = Number(t)
  return Number.isNaN(n) ? null : n
}

/**
 * Convert a stored profile into editable string fields.
 *
 * Example: `setForm(profileToForm(await profile.get()))`
 */
export function profileToForm(p: Profile): FormState {
  return {
    max_hr: p.max_hr?.toString() ?? '',
    resting_hr: p.resting_hr?.toString() ?? '',
    threshold_pace: secToMinSec(p.threshold_pace_sec_per_km),
    threshold_hr: p.threshold_hr?.toString() ?? '',
    recent_race_distance_km: p.recent_race_distance_km?.toString() ?? '',
    recent_race_time: secToHms(p.recent_race_time_sec),
    current_weekly_volume_km: p.current_weekly_volume_km?.toString() ?? '',
    injury_history: p.injury_history.join(', '),
    goal_mode: p.goal_mode,
    goal_race_distance: p.goal_race_distance ?? '',
    goal_race_date: p.goal_race_date ?? '',
    preferred_days: p.preferred_days,
  }
}

/** Parse an optional field; returns null for blank input or `undefined` when unparseable. */
function parseOptional(value: string, parse: (s: string) => number | null): number | null | undefined {
  if (value.trim() === '') return null
  return parse(value) ?? undefined
}

function collectFieldErrors(form: FormState): FieldErrors {
  const errors: FieldErrors = {}
  if (parseOptional(form.threshold_pace, parsePace) === undefined) {
    errors.threshold_pace = 'Use m:ss, e.g. 4:30'
  }
  if (parseOptional(form.recent_race_time, parseHms) === undefined) {
    errors.recent_race_time = 'Use h:mm:ss, e.g. 1:45:30'
  }
  if (form.goal_mode === 'race') {
    if (!form.goal_race_distance) errors.goal_race_distance = 'Required in race mode'
    if (!form.goal_race_date) errors.goal_race_date = 'Required in race mode'
  }
  return errors
}

function formToUpdate(form: FormState): ProfileUpdate {
  const race = form.goal_mode === 'race'
  return {
    max_hr: numOrNull(form.max_hr),
    resting_hr: numOrNull(form.resting_hr),
    threshold_pace_sec_per_km: parseOptional(form.threshold_pace, parsePace) ?? null,
    threshold_hr: numOrNull(form.threshold_hr),
    recent_race_distance_km: numOrNull(form.recent_race_distance_km),
    recent_race_time_sec: parseOptional(form.recent_race_time, parseHms) ?? null,
    current_weekly_volume_km: numOrNull(form.current_weekly_volume_km),
    injury_history: form.injury_history
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    goal_mode: form.goal_mode,
    goal_race_distance: race && form.goal_race_distance !== '' ? form.goal_race_distance : null,
    goal_race_date: race ? form.goal_race_date || null : null,
    preferred_days: form.preferred_days,
  }
}

/**
 * Validate the form; `body` is null whenever `errors` is non-empty.
 *
 * Example: `const { errors, body } = validateProfileForm(form)`
 */
export function validateProfileForm(form: FormState): { errors: FieldErrors; body: ProfileUpdate | null } {
  const errors = collectFieldErrors(form)
  if (Object.keys(errors).length > 0) return { errors, body: null }
  return { errors, body: formToUpdate(form) }
}
