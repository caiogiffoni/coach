import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, ingestion } from '../api'
import { errorMessage } from '../errors'
import { fromISODate, toISODate } from '../format'
import { verifyGarminMfa } from '../garminLogin'
import type { IngestionStatus, SyncReport } from '../types'
import type { RequestStatus } from './requestStatus'

interface GarminSyncInput {
  weekStart: string
  garminConfigured: boolean | undefined
  status: RequestStatus
}

function daysBetween(isoA: string, isoB: string): number {
  const a = fromISODate(isoA).getTime()
  const b = fromISODate(isoB).getTime()
  return Math.round((b - a) / (1000 * 60 * 60 * 24))
}

function syncNeedsMfaFrom(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 401) return false
  try {
    return Boolean(JSON.parse(err.message)?.needs_mfa)
  } catch {
    return false
  }
}

function stalenessLabel(newest: string | null | undefined): string | null {
  if (!newest) return null
  const age = daysBetween(newest, toISODate(new Date()))
  if (age === 0) return `Data as of ${newest} (today)`
  return `Data as of ${newest} (${age} day${age === 1 ? '' : 's'} old)`
}

/**
 * Garmin data sync (auto on open when configured) plus data staleness.
 *
 * Example: `const sync = useGarminSync({ weekStart, garminConfigured, status })`
 */
export function useGarminSync({ weekStart, garminConfigured, status }: GarminSyncInput) {
  const [ingestionStatus, setIngestionStatus] = useState<IngestionStatus | null>(null)
  const [syncReport, setSyncReport] = useState<SyncReport | null>(null)
  const [syncNeedsMfa, setSyncNeedsMfa] = useState(false)
  const [syncMfaCode, setSyncMfaCode] = useState('')

  const loadStaleness = useCallback(async () => {
    try {
      setIngestionStatus(await ingestion.status())
    } catch {
      setIngestionStatus(null)
    }
  }, [])

  useEffect(() => {
    loadStaleness()
  }, [weekStart, loadStaleness])

  async function executeSync(showError = true) {
    status.setBusy(true)
    status.setError((prev) => (showError ? null : prev))
    setSyncReport(null)
    setSyncNeedsMfa(false)
    try {
      setSyncReport(await ingestion.sync())
      await loadStaleness()
    } catch (err) {
      if (syncNeedsMfaFrom(err)) setSyncNeedsMfa(true)
      else if (showError) status.setError(errorMessage(err, 'Sync failed'))
    } finally {
      status.setBusy(false)
    }
  }

  // Auto-sync on open if Garmin is configured.
  useEffect(() => {
    if (!garminConfigured || syncReport || syncNeedsMfa) return
    executeSync(false).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [garminConfigured])

  async function submitSyncMfa() {
    if (!syncMfaCode) return
    status.setBusy(true)
    status.setError(null)
    try {
      if (!(await verifyGarminMfa(syncMfaCode, status.setError))) return
      setSyncNeedsMfa(false)
      setSyncMfaCode('')
      await executeSync()
    } catch (err) {
      status.setError(errorMessage(err, 'MFA login failed'))
    } finally {
      status.setBusy(false)
    }
  }

  function cancelSyncMfa() {
    setSyncNeedsMfa(false)
    setSyncMfaCode('')
  }

  const stalenessText = useMemo(
    () => stalenessLabel(syncReport?.newest_date ?? ingestionStatus?.newest_date),
    [syncReport, ingestionStatus],
  )

  return {
    syncReport,
    syncNeedsMfa,
    syncMfaCode,
    setSyncMfaCode,
    executeSync,
    submitSyncMfa,
    cancelSyncMfa,
    stalenessText,
  }
}
