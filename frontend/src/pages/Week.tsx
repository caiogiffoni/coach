import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, coaching, profile } from '../api'
import { DayCard } from '../components/DayCard'
import {
  addDays,
  fromISODate,
  mondayOf,
  nextMonday,
  toISODate,
  WEEKDAY_NAMES,
} from '../format'
import type { WeekPlan } from '../types'

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

  const draft = plan?.status === 'draft'
  const weekDates = Array.from({ length: 7 }, (_, i) =>
    toISODate(addDays(fromISODate(weekStart), i)),
  )

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
