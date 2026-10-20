import type { Dispatch, SetStateAction } from 'react'
import {
  addStepToRepeat,
  createRepeat,
  createStep,
  duplicateItem,
  moveItem,
  removeItem,
  updateRepeatIterations,
  updateStep,
} from '../workoutBuilder'
import type { ItemDraft, StepDraft, WorkoutDraft } from '../workoutBuilder'
import { DEFAULT_GROUP_ITERATIONS, checkGroupSelection, ungroupRepeat, wrapItemsInRepeat } from '../workoutGrouping'

function indexOfUid(items: ItemDraft[], uid: string): number {
  return items.findIndex((item) => item.uid === uid)
}

/** Wrap one top-level step into "Repeat 2×"; no-op for steps inside a repeat. */
function repeatSingleStep(items: ItemDraft[], uid: string): ItemDraft[] {
  const index = indexOfUid(items, uid)
  return index < 0 ? items : wrapItemsInRepeat(items, index, index, DEFAULT_GROUP_ITERATIONS)
}

/** Wrap the selected run of steps; resolved against the latest items, so a
    stale selection that is no longer contiguous is a no-op. */
function groupSelection(items: ItemDraft[], uids: ReadonlySet<string>, iterations: number): ItemDraft[] {
  const check = checkGroupSelection(items, uids)
  return check.ok ? wrapItemsInRepeat(items, check.startIndex, check.endIndex, iterations) : items
}

/**
 * Bind the pure step/repeat list operations to the editor's draft state.
 *
 * Example: `const ops = useWorkoutItemOps(setDraft); ops.move(uid, -1)`
 */
export function useWorkoutItemOps(setDraft: Dispatch<SetStateAction<WorkoutDraft>>) {
  function applyItems(change: (items: ItemDraft[]) => ItemDraft[]) {
    setDraft((d) => ({ ...d, items: change(d.items) }))
  }

  return {
    addStep: () => applyItems((items) => [...items, createStep('run', { endType: 'distance' })]),
    addRepeat: () => applyItems((items) => [...items, createRepeat()]),
    addStepToRepeat: (uid: string) => applyItems((items) => addStepToRepeat(items, uid)),
    move: (uid: string, direction: -1 | 1) => applyItems((items) => moveItem(items, uid, direction)),
    duplicate: (uid: string) => applyItems((items) => duplicateItem(items, uid)),
    remove: (uid: string) => applyItems((items) => removeItem(items, uid)),
    updateStep: (uid: string, patch: Partial<StepDraft>) => applyItems((items) => updateStep(items, uid, patch)),
    setIterations: (uid: string, text: string) => applyItems((items) => updateRepeatIterations(items, uid, text)),
    repeatStep: (uid: string) => applyItems((items) => repeatSingleStep(items, uid)),
    groupSteps: (uids: ReadonlySet<string>, iterations: number) =>
      applyItems((items) => groupSelection(items, uids, iterations)),
    ungroup: (uid: string) => applyItems((items) => ungroupRepeat(items, indexOfUid(items, uid))),
  }
}

export type WorkoutItemOps = ReturnType<typeof useWorkoutItemOps>
