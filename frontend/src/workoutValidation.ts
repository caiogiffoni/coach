// Client-side validation of a workout draft, mirroring the API contract bounds
// so the user sees inline messages before the server's 422.

import { parsePace } from './format'
import { parseDistanceKm, parseStepDuration, parseWholeNumber } from './workoutBuilder'
import type { ItemDraft, RepeatDraft, StepDraft, WorkoutDraft } from './workoutBuilder'

export const LIMITS = {
  nameMax: 100,
  descriptionMax: 1000,
  notesMax: 200,
  itemsMax: 50,
  leafStepsMax: 100,
  repeatStepsMax: 20,
  iterationsMin: 2,
  iterationsMax: 50,
  secondsMax: 86400,
  metersMax: 100000,
  bpmMin: 30,
  bpmMax: 230,
  paceMin: 120,
  paceMax: 1200,
} as const

export interface ItemErrors {
  end?: string
  target?: string
  notes?: string
  iterations?: string
  steps?: string
}

export interface DraftErrors {
  name?: string
  description?: string
  items?: string
  byUid: Record<string, ItemErrors>
}

function endError(step: StepDraft): string | undefined {
  if (step.endType === 'time') {
    const sec = parseStepDuration(step.timeText)
    if (sec === null) return `Enter a time as m:ss, got "${step.timeText}"`
    if (sec > LIMITS.secondsMax) return 'Time must be at most 24:00:00'
  }
  if (step.endType === 'distance') {
    const meters = parseDistanceKm(step.distanceKmText)
    if (meters === null) return `Enter a distance in km, got "${step.distanceKmText}"`
    if (meters > LIMITS.metersMax) return 'Distance must be at most 100 km'
  }
  return undefined
}

function hrRangeError(step: StepDraft): string | undefined {
  const min = parseWholeNumber(step.minBpmText)
  const max = parseWholeNumber(step.maxBpmText)
  if (min === null || max === null) return 'Enter both heart rates as whole bpm'
  if (min < LIMITS.bpmMin || max > LIMITS.bpmMax) return `Heart rate must be ${LIMITS.bpmMin}–${LIMITS.bpmMax} bpm`
  if (min >= max) return 'Low heart rate must be below high heart rate'
  return undefined
}

function paceRangeError(step: StepDraft): string | undefined {
  const fast = parsePace(step.fastPaceText)
  const slow = parsePace(step.slowPaceText)
  if (fast === null || slow === null) return 'Enter both paces as m:ss per km'
  if (fast < LIMITS.paceMin || slow > LIMITS.paceMax) return 'Pace must be between 2:00 and 20:00 /km'
  if (fast >= slow) return 'Fast pace must be quicker (lower) than slow pace'
  return undefined
}

function targetError(step: StepDraft): string | undefined {
  if (step.targetType === 'hr_range') return hrRangeError(step)
  if (step.targetType === 'pace_range') return paceRangeError(step)
  return undefined
}

function stepErrors(step: StepDraft): ItemErrors {
  const errors: ItemErrors = { end: endError(step), target: targetError(step) }
  if (step.notes.length > LIMITS.notesMax) errors.notes = `Notes must be at most ${LIMITS.notesMax} characters`
  return errors
}

function repeatErrors(repeat: RepeatDraft): ItemErrors {
  const errors: ItemErrors = {}
  const n = parseWholeNumber(repeat.iterationsText)
  if (n === null || n < LIMITS.iterationsMin || n > LIMITS.iterationsMax) {
    errors.iterations = `Repeat ${LIMITS.iterationsMin}–${LIMITS.iterationsMax} times`
  }
  if (repeat.steps.length === 0) errors.steps = 'A repeat needs at least one step'
  if (repeat.steps.length > LIMITS.repeatStepsMax) errors.steps = `A repeat holds at most ${LIMITS.repeatStepsMax} steps`
  return errors
}

function collectItemErrors(items: ItemDraft[]): Record<string, ItemErrors> {
  const byUid: Record<string, ItemErrors> = {}
  for (const item of items) {
    if (item.kind === 'step') {
      byUid[item.uid] = stepErrors(item)
      continue
    }
    byUid[item.uid] = repeatErrors(item)
    for (const child of item.steps) byUid[child.uid] = stepErrors(child)
  }
  return byUid
}

function itemsError(items: ItemDraft[]): string | undefined {
  if (items.length === 0) return 'Add at least one step'
  if (items.length > LIMITS.itemsMax) return `At most ${LIMITS.itemsMax} steps and repeats`
  const leaves = items.reduce((n, item) => n + (item.kind === 'repeat' ? item.steps.length : 1), 0)
  if (leaves > LIMITS.leafStepsMax) return `At most ${LIMITS.leafStepsMax} steps in total, got ${leaves}`
  return undefined
}

/**
 * Inline validation errors for the whole draft.
 *
 * Example: `const errors = validateDraft(draft); if (hasDraftErrors(errors)) return`
 */
export function validateDraft(draft: WorkoutDraft): DraftErrors {
  const name = draft.name.trim()
  return {
    name: name === '' || name.length > LIMITS.nameMax ? `Name must be 1–${LIMITS.nameMax} characters` : undefined,
    description:
      draft.description.length > LIMITS.descriptionMax
        ? `Description must be at most ${LIMITS.descriptionMax} characters`
        : undefined,
    items: itemsError(draft.items),
    byUid: collectItemErrors(draft.items),
  }
}

export function hasDraftErrors(errors: DraftErrors): boolean {
  if (errors.name || errors.description || errors.items) return true
  return Object.values(errors.byUid).some((e) => Object.values(e).some(Boolean))
}
