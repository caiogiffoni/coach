// Workout display helpers: derived distance, zone extraction, step targets.

import type { Workout, WorkoutStep, Zone } from './types'
import { formatPace } from './format'

const ZONE_ORDER: Zone[] = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']

/** Unique step zones of a workout, sorted Z1→Z5. */
export function workoutZones(workout: Workout): string[] {
  const zones = new Set<string>()
  for (const step of workout.steps) {
    if (step.target_zone) zones.add(step.target_zone)
  }
  return [...zones].sort(
    (a, b) => ZONE_ORDER.indexOf(a as Zone) - ZONE_ORDER.indexOf(b as Zone),
  )
}

/** Sum of step distances derived from duration ÷ midpoint pace. Null if no
    step carries pace targets. */
export function derivedDistanceKm(workout: Workout): number | null {
  let km = 0
  let any = false
  for (const step of workout.steps) {
    if (step.target_pace_min && step.target_pace_max) {
      const pace = (step.target_pace_min + step.target_pace_max) / 2
      km += (step.duration_min * 60) / pace
      any = true
    }
  }
  return any ? km : null
}

/** "4:30/km–5:00/km · 150–160 bpm" — whichever targets the step carries. */
export function stepTargetText(step: WorkoutStep): string {
  const parts: string[] = []
  if (step.target_pace_min && step.target_pace_max) {
    parts.push(`${formatPace(step.target_pace_min)}–${formatPace(step.target_pace_max)}`)
  }
  if (step.target_hr_min && step.target_hr_max) {
    parts.push(`${step.target_hr_min}–${step.target_hr_max} bpm`)
  }
  return parts.join(' · ')
}
