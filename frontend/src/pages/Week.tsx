import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, coaching, garmin, profile } from '../api'
import { DayCard } from '../components/DayCard'
import {
  addDays,
  fromISODate,
  mondayOf,
  nextMonday,
  toISODate,
  WEEKDAY_NAMES,
} from '../format'
import type { GarminStatus, PushReport, WeekPlan } from '../types'

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-muted',
  approved: 'badge-success',
  pushed: 'badge-success',
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

  useEffect(() => {
    loadPlan(weekStart)
  }, [weekStart, loadPlan])

  useEffect(() => {
    garmin
      .status()
      .then((s) => setGarminStatus(s))
      .catch(() => setGarminStatus(null))
  }, [weekStart])

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

  const draft = plan?.status === 'draft'
  const approved = plan?.status === 'approved'
  const weekDates = Array.from({ length: 7 }, (_, i) =>
    toISODate(addDays(fromISODate(weekStart), i)),
  )

  const garminConfigured = garminStatus?.configured ?? false

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
          Garmin credentials not configured. Push to Garmin is disabled until
          GARMIN_EMAIL and GARMIN_PASSWORD are set on the backend.
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

      {needsMfa && (
        <section className="section">
          <div className="card">
            <h2 className="card-title">Garmin two-factor authentication</h2>
            <p className="field-hint" style={{ marginBottom: 12 }}>
              Enter the MFA code from your authenticator app to continue the push.
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
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submitMfa()}
              />
            </div>
            <div className="form-actions">
              <button
                type="button"
                className="button button-primary"
                onClick={submitMfa}
                disabled={busy || !mfaCode}
              >
                Verify and push
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  setNeedsMfa(false)
                  setMfaCode('')
                }}
                disabled={busy}
              >
                Cancel
              </button>
            </div>
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
          <h2 className="card-title">Generate week</h2>
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
                onRegenerateDay={regenerateDay}
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
