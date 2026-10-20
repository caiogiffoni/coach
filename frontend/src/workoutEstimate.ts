// Client-side workout estimates, same rules as the backend contract:
// time steps add seconds, distance steps add meters; the other total is only
// derivable from a pace_range target (midpoint pace); lap_button steps make
// both totals null; repeats multiply by iterations.

import type { BuilderStep, WorkoutItem } from './types'

export interface WorkoutEstimate {
  durationSec: number | null
  distanceM: number | null
}

function midpointPace(step: BuilderStep): number | null {
  if (step.target.type !== 'pace_range') return null
  return (step.target.fast_sec_per_km + step.target.slow_sec_per_km) / 2
}

/** Estimate of a single leaf step. */
export function estimateStep(step: BuilderStep): WorkoutEstimate {
  const pace = midpointPace(step)
  if (step.end.type === 'time') {
    const seconds = step.end.seconds
    return { durationSec: seconds, distanceM: pace === null ? null : (seconds / pace) * 1000 }
  }
  if (step.end.type === 'distance') {
    const meters = step.end.meters
    return { durationSec: pace === null ? null : (meters / 1000) * pace, distanceM: meters }
  }
  return { durationSec: null, distanceM: null }
}

function addNullable(a: number | null, b: number | null): number | null {
  return a === null || b === null ? null : a + b
}

function estimateItem(item: WorkoutItem): WorkoutEstimate {
  if (item.kind === 'step') return estimateStep(item)
  const once = estimateSequence(item.steps)
  return {
    durationSec: once.durationSec === null ? null : once.durationSec * item.iterations,
    distanceM: once.distanceM === null ? null : once.distanceM * item.iterations,
  }
}

function estimateSequence(items: WorkoutItem[]): WorkoutEstimate {
  let total: WorkoutEstimate = { durationSec: 0, distanceM: 0 }
  for (const item of items) {
    const part = estimateItem(item)
    total = {
      durationSec: addNullable(total.durationSec, part.durationSec),
      distanceM: addNullable(total.distanceM, part.distanceM),
    }
  }
  return total
}

/**
 * Total estimated duration/distance, null where any step can't be estimated.
 *
 * Example: `estimateWorkout(items).durationSec // 2400`
 */
export function estimateWorkout(items: WorkoutItem[]): WorkoutEstimate {
  if (items.length === 0) return { durationSec: null, distanceM: null }
  return estimateSequence(items)
}

/** Leaf steps with repeats expanded (iterations × children), like the API's step_count. */
export function expandedStepCount(items: WorkoutItem[]): number {
  return items.reduce((n, item) => n + (item.kind === 'repeat' ? item.iterations * item.steps.length : 1), 0)
}
