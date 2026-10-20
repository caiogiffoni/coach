// Battery / fartlek grouping for the workout builder: wrap a run of consecutive
// top-level steps into one repeat block, and unwrap a block back into steps.
// Single level only — the API contract forbids nested repeats. Kept apart from
// workoutBuilder.ts because it needs LIMITS, and workoutValidation imports
// workoutBuilder (a cycle otherwise).

import { newUid, parseWholeNumber } from './workoutBuilder'
import type { ItemDraft, RepeatDraft, StepDraft } from './workoutBuilder'
import { LIMITS } from './workoutValidation'

/** Iterations a fresh "Repeat" / "Group" starts with, like Garmin. */
export const DEFAULT_GROUP_ITERATIONS = 2

export type GroupCheck =
  | { ok: true; startIndex: number; endIndex: number }
  | { ok: false; reason: string }

/** The steps in items[startIndex..endIndex] (inclusive), or null when the range
    is out of bounds, holds a repeat block, or exceeds the repeat child limit. */
function stepsInRange(items: ItemDraft[], startIndex: number, endIndex: number): StepDraft[] | null {
  if (startIndex < 0 || endIndex >= items.length || startIndex > endIndex) return null
  const range = items.slice(startIndex, endIndex + 1)
  const steps = range.filter((item): item is StepDraft => item.kind === 'step')
  if (steps.length !== range.length || steps.length > LIMITS.repeatStepsMax) return null
  return steps
}

/**
 * Wrap items[startIndex..endIndex] (inclusive) into one repeat block, in place.
 * Child steps keep their uids. Returns `items` unchanged when the range can't
 * be grouped (out of bounds, contains a repeat, more than 20 steps).
 *
 * Example: `wrapItemsInRepeat(items, 1, 2, 6)` → items[1..2] become "Repeat 6×".
 */
export function wrapItemsInRepeat(
  items: ItemDraft[],
  startIndex: number,
  endIndex: number,
  iterations: number,
): ItemDraft[] {
  const steps = stepsInRange(items, startIndex, endIndex)
  if (steps === null) return items
  const repeat: RepeatDraft = { uid: newUid(), kind: 'repeat', iterationsText: String(iterations), steps }
  return [...items.slice(0, startIndex), repeat, ...items.slice(endIndex + 1)]
}

/**
 * Replace the repeat block at `index` with one copy of its child steps.
 * Returns `items` unchanged when `items[index]` is not a repeat.
 *
 * Example: `ungroupRepeat(items, 0)` → the block's steps now sit at 0..n-1.
 */
export function ungroupRepeat(items: ItemDraft[], index: number): ItemDraft[] {
  const item = items[index]
  if (item?.kind !== 'repeat') return items
  return [...items.slice(0, index), ...item.steps, ...items.slice(index + 1)]
}

/**
 * Whether the selected top-level items form one groupable run of steps, and
 * if not, a short reason to show next to the disabled "Group" button.
 *
 * Example: `const check = checkGroupSelection(items, new Set([a.uid, b.uid]))`
 */
export function checkGroupSelection(items: ItemDraft[], selectedUids: ReadonlySet<string>): GroupCheck {
  const indices = items.flatMap((item, i) => (selectedUids.has(item.uid) ? [i] : []))
  if (indices.length === 0) return { ok: false, reason: 'Select at least one step' }
  const startIndex = indices[0]
  const endIndex = indices[indices.length - 1]
  const range = items.slice(startIndex, endIndex + 1)
  if (range.some((item) => item.kind === 'repeat')) return { ok: false, reason: 'Selection includes a repeat block' }
  if (indices.length !== range.length) return { ok: false, reason: 'Select consecutive steps only' }
  if (range.length > LIMITS.repeatStepsMax) {
    return { ok: false, reason: `A repeat holds at most ${LIMITS.repeatStepsMax} steps` }
  }
  return { ok: true, startIndex, endIndex }
}

/** "6" → 6 when within the repeat limits (2..50), else null. */
export function parseGroupIterations(text: string): number | null {
  const n = parseWholeNumber(text)
  if (n === null || n < LIMITS.iterationsMin || n > LIMITS.iterationsMax) return null
  return n
}

/** Whether ungrouping the repeat at `index` keeps the list within the item limit. */
export function canUngroupRepeat(items: ItemDraft[], index: number): boolean {
  const item = items[index]
  if (item?.kind !== 'repeat') return false
  return items.length - 1 + item.steps.length <= LIMITS.itemsMax
}
