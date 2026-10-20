import { Plus, Repeat, Ungroup } from 'lucide-react'
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
  canUngroup: boolean
  errors: DraftErrors
  hrZones: HrZone[] | null
  ops: WorkoutItemOps
}

function RepeatHeader({ repeat, position, canUngroup, ops }: Omit<RepeatCardProps, 'errors' | 'hrZones'>) {
  return (
    <div className="builder-repeat-head">
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
        ×
      </label>
      <ItemActions
        {...position}
        onMove={(d) => ops.move(repeat.uid, d)}
        onDuplicate={() => ops.duplicate(repeat.uid)}
        onRemove={() => ops.remove(repeat.uid)}
      >
        <button
          type="button"
          className="icon-button icon-button-compact"
          onClick={() => ops.ungroup(repeat.uid)}
          disabled={!canUngroup}
          aria-label={`Ungroup ${position.label}`}
          title={canUngroup ? 'Ungroup into single steps' : `Ungrouping would pass ${LIMITS.itemsMax} items`}
        >
          <Ungroup size={16} strokeWidth={1.5} />
        </button>
      </ItemActions>
    </div>
  )
}

/** Compact "Repeat N×" block with its indented child steps (no nested repeats). */
export function RepeatCard({ repeat, position, canUngroup, errors, hrZones, ops }: RepeatCardProps) {
  const own = errors.byUid[repeat.uid]
  const count = repeat.steps.length
  return (
    <div className="builder-repeat">
      <RepeatHeader repeat={repeat} position={position} canUngroup={canUngroup} ops={ops} />
      {own?.iterations && <span className="field-error">{own.iterations}</span>}
      <div className="builder-repeat-children">
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
    </div>
  )
}
