import { addDays, fromISODate, toISODate } from '../../format'
import type { DayGuardResult, WeekPlan } from '../../types'
import { DayCard } from '../DayCard'

interface WeekDaysProps {
  weekStart: string
  plan: WeekPlan | null
  loading: boolean
  busy: boolean
  canGenerate: boolean
  guardByDate: Record<string, DayGuardResult>
  onGenerate: () => void
  onRegenerateDay: (date: string) => void
  onRegenerateFromGuard: (date: string, reason: string) => void
}

function EmptyWeek({ disabled, onGenerate }: { disabled: boolean; onGenerate: () => void }) {
  return (
    <div className="card empty-state">
      <p>No plan for this week yet.</p>
      <button type="button" className="button button-primary" onClick={onGenerate} disabled={disabled}>
        Generate week
      </button>
    </div>
  )
}

/** Seven day cards for the plan, or a loading / empty state. */
export function WeekDays(props: WeekDaysProps) {
  const { weekStart, plan, loading, busy, canGenerate, guardByDate } = props
  if (loading) return <section className="section"><p className="muted">Loading…</p></section>
  if (!plan) {
    return (
      <section className="section">
        <EmptyWeek disabled={busy || !canGenerate} onGenerate={props.onGenerate} />
      </section>
    )
  }
  const weekDates = Array.from({ length: 7 }, (_, i) => toISODate(addDays(fromISODate(weekStart), i)))
  return (
    <section className="section">
      <div className="week-grid">
        {weekDates.map((date, i) => (
          <DayCard
            key={date}
            date={date}
            weekday={i}
            workout={plan.workouts.find((w) => w.date === date) ?? null}
            draft={plan.status === 'draft'}
            busy={busy}
            guard={guardByDate[date] ?? null}
            onRegenerateDay={props.onRegenerateDay}
            onRegenerateFromGuard={props.onRegenerateFromGuard}
          />
        ))}
      </div>
    </section>
  )
}
