import { Plus, Repeat } from 'lucide-react'
import type { HrZone } from '../../types'
import type { RepeatDraft } from '../../workoutBuilder'
import type { DraftErrors } from '../../workoutValidation'
import { LIMITS } from '../../workoutValidation'
import type { WorkoutItemOps } from '../../hooks/useWorkoutItemOps'
import { ItemActions } from './ItemActions'
import type { ItemPosition } from './StepCard'
import { StepCard } from './StepCard'

interface RepeatCardProps {
  repeat: RepeatDraft
  position: ItemPosition
  errors: DraftErrors
  hrZones: HrZone[] | null
  ops: WorkoutItemOps
}

/** "Repeat N times" block with its own child steps (no nested repeats). */
export function RepeatCard({ repeat, position, errors, hrZones, ops }: RepeatCardProps) {
  const own = errors.byUid[repeat.uid]
  const count = repeat.steps.length
  return (
    <div className="builder-repeat">
      <div className="builder-step-head">
        <label className="builder-repeat-count" htmlFor={`${repeat.uid}-iterations`}>
          <Repeat size={16} strokeWidth={1.5} />
          Repeat
          <input
            id={`${repeat.uid}-iterations`}
            className="input input-compact mono"
            inputMode="numeric"
            value={repeat.iterationsText}
            onChange={(e) => ops.setIterations(repeat.uid, e.target.value)}
          />
          times
        </label>
        <ItemActions
          {...position}
          onMove={(d) => ops.move(repeat.uid, d)}
          onDuplicate={() => ops.duplicate(repeat.uid)}
          onRemove={() => ops.remove(repeat.uid)}
        />
      </div>
      {own?.iterations && <span className="field-error">{own.iterations}</span>}
      {repeat.steps.map((step, i) => (
        <StepCard
          key={step.uid}
          step={step}
          position={{ label: `repeat step ${i + 1}`, canMoveUp: i > 0, canMoveDown: i < count - 1, canRemove: count > 1 }}
          errors={errors.byUid[step.uid]}
          hrZones={hrZones}
          onChange={(patch) => ops.updateStep(step.uid, patch)}
          onMove={(d) => ops.move(step.uid, d)}
          onDuplicate={() => ops.duplicate(step.uid)}
          onRemove={() => ops.remove(step.uid)}
        />
      ))}
      {own?.steps && <span className="field-error">{own.steps}</span>}
      <div>
        <button
          type="button"
          className="button button-secondary button-compact"
          onClick={() => ops.addStepToRepeat(repeat.uid)}
          disabled={count >= LIMITS.repeatStepsMax}
        >
          <Plus size={16} strokeWidth={1.5} />
          Add step
        </button>
      </div>
    </div>
  )
}
