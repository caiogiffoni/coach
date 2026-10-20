import type { HrZone, HrZoneNumber } from '../../types'
import type { StepDraft, TargetType } from '../../workoutBuilder'

interface StepTargetFieldsProps {
  step: StepDraft
  label: string // e.g. "step 2" — used for accessible names
  hrZones: HrZone[] | null
  onChange: (patch: Partial<StepDraft>) => void
}

const TARGET_LABELS: Record<TargetType, string> = {
  none: 'No target',
  hr_zone: 'HR zone',
  hr_range: 'HR range',
  pace_range: 'Pace',
}

const TARGET_UNITS: Partial<Record<TargetType, string>> = {
  hr_range: 'bpm',
  pace_range: '/km',
}

const ZONES: HrZoneNumber[] = [1, 2, 3, 4, 5]

interface RangeField {
  label: string
  placeholder: string
  value: string
  onChange: (value: string) => void
}

function RangeInputs({ uid, fields }: { uid: string; fields: [RangeField, RangeField] }) {
  return (
    <>
      {fields.map((f, i) => (
        <input
          key={f.label}
          id={i === 0 ? `${uid}-target-value` : undefined}
          className="input mono builder-value"
          inputMode={f.placeholder.includes(':') ? 'text' : 'numeric'}
          aria-label={f.label}
          placeholder={f.placeholder}
          value={f.value}
          onChange={(e) => f.onChange(e.target.value)}
        />
      ))}
    </>
  )
}

function ZoneSelect({ step, onChange }: Pick<StepTargetFieldsProps, 'step' | 'onChange'>) {
  return (
    <select
      className="select"
      aria-label="Heart rate zone"
      value={step.hrZone}
      onChange={(e) => onChange({ hrZone: Number(e.target.value) as HrZoneNumber })}
    >
      {ZONES.map((z) => (
        <option key={z} value={z}>
          Zone {z}
        </option>
      ))}
    </select>
  )
}

function TargetValueInputs({ step, onChange }: Pick<StepTargetFieldsProps, 'step' | 'onChange'>) {
  if (step.targetType === 'hr_zone') return <ZoneSelect step={step} onChange={onChange} />
  if (step.targetType === 'hr_range') {
    return (
      <RangeInputs
        uid={step.uid}
        fields={[
          { label: 'Low heart rate (bpm)', placeholder: 'Low', value: step.minBpmText, onChange: (v) => onChange({ minBpmText: v }) },
          { label: 'High heart rate (bpm)', placeholder: 'High', value: step.maxBpmText, onChange: (v) => onChange({ maxBpmText: v }) },
        ]}
      />
    )
  }
  if (step.targetType === 'pace_range') {
    return (
      <RangeInputs
        uid={step.uid}
        fields={[
          { label: 'Fast pace (m:ss per km)', placeholder: '4:30', value: step.fastPaceText, onChange: (v) => onChange({ fastPaceText: v }) },
          { label: 'Slow pace (m:ss per km)', placeholder: '5:00', value: step.slowPaceText, onChange: (v) => onChange({ slowPaceText: v }) },
        ]}
      />
    )
  }
  return null
}

/** "145–160 bpm" for the chosen zone from the athlete's profile zones, when known. */
function ZoneHint({ zone, hrZones }: { zone: HrZoneNumber; hrZones: HrZone[] | null }) {
  const match = hrZones?.find((z) => z.zone === `Z${zone}`)
  if (!match) return null
  return (
    <span className="builder-unit mono">
      {match.min_bpm}–{match.max_bpm} bpm
    </span>
  )
}

/** Garmin's "Intensity target" block, inline: target type plus its zone/range values. */
export function StepTargetFields({ step, label, hrZones, onChange }: StepTargetFieldsProps) {
  const unit = TARGET_UNITS[step.targetType]
  return (
    <div className="builder-field-group">
      <select
        id={`${step.uid}-target`}
        className="select"
        aria-label={`Intensity target of ${label}`}
        title="Intensity target"
        value={step.targetType}
        onChange={(e) => onChange({ targetType: e.target.value as TargetType })}
      >
        {(Object.keys(TARGET_LABELS) as TargetType[]).map((t) => (
          <option key={t} value={t}>
            {TARGET_LABELS[t]}
          </option>
        ))}
      </select>
      <TargetValueInputs step={step} onChange={onChange} />
      {unit && <span className="builder-unit mono">{unit}</span>}
      {step.targetType === 'hr_zone' && <ZoneHint zone={step.hrZone} hrZones={hrZones} />}
    </div>
  )
}
