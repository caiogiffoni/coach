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
  }
}

export type WorkoutItemOps = ReturnType<typeof useWorkoutItemOps>
