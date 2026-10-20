import { useState } from 'react'
import { ApiError } from '../api'
import { errorMessage } from '../errors'
import { verifyGarminMfa } from '../garminLogin'
import type { RequestStatus } from './requestStatus'

/** True when a Garmin call failed because Garmin wants an MFA code. */
export function isMfaChallenge(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && err.message.toLowerCase().includes('mfa')
}

/**
 * Garmin MFA prompt state shared by every Garmin push: show the prompt on a
 * challenge, verify the code, then re-run the original action.
 *
 * Example: `const mfa = useGarminMfa(status); mfa.submitMfa(() => executePush())`
 */
export function useGarminMfa(status: RequestStatus) {
  const [needsMfa, setNeedsMfa] = useState(false)
  const [mfaCode, setMfaCode] = useState('')

  async function submitMfa(retry: () => Promise<void>) {
    if (!mfaCode) return
    status.setBusy(true)
    status.setError(null)
    try {
      if (!(await verifyGarminMfa(mfaCode, status.setError))) return
      setNeedsMfa(false)
      setMfaCode('')
      await retry()
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

  return { needsMfa, setNeedsMfa, mfaCode, setMfaCode, submitMfa, cancelMfa }
}
