// Workout builder draft model: editable step/repeat drafts (numbers kept as the
// text the user typed), defaults mirroring Garmin's "new workout", wire
// conversion, and pure list operations (add/move/duplicate/remove).

import { parseHms, parsePace, secToMinSec } from './format'
import type {
  BuilderStep,
  BuilderStepEnd,
  BuilderStepTarget,
  BuilderStepType,
  HrZoneNumber,
  RepeatBlock,
  WorkoutItem,
} from './types'

export type EndType = BuilderStepEnd['type']
export type TargetType = BuilderStepTarget['type']

/** One leaf step as edited in the form. Every end/target value is kept so
    switching the End or Target type back restores what was typed. */
export interface StepDraft {
  uid: string
  kind: 'step'
  stepType: BuilderStepType
  endType: EndType
  timeText: string // "m:ss" or "h:mm:ss"
  distanceKmText: string // "1.00"
  targetType: TargetType
  hrZone: HrZoneNumber
  minBpmText: string
  maxBpmText: string
  fastPaceText: string // "m:ss" per km
  slowPaceText: string
  notes: string
}

export interface RepeatDraft {
  uid: string
  kind: 'repeat'
  iterationsText: string
  steps: StepDraft[]
}

export type ItemDraft = StepDraft | RepeatDraft

export interface WorkoutDraft {
  name: string
  description: string
  items: ItemDraft[]
}

export const STEP_TYPE_LABELS: Record<BuilderStepType, string> = {
  warmup: 'Warm up',
  run: 'Run',
  recover: 'Recover',
  rest: 'Rest',
  cooldown: 'Cool down',
}

let uidCounter = 0

/** Client-only React key; never sent to the server. */
export function newUid(): string {
  uidCounter += 1
  return `item-${uidCounter}`
}

const BLANK_STEP: Omit<StepDraft, 'uid' | 'stepType'> = {
  kind: 'step',
  endType: 'time',
  timeText: '10:00',
  distanceKmText: '1.00',
  targetType: 'none',
  hrZone: 2,
  minBpmText: '',
  maxBpmText: '',
  fastPaceText: '',
  slowPaceText: '',
  notes: '',
}

/** Fresh step draft. Example: `createStep('run', { endType: 'distance' })` */
export function createStep(stepType: BuilderStepType, overrides: Partial<StepDraft> = {}): StepDraft {
  return { ...BLANK_STEP, uid: newUid(), stepType, ...overrides }
}

/** Garmin's default repeat: 2 × (Run 1 km, Recover 2:00). */
export function createRepeat(): RepeatDraft {
  return {
    uid: newUid(),
    kind: 'repeat',
    iterationsText: '2',
    steps: [createStep('run', { endType: 'distance' }), createStep('recover', { timeText: '2:00' })],
  }
}

/** New-workout defaults: warm up 10:00, run 1 km, cool down 10:00. */
export function createDefaultDraft(): WorkoutDraft {
  return {
    name: 'Run workout',
    description: '',
    items: [
      createStep('warmup'),
      createStep('run', { endType: 'distance' }),
      createStep('cooldown'),
    ],
  }
}

// --- Wire → draft ---------------------------------------------------------

function endToDraft(end: BuilderStepEnd): Partial<StepDraft> {
  if (end.type === 'time') return { endType: 'time', timeText: secToMinSec(end.seconds) }
  if (end.type === 'distance') return { endType: 'distance', distanceKmText: (end.meters / 1000).toFixed(2) }
  return { endType: 'lap_button' }
}

function targetToDraft(target: BuilderStepTarget): Partial<StepDraft> {
  if (target.type === 'hr_zone') return { targetType: 'hr_zone', hrZone: target.zone }
  if (target.type === 'hr_range') {
    return { targetType: 'hr_range', minBpmText: String(target.min_bpm), maxBpmText: String(target.max_bpm) }
  }
  if (target.type === 'pace_range') {
    return {
      targetType: 'pace_range',
      fastPaceText: secToMinSec(target.fast_sec_per_km),
      slowPaceText: secToMinSec(target.slow_sec_per_km),
    }
  }
  return { targetType: 'none' }
}

function stepToDraft(step: BuilderStep): StepDraft {
  return createStep(step.step_type, { ...endToDraft(step.end), ...targetToDraft(step.target), notes: step.notes })
}

/** Saved items → editable drafts. Example: `itemsToDrafts(workout.steps)` */
export function itemsToDrafts(items: WorkoutItem[]): ItemDraft[] {
  return items.map((item) =>
    item.kind === 'repeat'
      ? { uid: newUid(), kind: 'repeat', iterationsText: String(item.iterations), steps: item.steps.map(stepToDraft) }
      : stepToDraft(item),
  )
}

// --- Draft → wire (null when any typed value doesn't parse) ---------------

/** "1.5" → 1500 m; null when not a positive number. */
export function parseDistanceKm(text: string): number | null {
  const km = Number(text.trim().replace(',', '.'))
  if (text.trim() === '' || !Number.isFinite(km) || km <= 0) return null
  return Math.round(km * 1000)
}

/** "10:00" → 600 s; null when not a whole number of seconds. */
export function parseStepDuration(text: string): number | null {
  const sec = parseHms(text)
  return sec !== null && Number.isInteger(sec) && sec > 0 ? sec : null
}

