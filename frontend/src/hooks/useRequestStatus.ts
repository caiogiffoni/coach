import { useState } from 'react'
import type { RequestStatus } from './requestStatus'

/** Fresh page-level busy/error state. Example: `const status = useRequestStatus()` */
export function useRequestStatus(): RequestStatus {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return { busy, setBusy, error, setError }
}
