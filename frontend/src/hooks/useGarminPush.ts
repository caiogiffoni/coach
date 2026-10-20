import { useEffect, useState } from 'react'
import { coaching, garmin } from '../api'
import { errorMessage } from '../errors'
import type { PushReport, WeekPlan } from '../types'
import { isMfaChallenge, useGarminMfa } from './useGarminMfa'
import type { RequestStatus } from './requestStatus'

interface GarminPushInput {
  weekStart: string
  setPlan: (plan: WeekPlan) => void
  status: RequestStatus
}

/**
 * Push the approved week to Garmin, handling the MFA challenge.
 *
 * Example: `const push = useGarminPush({ weekStart, setPlan, status }); push.executePush()`
 */
export function useGarminPush({ weekStart, setPlan, status }: GarminPushInput) {
  const [pushReport, setPushReport] = useState<PushReport | null>(null)
  const mfa = useGarminMfa(status)

  // A push report belongs to the week it was produced for.
  useEffect(() => {
    setPushReport(null)
  }, [weekStart])

  async function executePush() {
    status.setBusy(true)
    status.setError(null)
    setPushReport(null)
    mfa.setNeedsMfa(false)
    try {
      setPushReport(await garmin.push(weekStart))
      // Refresh plan so the status becomes "pushed".
      setPlan(await coaching.getWeek(weekStart))
    } catch (err) {
      if (isMfaChallenge(err)) mfa.setNeedsMfa(true)
      else status.setError(errorMessage(err, 'Push failed'))
    } finally {
      status.setBusy(false)
    }
  }

  return {
    pushReport,
    needsMfa: mfa.needsMfa,
    mfaCode: mfa.mfaCode,
    setMfaCode: mfa.setMfaCode,
    executePush,
    submitMfa: () => mfa.submitMfa(executePush),
    cancelMfa: mfa.cancelMfa,
  }
}
