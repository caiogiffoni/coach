import type { EndType, StepDraft } from '../../workoutBuilder'

interface StepEndFieldsProps {
  step: StepDraft
  error?: string
  onChange: (patch: Partial<StepDraft>) => void
}

const END_LABELS: Record<EndType, string> = {
  time: 'Time',
  distance: 'Distance',
  lap_button: 'Lap button press',
}

function EndValueInput({ step, onChange }: Omit<StepEndFieldsProps, 'error'>) {
  if (step.endType === 'lap_button') {
    return <p className="field-hint builder-lap-hint">Ends when you press Lap.</p>
  }
  const isTime = step.endType === 'time'
  return (
    <input
      id={`${step.uid}-end-value`}
      className="input mono"
      inputMode={isTime ? 'numeric' : 'decimal'}
      aria-label={isTime ? 'Duration (m:ss)' : 'Distance (km)'}
      placeholder={isTime ? 'm:ss' : 'km'}
      value={isTime ? step.timeText : step.distanceKmText}
      onChange={(e) => onChange(isTime ? { timeText: e.target.value } : { distanceKmText: e.target.value })}
    />
  )
}

/** Garmin's "Duration" block: how the step ends plus its time/distance value. */
export function StepEndFields({ step, error, onChange }: StepEndFieldsProps) {
  const unit = step.endType === 'time' ? 'm:ss' : step.endType === 'distance' ? 'km' : null
  return (
    <div className="field">
      <label className="field-label" htmlFor={`${step.uid}-end`}>
        End{unit && <span className="mono"> ({unit})</span>}
      </label>
      <div className="builder-pair">
        <select
          id={`${step.uid}-end`}
          className="select"
          value={step.endType}
          onChange={(e) => onChange({ endType: e.target.value as EndType })}
        >
          {(Object.keys(END_LABELS) as EndType[]).map((t) => (
            <option key={t} value={t}>
              {END_LABELS[t]}
            </option>
          ))}
        </select>
        <EndValueInput step={step} onChange={onChange} />
      </div>
      {error && <span className="field-error">{error}</span>}
    </div>
  )
}
