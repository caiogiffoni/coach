import { useEffect, useState } from 'react'
import { ApiError, coaching, garmin } from '../api'
import { errorMessage } from '../errors'
import { verifyGarminMfa } from '../garminLogin'
import type { PushReport, WeekPlan } from '../types'
import type { RequestStatus } from './requestStatus'

interface GarminPushInput {
  weekStart: string
  setPlan: (plan: WeekPlan) => void
  status: RequestStatus
}

function isMfaChallenge(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && err.message.toLowerCase().includes('mfa')
}

/**
 * Push the approved week to Garmin, handling the MFA challenge.
 *
 * Example: `const push = useGarminPush({ weekStart, setPlan, status }); push.executePush()`
 */
export function useGarminPush({ weekStart, setPlan, status }: GarminPushInput) {
  const [pushReport, setPushReport] = useState<PushReport | null>(null)
  const [needsMfa, setNeedsMfa] = useState(false)
  const [mfaCode, setMfaCode] = useState('')

  // A push report belongs to the week it was produced for.
  useEffect(() => {
    setPushReport(null)
  }, [weekStart])

  async function executePush() {
    status.setBusy(true)
    status.setError(null)
    setPushReport(null)
    setNeedsMfa(false)
    try {
      setPushReport(await garmin.push(weekStart))
      // Refresh plan so the status becomes "pushed".
      setPlan(await coaching.getWeek(weekStart))
    } catch (err) {
      if (isMfaChallenge(err)) setNeedsMfa(true)
      else status.setError(errorMessage(err, 'Push failed'))
    } finally {
      status.setBusy(false)
    }
  }

  async function submitMfa() {
    if (!mfaCode) return
    status.setBusy(true)
    status.setError(null)
    try {
      if (!(await verifyGarminMfa(mfaCode, status.setError))) return
      setNeedsMfa(false)
      setMfaCode('')
      await executePush()
    } catch (err) {
      status.setError(errorMessage(err, 'MFA login failed'))
    } finally {
      status.setBusy(false)
    }
  }

  function cancelMfa() {
    setNeedsMfa(false)
    setMfaCode('')
  }

  return { pushReport, needsMfa, mfaCode, setMfaCode, executePush, submitMfa, cancelMfa }
}
