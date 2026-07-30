import { useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import type { DayGuardResult, Workout } from '../types'
import { formatDateShort, WEEKDAY_NAMES } from '../format'
import { derivedDistanceKm, stepTargetText, workoutZones } from '../workout'

interface DayCardProps {
  date: string // ISO date
  weekday: number // 0=Mon
  workout: Workout | null
  draft: boolean
  busy: boolean
  guard: DayGuardResult | null
  onRegenerateDay: (date: string) => void
  onRegenerateFromGuard?: (date: string, reason: string) => void
}

export function DayCard({
  date,
  weekday,
  workout,
  draft,
  busy,
  guard,
  onRegenerateDay,
  onRegenerateFromGuard,
}: DayCardProps) {
  const [expanded, setExpanded] = useState(false)

  if (!workout) {
    return (
      <div className="day-card day-card-rest">
        <div className="day-card-header">
          <span className="day-card-date">
            {WEEKDAY_NAMES[weekday]} {formatDateShort(date).split(' ').slice(1).join(' ')}
          </span>
        </div>
        <span className="day-card-meta">Rest</span>
      </div>
    )
  }

  const km = derivedDistanceKm(workout)
  const guardAction = guard && guard.recommendation !== 'proceed'

  return (
    <div className="day-card">
      <div className="day-card-header">
        <span className="day-card-date">{formatDateShort(date)}</span>
        <span className={`badge badge-${workout.slot_type === 'quality' || workout.slot_type === 'long' ? 'info' : 'muted'}`}>
          {workout.slot_type}
        </span>
      </div>
      {guardAction && (
        <div className="day-card-alert">
          <AlertTriangle size={14} strokeWidth={1.5} />
          <span className={`badge badge-${guard.recommendation === 'veto' ? 'danger' : 'warning'}`}>
            {guard.recommendation}
          </span>
          <span className="muted" title={guard.reason}>
            {guard.reason}
          </span>
        </div>
      )}
      <div className="day-card-name">{workout.name}</div>
      <div className="day-card-meta mono">
        {Math.round(workout.duration_min)} min
        {km !== null && ` · ${km.toFixed(1)} km`}
      </div>
      <div className="day-card-badges">
        {workoutZones(workout).map((z) => (
          <span key={z} className={`badge badge-${z.toLowerCase()}`}>
            {z}
          </span>
        ))}
      </div>
      {workout.steps.length > 0 && (
        <button
          type="button"
          className="day-card-toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? 'Hide steps' : `Steps (${workout.steps.length})`}
        </button>
      )}
      {expanded && (
        <div className="steps-list">
          {workout.steps.map((step, i) => (
            <div className="step-row" key={i}>
              <div className="step-row-head">
                <span className="muted">{step.type}</span>
                <span className="mono">{step.duration_min} min</span>
                {step.target_zone && (
                  <span className={`badge badge-${step.target_zone.toLowerCase()}`}>
                    {step.target_zone}
                  </span>
                )}
              </div>
              {stepTargetText(step) && (
                <span className="step-targets mono">{stepTargetText(step)}</span>
              )}
            </div>
          ))}
        </div>
      )}
      {draft && (
        <button
          type="button"
          className="button button-secondary button-compact"
          onClick={() => onRegenerateDay(date)}
          disabled={busy}
          title="Regenerate this day"
        >
          <RefreshCw size={14} strokeWidth={1.5} />
          Regenerate
        </button>
      )}
      {guardAction && onRegenerateFromGuard && draft && (
        <button
          type="button"
          className="button button-warning button-compact"
          onClick={() => onRegenerateFromGuard(date, guard.reason)}
          disabled={busy}
          title="Regenerate this day using the guard recommendation"
        >
          <RefreshCw size={14} strokeWidth={1.5} />
          Regenerate from guard
        </button>
      )}
    </div>
  )
}
