import { garmin } from './api'
import type { GarminStatus } from './types'

/**
 * Submit a Garmin MFA code; reports failure through `onFailure`.
 *
 * Example: `if (await verifyGarminMfa(code, setError)) await retry()`
 */
export async function verifyGarminMfa(
  code: string,
  onFailure: (message: string) => void,
): Promise<boolean> {
  const result = await garmin.login(code)
  if (!result.success && result.needs_mfa) {
    onFailure(result.message || 'MFA required')
    return false
  }
  if (!result.success) {
    onFailure(result.message || 'Login failed')
    return false
  }
  return true
}

/**
 * Why a Garmin push is unavailable, or null when configured (or still unknown).
 *
 * Example: `disabled={garminPushDisabledReason(garminStatus) !== null}`
 */
export function garminPushDisabledReason(garminStatus: GarminStatus | null): string | null {
  return garminStatus && !garminStatus.configured ? 'Garmin credentials not configured' : null
}
