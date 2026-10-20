import { useEffect, useEffectEvent, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { workoutLibrary } from '../api'
import { errorMessage } from '../errors'
import type { LibraryWorkout } from '../types'
import { createDefaultDraft, draftSnapshot, draftsToItems, itemsToDrafts } from '../workoutBuilder'
import type { WorkoutDraft } from '../workoutBuilder'
import { estimateWorkout, expandedStepCount } from '../workoutEstimate'
import { hasDraftErrors, validateDraft } from '../workoutValidation'
import { useRequestStatus } from './useRequestStatus'
import { useUnsavedChangesPrompt } from './useUnsavedChangesPrompt'
import { useWorkoutItemOps } from './useWorkoutItemOps'

function workoutToDraft(workout: LibraryWorkout): WorkoutDraft {
  return { name: workout.name, description: workout.description, items: itemsToDrafts(workout.steps) }
}

/** Load `/workouts/:id` (or start a new draft) and track the saved baseline. */
function useLoadedWorkout(id: number | null, onLoaded: (draft: WorkoutDraft) => void, setError: (e: string) => void) {
  const [workout, setWorkout] = useState<LibraryWorkout | null>(null)
  const [loading, setLoading] = useState(id !== null)
  const handleLoaded = useEffectEvent((w: LibraryWorkout) => onLoaded(workoutToDraft(w)))
  const handleError = useEffectEvent((err: unknown) => setError(errorMessage(err, 'Failed to load workout')))

  useEffect(() => {
    if (id === null) return
    setLoading(true)
    workoutLibrary
      .get(id)
      .then((w) => {
        setWorkout(w)
        handleLoaded(w)
      })
      .catch(handleError)
      .finally(() => setLoading(false))
  }, [id])

  return { workout, loading, setWorkout }
}

/**
 * Editor state for one library workout: draft, live estimate/validation,
 * unsaved-changes tracking and save (POST for new, PUT for existing).
 *
 * Example: `const editor = useWorkoutEditor(params.id); editor.ops.addRepeat()`
 */
export function useWorkoutEditor(idParam: string | undefined) {
  const id = idParam === undefined ? null : Number(idParam)
  const navigate = useNavigate()
  const location = useLocation()
  const status = useRequestStatus()
  const [initialDraft] = useState(createDefaultDraft)
  const [draft, setDraft] = useState<WorkoutDraft>(initialDraft)
  // New workouts start "clean" so leaving an untouched form doesn't prompt.
  const [savedSnapshot, setSavedSnapshot] = useState(() => draftSnapshot(initialDraft))
  // A create navigates to /workouts/:id (remounting the page), carrying the flag.
  const [saved, setSaved] = useState(() => Boolean((location.state as { saved?: boolean } | null)?.saved))

  function resetTo(next: WorkoutDraft) {
    setDraft(next)
    setSavedSnapshot(draftSnapshot(next))
  }

  const loaded = useLoadedWorkout(id, resetTo, status.setError)
  const ops = useWorkoutItemOps(setDraft)
  const errors = useMemo(() => validateDraft(draft), [draft])
  const wireItems = useMemo(() => draftsToItems(draft.items), [draft.items])
  const estimate = useMemo(() => estimateWorkout(wireItems ?? []), [wireItems])
  const dirty = draftSnapshot(draft) !== savedSnapshot
  useUnsavedChangesPrompt(dirty)

  function updateMeta(patch: Partial<Pick<WorkoutDraft, 'name' | 'description'>>) {
    setDraft((d) => ({ ...d, ...patch }))
  }

  async function save() {
    if (hasDraftErrors(errors) || wireItems === null) {
      status.setError('Fix the highlighted fields before saving.')
      return
    }
    status.setBusy(true)
    status.setError(null)
    const body = { name: draft.name.trim(), description: draft.description, steps: wireItems }
    try {
      const result = id === null ? await workoutLibrary.create(body) : await workoutLibrary.update(id, body)
      loaded.setWorkout(result)
      resetTo(workoutToDraft(result))
      setSaved(true)
      if (id === null) navigate(`/workouts/${result.id}`, { replace: true, state: { saved: true } })
    } catch (err) {
      status.setError(errorMessage(err, 'Save failed'))
    } finally {
      status.setBusy(false)
    }
  }

  /** Re-read the saved workout (e.g. to show a new push). */
  async function refresh() {
    if (id === null) return
    try {
      loaded.setWorkout(await workoutLibrary.get(id))
    } catch (err) {
      status.setError(errorMessage(err, 'Failed to refresh workout'))
    }
  }

  return {
    isNew: id === null,
    workout: loaded.workout,
    loading: loaded.loading,
    draft,
    updateMeta,
    ops,
    errors,
    estimate,
    stepCount: wireItems === null ? null : expandedStepCount(wireItems),
    dirty: dirty || id === null,
    saved: saved && !dirty,
    status,
    save,
    refresh,
  }
}
