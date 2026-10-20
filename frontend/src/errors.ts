import { ApiError } from './api'

/**
 * Human-readable message for a failed API call.
 *
 * Example: `setError(errorMessage(err, 'Save failed'))`
 */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}
