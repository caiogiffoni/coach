import type { EndType, StepDraft } from '../../workoutBuilder'

interface StepEndFieldsProps {
  step: StepDraft
  label: string // e.g. "step 2" — used for accessible names
  onChange: (patch: Partial<StepDraft>) => void
}

const END_LABELS: Record<EndType, string> = {
  time: 'Time',
  distance: 'Distance',
  lap_button: 'Lap press',
}

function EndValueInput({ step, onChange }: Omit<StepEndFieldsProps, 'label'>) {
  if (step.endType === 'lap_button') return null
  const isTime = step.endType === 'time'
  return (
    <>
      <input
        id={`${step.uid}-end-value`}
        className="input mono builder-value"
        inputMode={isTime ? 'numeric' : 'decimal'}
        aria-label={isTime ? 'Duration (m:ss)' : 'Distance (km)'}
        placeholder={isTime ? 'm:ss' : 'km'}
        value={isTime ? step.timeText : step.distanceKmText}
        onChange={(e) => onChange(isTime ? { timeText: e.target.value } : { distanceKmText: e.target.value })}
      />
      {!isTime && <span className="builder-unit mono">km</span>}
    </>
  )
}

/** Garmin's "Duration" block, inline: how the step ends plus its time/distance value. */
export function StepEndFields({ step, label, onChange }: StepEndFieldsProps) {
  return (
    <div className="builder-field-group">
      <select
        id={`${step.uid}-end`}
        className="select"
        aria-label={`How ${label} ends`}
        title="Ends by"
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
  )
}
