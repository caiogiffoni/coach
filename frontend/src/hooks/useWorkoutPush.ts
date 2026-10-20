import { useState } from 'react'
import { workoutLibrary } from '../api'
import { errorMessage } from '../errors'
import type { LibraryWorkoutPush } from '../types'
import { isMfaChallenge, useGarminMfa } from './useGarminMfa'
import type { RequestStatus } from './requestStatus'

export interface WorkoutPushResult {
  workoutId: number
  push: LibraryWorkoutPush
}

/**
 * Schedule a saved library workout on a Garmin calendar date, reusing the
 * week push's MFA handling; the pending push is retried after MFA.
 *
 * Example: `const push = useWorkoutPush({ status, onPushed: reload }); push.executePush(3, '2026-10-20')`
 */
export function useWorkoutPush({ status, onPushed }: { status: RequestStatus; onPushed?: () => void }) {
  const [lastPush, setLastPush] = useState<WorkoutPushResult | null>(null)
  const [pending, setPending] = useState<{ id: number; date: string } | null>(null)
  const mfa = useGarminMfa(status)

  async function executePush(id: number, date: string) {
    status.setBusy(true)
    status.setError(null)
    setLastPush(null)
    setPending({ id, date })
    mfa.setNeedsMfa(false)
    try {
      setLastPush({ workoutId: id, push: await workoutLibrary.push(id, date) })
      onPushed?.()
    } catch (err) {
      if (isMfaChallenge(err)) mfa.setNeedsMfa(true)
      else status.setError(errorMessage(err, 'Push failed'))
    } finally {
      status.setBusy(false)
    }
  }

  function submitMfa() {
    if (!pending) return
    return mfa.submitMfa(() => executePush(pending.id, pending.date))
  }

  return {
    lastPush,
    needsMfa: mfa.needsMfa,
    mfaCode: mfa.mfaCode,
    setMfaCode: mfa.setMfaCode,
    executePush,
    submitMfa,
    cancelMfa: mfa.cancelMfa,
  }
}
