import type { Dispatch, SetStateAction } from 'react'

/** Shared busy/error state that page-level hooks report into. */
export interface RequestStatus {
  busy: boolean
  setBusy: Dispatch<SetStateAction<boolean>>
  error: string | null
  setError: Dispatch<SetStateAction<string | null>>
}
