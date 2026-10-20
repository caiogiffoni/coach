import { useState } from 'react'
import { CalendarPlus } from 'lucide-react'
import { tomorrowISO } from '../../format'

interface ScheduleControlsProps {
  idPrefix: string
  busy: boolean
  disabledReason: string | null // why pushing is unavailable, or null
  onPush: (date: string) => void
  onCancel?: () => void
}

/** Date picker (default tomorrow) + "Push to Garmin" button. */
export function ScheduleControls({ idPrefix, busy, disabledReason, onPush, onCancel }: ScheduleControlsProps) {
  const [date, setDate] = useState(tomorrowISO)
  return (
    <div className="schedule-controls">
      <label className="field-label" htmlFor={`${idPrefix}-date`}>
        Date
      </label>
      <input
        id={`${idPrefix}-date`}
        className="input input-compact mono"
        type="date"
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />
      <button
        type="button"
        className="button button-primary button-compact"
        onClick={() => onPush(date)}
        disabled={busy || !date || disabledReason !== null}
        title={disabledReason ?? 'Schedule this workout on your Garmin calendar'}
      >
        <CalendarPlus size={16} strokeWidth={1.5} />
        Push to Garmin
      </button>
      {onCancel && (
        <button type="button" className="button button-secondary button-compact" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      )}
      {disabledReason && <span className="field-hint">{disabledReason}</span>}
    </div>
  )
}
