import type { WorkoutDraft } from '../../workoutBuilder'
import type { DraftErrors } from '../../workoutValidation'
import { LIMITS } from '../../workoutValidation'

interface WorkoutMetaFieldsProps {
  draft: WorkoutDraft
  errors: DraftErrors
  onChange: (patch: Partial<Pick<WorkoutDraft, 'name' | 'description'>>) => void
}

/** Workout name and description. */
export function WorkoutMetaFields({ draft, errors, onChange }: WorkoutMetaFieldsProps) {
  return (
    <>
      <div className="field">
        <label className="field-label" htmlFor="workout-name">
          Workout name
        </label>
        <input
          id="workout-name"
          className="input"
          maxLength={LIMITS.nameMax}
          value={draft.name}
          onChange={(e) => onChange({ name: e.target.value })}
        />
        {errors.name && <span className="field-error">{errors.name}</span>}
      </div>
      <div className="field">
        <label className="field-label" htmlFor="workout-description">
          Description (optional)
        </label>
        <textarea
          id="workout-description"
          className="textarea"
          maxLength={LIMITS.descriptionMax}
          value={draft.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
        {errors.description && <span className="field-error">{errors.description}</span>}
      </div>
    </>
  )
}
