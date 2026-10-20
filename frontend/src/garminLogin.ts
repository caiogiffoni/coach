import { garmin } from './api'

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
