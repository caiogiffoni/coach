import type { HrZone, BuilderStepType } from '../../types'
import { STEP_TYPE_LABELS } from '../../workoutBuilder'
import type { StepDraft } from '../../workoutBuilder'
import type { ItemErrors } from '../../workoutValidation'
import { LIMITS } from '../../workoutValidation'
import { ItemActions } from './ItemActions'
import { StepEndFields } from './StepEndFields'
import { StepTargetFields } from './StepTargetFields'

export interface ItemPosition {
  label: string
  canMoveUp: boolean
  canMoveDown: boolean
  canRemove: boolean
}

interface StepCardProps {
  step: StepDraft
  position: ItemPosition
  errors: ItemErrors | undefined
  hrZones: HrZone[] | null
  onChange: (patch: Partial<StepDraft>) => void
  onMove: (direction: -1 | 1) => void
  onDuplicate: () => void
  onRemove: () => void
}

/** One builder step: type (colored edge), end condition, target, notes. */
export function StepCard({ step, position, errors, hrZones, onChange, ...actions }: StepCardProps) {
  return (
    <div className="builder-step" data-step-type={step.stepType}>
      <div className="builder-step-head">
        <select
          className="select builder-step-type"
          aria-label={`Type of ${position.label}`}
          value={step.stepType}
          onChange={(e) => onChange({ stepType: e.target.value as BuilderStepType })}
        >
          {(Object.keys(STEP_TYPE_LABELS) as BuilderStepType[]).map((t) => (
            <option key={t} value={t}>
              {STEP_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <ItemActions {...position} {...actions} />
      </div>
      <div className="builder-step-grid">
        <StepEndFields step={step} error={errors?.end} onChange={onChange} />
        <StepTargetFields step={step} error={errors?.target} hrZones={hrZones} onChange={onChange} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${step.uid}-notes`}>
          Notes (optional)
        </label>
        <input
          id={`${step.uid}-notes`}
          className="input"
          maxLength={LIMITS.notesMax}
          value={step.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
        />
        {errors?.notes && <span className="field-error">{errors.notes}</span>}
      </div>
    </div>
  )
}
