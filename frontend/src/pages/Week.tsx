import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, coaching, garmin, ingestion, profile } from '../api'
import { DayCard } from '../components/DayCard'
import {
  addDays,
  fromISODate,
  mondayOf,
  nextMonday,
  toISODate,
  WEEKDAY_NAMES,
} from '../format'
import type {
  DayGuardResult,
  GarminStatus,
  IngestionStatus,
  PushReport,
  SyncReport,
  WeekPlan,
} from '../types'

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-muted',
  approved: 'badge-success',
  pushed: 'badge-success',
}

function daysBetween(isoA: string, isoB: string): number {
  const a = fromISODate(isoA).getTime()
  const b = fromISODate(isoB).getTime()
  return Math.round((b - a) / (1000 * 60 * 60 * 24))
}

function todayIso(): string {
  return toISODate(new Date())
}

export function Week() {
  const [weekStart, setWeekStart] = useState<string>(() => toISODate(nextMonday()))
  const [plan, setPlan] = useState<WeekPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Generate panel state
  const [notes, setNotes] = useState('')
  const [days, setDays] = useState<number[]>([])

  // Garmin push state
  const [garminStatus, setGarminStatus] = useState<GarminStatus | null>(null)
  const [pushReport, setPushReport] = useState<PushReport | null>(null)
  const [needsMfa, setNeedsMfa] = useState(false)
  const [mfaCode, setMfaCode] = useState('')

  // Sync + staleness state
  const [ingestionStatus, setIngestionStatus] = useState<IngestionStatus | null>(null)
  const [syncReport, setSyncReport] = useState<SyncReport | null>(null)
  const [syncNeedsMfa, setSyncNeedsMfa] = useState(false)
  const [syncMfaCode, setSyncMfaCode] = useState('')

  // Per-day guard results
  const [guardByDate, setGuardByDate] = useState<Record<string, DayGuardResult>>({})

  // Initialize run-day checkboxes from the profile's preferred days.
  useEffect(() => {
    profile
      .get()
      .then((p) => setDays([...p.preferred_days].sort()))
      .catch(() => {})
  }, [])

  const loadPlan = useCallback(async (week: string) => {
    setLoading(true)
    setError(null)
    setPushReport(null)
    try {
      const p = await coaching.getWeek(week)
      setPlan(p)
      setNotes(p.notes)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlan(null)
        setNotes('')
      } else {
        setError(err instanceof ApiError ? err.message : 'Failed to load week')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const loadStaleness = useCallback(async () => {
    try {
      const status = await ingestion.status()
      setIngestionStatus(status)
    } catch {
      setIngestionStatus(null)
    }
  }, [])

  useEffect(() => {
    loadPlan(weekStart)
    loadStaleness()
  }, [weekStart, loadPlan, loadStaleness])

  useEffect(() => {
    garmin
      .status()
      .then((s) => setGarminStatus(s))
      .catch(() => setGarminStatus(null))
  }, [weekStart])

  // Auto-sync on open if Garmin is configured.
  useEffect(() => {
    if (!garminStatus?.configured || syncReport || syncNeedsMfa) return
    executeSync(false).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [garminStatus?.configured])

  // Fetch guard results for every day that has a planned workout.
  useEffect(() => {
    if (!plan) {
      setGuardByDate({})
      return
    }
    let cancelled = false
    const today = todayIso()
    Promise.all(
      plan.workouts.map(async (w) => {
        if (w.date > today) return null
        try {
          return await coaching.guard(weekStart, w.date)
        } catch {
          return null
        }
      }),
    ).then((results) => {
      if (cancelled) return
      const byDate: Record<string, DayGuardResult> = {}
      for (const r of results) {
        if (r) byDate[r.date] = r
      }
      setGuardByDate(byDate)
    })
    return () => {
      cancelled = true
    }
  }, [plan, weekStart])

  function pickWeek(value: string) {
    if (!value) return
    setWeekStart(toISODate(mondayOf(fromISODate(value))))
  }

  function shiftWeek(offset: number) {
    setWeekStart(toISODate(addDays(fromISODate(weekStart), offset * 7)))
  }

  function toggleDay(day: number) {
    setDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort(),
    )
  }

  async function run(action: () => Promise<WeekPlan>) {
    setBusy(true)
    setError(null)
    try {
      setPlan(await action())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  const generate = () =>
    run(() =>
      coaching.generateWeek({
        week: weekStart,
        days: days.length > 0 ? days : undefined,
        notes: notes.trim() || undefined,
      }),
    )

  const regenerateDay = (date: string) =>
    run(() => coaching.generateWeek({ week: weekStart, day_date: date }))

  const regenerateFromGuard = (date: string, reason: string) =>
    run(() =>
      coaching.generateWeek({
        week: weekStart,
        day_date: date,
        notes: [notes.trim(), `Guard: ${reason}`].filter(Boolean).join(' — '),
      }),
    )

  const approve = () => run(() => coaching.approveWeek(weekStart))

  async function executePush() {
    setBusy(true)
    setError(null)
    setPushReport(null)
    setNeedsMfa(false)
    try {
      const report = await garmin.push(weekStart)
      setPushReport(report)
      // Refresh plan so the status becomes "pushed".
      const p = await coaching.getWeek(weekStart)
      setPlan(p)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && err.message.toLowerCase().includes('mfa')) {
        setNeedsMfa(true)
      } else {
        setError(err instanceof ApiError ? err.message : 'Push failed')
      }
    } finally {
      setBusy(false)
    }
  }

  async function submitMfa() {
    if (!mfaCode) return
    setBusy(true)
    setError(null)
    try {
      const result = await garmin.login(mfaCode)
      if (!result.success && result.needs_mfa) {
        setError(result.message || 'MFA required')
        return
      }
      if (!result.success) {
        setError(result.message || 'Login failed')
        return
      }
      setNeedsMfa(false)
      setMfaCode('')
      await executePush()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'MFA login failed')
    } finally {
      setBusy(false)
    }
  }

  async function executeSync(showError = true) {
    setBusy(true)
    setError(showError ? null : error)
    setSyncReport(null)
    setSyncNeedsMfa(false)
    try {
      const report = await ingestion.sync()
      setSyncReport(report)
      await loadStaleness()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        try {
          const body = JSON.parse(err.message)
          if (body?.needs_mfa) {
            setSyncNeedsMfa(true)
            return
          }
        } catch {
          // fall through
        }
      }
      if (showError) {
        setError(err instanceof ApiError ? err.message : 'Sync failed')
      }
    } finally {
      setBusy(false)
    }
  }

  async function submitSyncMfa() {
    if (!syncMfaCode) return
    setBusy(true)
    setError(null)
    try {
      const result = await garmin.login(syncMfaCode)
      if (!result.success && result.needs_mfa) {
        setError(result.message || 'MFA required')
        return
      }
      if (!result.success) {
        setError(result.message || 'Login failed')
        return
      }
      setSyncNeedsMfa(false)
      setSyncMfaCode('')
      await executeSync()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'MFA login failed')
    } finally {
      setBusy(false)
    }
  }

  const draft = plan?.status === 'draft'
  const approved = plan?.status === 'approved'
  const weekDates = Array.from({ length: 7 }, (_, i) =>
    toISODate(addDays(fromISODate(weekStart), i)),
  )

  const garminConfigured = garminStatus?.configured ?? false

  const stalenessText = useMemo(() => {
    const newest = syncReport?.newest_date ?? ingestionStatus?.newest_date
    if (!newest) return null
    const age = daysBetween(newest, todayIso())
    if (age === 0) return `Data as of ${newest} (today)`
    return `Data as of ${newest} (${age} day${age === 1 ? '' : 's'} old)`
  }, [syncReport, ingestionStatus])

  return (
    <>
      <div className="page-header">
        <h1>Week</h1>
        {draft && (
          <div className="row">
            <button
              type="button"
              className="button button-secondary"
              onClick={generate}
              disabled={busy}
            >
              Regenerate
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={approve}
              disabled={busy}
            >
              Approve
            </button>
          </div>
        )}
        {approved && (
          <button
            type="button"
            className="button button-primary"
            onClick={executePush}
            disabled={busy || !garminConfigured}
            title={
              garminConfigured
                ? 'Push this week to Garmin Connect'
                : 'Garmin credentials not configured'
            }
          >
            Push to Garmin
          </button>
        )}
      </div>

      <div className="week-controls">
        <button
          type="button"
          className="icon-button"
          onClick={() => shiftWeek(-1)}
          aria-label="Previous week"
        >
          <ChevronLeft size={20} strokeWidth={1.5} />
        </button>
        <input
          type="date"
          className="input"
          style={{ width: 'auto' }}
          value={weekStart}
          onChange={(e) => pickWeek(e.target.value)}
          aria-label="Week (any date; snapped to Monday)"
        />
        <button
          type="button"
          className="icon-button"
          onClick={() => shiftWeek(1)}
          aria-label="Next week"
        >
          <ChevronRight size={20} strokeWidth={1.5} />
        </button>
        {plan && (
          <span className={`badge ${STATUS_BADGE[plan.status] ?? 'badge-muted'}`}>
            {plan.status}
          </span>
        )}
      </div>

      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
          {error.includes('Profile not found') && (
            <>
              {' '}
              <Link to="/profile">Create your profile</Link>
            </>
          )}
          {error.includes('No imported data') && (
            <>
              {' '}
              <Link to="/data">Import data</Link>
            </>
          )}
        </div>
      )}
      {garminStatus && !garminStatus.configured && (
        <div className="banner banner-warning" role="alert">
          Garmin credentials not configured. Push to Garmin and auto-sync are
          disabled until GARMIN_EMAIL and GARMIN_PASSWORD are set on the backend.
        </div>
      )}
      {stalenessText && (
        <div className="banner banner-info" role="status">
          {stalenessText}
        </div>
      )}
      {plan?.source === 'fallback' && (
        <div className="banner banner-warning">
          LLM unavailable — built from template.
        </div>
      )}
      {plan && plan.validation_errors.length > 0 && (
        <div className="banner banner-danger" role="alert">
          Validation errors
          <ul>
            {plan.validation_errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {(needsMfa || syncNeedsMfa) && (
        <section className="section">
          <div className="card">
            <h2 className="card-title">Garmin two-factor authentication</h2>
            <p className="field-hint" style={{ marginBottom: 12 }}>
              Enter the MFA code from your authenticator app to continue.
            </p>
            <div className="field">
              <label className="field-label" htmlFor="mfa-code">
                MFA code
              </label>
              <input
                id="mfa-code"
                className="input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={syncNeedsMfa ? syncMfaCode : mfaCode}
                onChange={(e) =>
                  syncNeedsMfa ? setSyncMfaCode(e.target.value) : setMfaCode(e.target.value)
                }
                onKeyDown={(e) =>
                  e.key === 'Enter' && (syncNeedsMfa ? submitSyncMfa() : submitMfa())
                }
              />
            </div>
            <div className="form-actions">
              <button
                type="button"
                className="button button-primary"
                onClick={syncNeedsMfa ? submitSyncMfa : submitMfa}
                disabled={busy || !(syncNeedsMfa ? syncMfaCode : mfaCode)}
              >
                Verify and continue
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  setNeedsMfa(false)
                  setSyncNeedsMfa(false)
                  setMfaCode('')
                  setSyncMfaCode('')
                }}
                disabled={busy}
              >
                Cancel
              </button>
            </div>
          </div>
        </section>
      )}

      {syncReport && (
        <section className="section">
          <div className="card">
            <h2 className="card-title">Sync report</h2>
            <div className="sync-grid">
              <div>
                <span className="field-label">Activities</span>
                <p className="mono">{syncReport.activities}</p>
              </div>
              <div>
                <span className="field-label">Wellness</span>
                <p className="mono">{syncReport.daily_wellness}</p>
              </div>
              <div>
                <span className="field-label">HRV</span>
                <p className="mono">{syncReport.hrv}</p>
              </div>
              <div>
                <span className="field-label">Readiness</span>
                <p className="mono">{syncReport.training_readiness}</p>
              </div>
              <div>
                <span className="field-label">Load</span>
                <p className="mono">{syncReport.training_load}</p>
              </div>
            </div>
            {syncReport.skipped_datasets.length > 0 && (
              <div className="field">
                <span className="field-label">Skipped datasets</span>
                <p className="mono">{syncReport.skipped_datasets.join(', ')}</p>
              </div>
            )}
            {syncReport.newest_date && (
              <div className="field">
                <span className="field-label">Newest date</span>
                <p className="mono">{syncReport.newest_date}</p>
              </div>
            )}
          </div>
        </section>
      )}

      {pushReport && (
        <section className="section">
          <div className="card">
            <h2 className="card-title">Push report</h2>
            {pushReport.pushed_dates.length > 0 && (
              <div className="field">
                <span className="field-label">Pushed</span>
                <p className="mono">{pushReport.pushed_dates.join(', ')}</p>
              </div>
            )}
            {pushReport.skipped_dates.length > 0 && (
              <div className="field">
                <span className="field-label">Skipped</span>
                <ul>
                  {pushReport.skipped_dates.map((s, i) => (
                    <li key={i}>
                      <span className="mono">{s.date}</span> — {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {pushReport.errors.length > 0 && (
              <div className="field">
                <span className="field-label">Errors</span>
                <ul>
                  {pushReport.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {pushReport.pushed_dates.length === 0 &&
              pushReport.skipped_dates.length === 0 &&
              pushReport.errors.length === 0 && (
                <p className="muted">No workouts to push.</p>
              )}
          </div>
        </section>
      )}

      <section className="section">
        <div className="card">
          <div className="card-header-row">
            <h2 className="card-title">Generate week</h2>
            <button
              type="button"
              className="button button-secondary button-compact"
              onClick={() => executeSync()}
              disabled={busy}
              title="Pull recent data from Garmin Connect"
            >
              <RotateCcw size={14} strokeWidth={1.5} />
              Sync now
            </button>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="notes">
              Notes to the coach
            </label>
            <textarea
              id="notes"
              className="textarea"
              placeholder="e.g. legs heavy after Sunday's long run; travel on Thursday"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="field">
            <span className="field-label">Run days</span>
            <div className="checkbox-row">
              {WEEKDAY_NAMES.map((name, i) => (
                <label className="checkbox-label" key={name}>
                  <input
                    type="checkbox"
                    checked={days.includes(i)}
                    onChange={() => toggleDay(i)}
                  />
                  {name}
                </label>
              ))}
            </div>
            <p className="field-hint">Defaults come from your profile's preferred days.</p>
          </div>
          <div className="form-actions">
            <button
              type="button"
              className="button button-primary"
              onClick={generate}
              disabled={busy || days.length === 0}
            >
              {plan ? 'Regenerate week' : 'Generate week'}
            </button>
          </div>
        </div>
      </section>

      <section className="section">
        {loading ? (
          <p className="muted">Loading…</p>
        ) : plan ? (
          <div className="week-grid">
            {weekDates.map((date, i) => (
              <DayCard
                key={date}
                date={date}
                weekday={i}
                workout={plan.workouts.find((w) => w.date === date) ?? null}
                draft={draft}
                busy={busy}
                guard={guardByDate[date] ?? null}
                onRegenerateDay={regenerateDay}
                onRegenerateFromGuard={regenerateFromGuard}
              />
            ))}
          </div>
        ) : (
          <div className="card empty-state">
            <p>No plan for this week yet.</p>
            <button
              type="button"
              className="button button-primary"
              onClick={generate}
              disabled={busy || days.length === 0}
            >
              Generate week
            </button>
          </div>
        )}
      </section>
    </>
  )
}