/** "152" → 152; null when not an integer. */
export function parseWholeNumber(text: string): number | null {
  const trimmed = text.trim()
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null
}

export function draftEnd(step: StepDraft): BuilderStepEnd | null {
  if (step.endType === 'lap_button') return { type: 'lap_button' }
  if (step.endType === 'time') {
    const seconds = parseStepDuration(step.timeText)
    return seconds === null ? null : { type: 'time', seconds }
  }
  const meters = parseDistanceKm(step.distanceKmText)
  return meters === null ? null : { type: 'distance', meters }
}

export function draftTarget(step: StepDraft): BuilderStepTarget | null {
  if (step.targetType === 'none') return { type: 'none' }
  if (step.targetType === 'hr_zone') return { type: 'hr_zone', zone: step.hrZone }
  if (step.targetType === 'hr_range') {
    const min_bpm = parseWholeNumber(step.minBpmText)
    const max_bpm = parseWholeNumber(step.maxBpmText)
    return min_bpm === null || max_bpm === null ? null : { type: 'hr_range', min_bpm, max_bpm }
  }
  const fast = parsePace(step.fastPaceText)
  const slow = parsePace(step.slowPaceText)
  return fast === null || slow === null ? null : { type: 'pace_range', fast_sec_per_km: fast, slow_sec_per_km: slow }
}

function draftToStep(step: StepDraft): BuilderStep | null {
  const end = draftEnd(step)
  const target = draftTarget(step)
  if (!end || !target) return null
  return { kind: 'step', step_type: step.stepType, end, target, notes: step.notes }
}

function draftToRepeat(repeat: RepeatDraft): RepeatBlock | null {
  const iterations = parseWholeNumber(repeat.iterationsText)
  const steps = repeat.steps.map(draftToStep)
  if (iterations === null || steps.some((s) => s === null)) return null
  return { kind: 'repeat', iterations, steps: steps as BuilderStep[] }
}

/** Drafts → wire items, or null if any value is unparseable.
    Example: `const items = draftsToItems(draft.items)` */
export function draftsToItems(items: ItemDraft[]): WorkoutItem[] | null {
  const converted = items.map((item) => (item.kind === 'repeat' ? draftToRepeat(item) : draftToStep(item)))
  return converted.some((item) => item === null) ? null : (converted as WorkoutItem[])
}

/** uid-free serialization used to detect unsaved changes. */
export function draftSnapshot(draft: WorkoutDraft): string {
  return JSON.stringify(draft, (key, value: unknown) => (key === 'uid' ? undefined : value))
}

// --- Pure list operations ------------------------------------------------

type ListOp = <T extends ItemDraft>(list: T[], index: number) => T[]

/** Apply `op` to whichever list (top level or a repeat's children) holds `uid`. */
function applyInContainingList(items: ItemDraft[], uid: string, op: ListOp): ItemDraft[] {
  const topIndex = items.findIndex((item) => item.uid === uid)
  if (topIndex >= 0) return op(items, topIndex)
  return items.map((item) => {
    if (item.kind !== 'repeat') return item
    const childIndex = item.steps.findIndex((step) => step.uid === uid)
    return childIndex < 0 ? item : { ...item, steps: op(item.steps, childIndex) }
  })
}

function cloneItem<T extends ItemDraft>(item: T): T {
  if (item.kind === 'step') return { ...item, uid: newUid() }
  const steps = item.steps.map((step) => ({ ...step, uid: newUid() }))
  return { ...item, uid: newUid(), steps } as T
}

/** Swap the item with its neighbour; no-op at either edge. */
export function moveItem(items: ItemDraft[], uid: string, direction: -1 | 1): ItemDraft[] {
  return applyInContainingList(items, uid, (list, index) => {
    const target = index + direction
    if (target < 0 || target >= list.length) return list
    const next = [...list]
    ;[next[index], next[target]] = [next[target], next[index]]
    return next
  })
}

/** Insert a copy (fresh uids) right after the item. */
export function duplicateItem(items: ItemDraft[], uid: string): ItemDraft[] {
  return applyInContainingList(items, uid, (list, index) => [
    ...list.slice(0, index + 1),
    cloneItem(list[index]),
    ...list.slice(index + 1),
  ])
}

export function removeItem(items: ItemDraft[], uid: string): ItemDraft[] {
  return applyInContainingList(items, uid, (list, index) => list.filter((_, i) => i !== index))
}

/** Merge `patch` into the step with `uid`, wherever it lives. */
export function updateStep(items: ItemDraft[], uid: string, patch: Partial<StepDraft>): ItemDraft[] {
  return applyInContainingList(items, uid, (list, index) =>
    list.map((item, i) => (i === index && item.kind === 'step' ? { ...item, ...patch } : item)),
  )
}

export function updateRepeatIterations(items: ItemDraft[], uid: string, iterationsText: string): ItemDraft[] {
  return items.map((item) => (item.uid === uid && item.kind === 'repeat' ? { ...item, iterationsText } : item))
}

/** Append a Run step inside the repeat block `uid`. */
export function addStepToRepeat(items: ItemDraft[], uid: string): ItemDraft[] {
  return items.map((item) =>
    item.uid === uid && item.kind === 'repeat'
      ? { ...item, steps: [...item.steps, createStep('run', { endType: 'distance' })] }
      : item,
  )
}
