import { useCallback, useEffect, useState } from 'react'
import { workoutLibrary } from '../api'
import { errorMessage } from '../errors'
import type { LibraryWorkoutSummary } from '../types'
import type { RequestStatus } from './requestStatus'

/**
 * Saved workouts list plus duplicate/delete actions.
 *
 * Example: `const library = useWorkoutLibrary(status); library.duplicate(3)`
 */
export function useWorkoutLibrary(status: RequestStatus) {
  const [workouts, setWorkouts] = useState<LibraryWorkoutSummary[]>([])
  const [loading, setLoading] = useState(true)
  const { setBusy, setError } = status

  const reload = useCallback(async () => {
    try {
      setWorkouts(await workoutLibrary.list())
    } catch (err) {
      setError(errorMessage(err, 'Failed to load workouts'))
    } finally {
      setLoading(false)
    }
  }, [setError])

  useEffect(() => {
    reload()
  }, [reload])

  async function runAction(action: () => Promise<unknown>, fallback: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(errorMessage(err, fallback))
    } finally {
      setBusy(false)
    }
  }

  return {
    workouts,
    loading,
    reload,
    duplicate: (id: number) => runAction(() => workoutLibrary.duplicate(id), 'Duplicate failed'),
    remove: (id: number) => runAction(() => workoutLibrary.remove(id), 'Delete failed'),
  }
}
