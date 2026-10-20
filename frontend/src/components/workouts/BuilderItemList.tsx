import { Plus, Repeat } from 'lucide-react'
import type { HrZone } from '../../types'
import type { ItemDraft } from '../../workoutBuilder'
import type { DraftErrors } from '../../workoutValidation'
import { LIMITS } from '../../workoutValidation'
import type { WorkoutItemOps } from '../../hooks/useWorkoutItemOps'
import { RepeatCard } from './RepeatCard'
import { StepCard } from './StepCard'

interface BuilderItemListProps {
  items: ItemDraft[]
  errors: DraftErrors
  hrZones: HrZone[] | null
  ops: WorkoutItemOps
}

/** Ordered steps and repeat blocks, plus the "Add step" / "Add repeat" buttons. */
export function BuilderItemList({ items, errors, hrZones, ops }: BuilderItemListProps) {
  const full = items.length >= LIMITS.itemsMax
  return (
    <>
      <div className="builder-list">
        {items.map((item, i) => {
          const position = {
            label: `${item.kind === 'repeat' ? 'repeat' : 'step'} ${i + 1}`,
            canMoveUp: i > 0,
            canMoveDown: i < items.length - 1,
            canRemove: true,
          }
          if (item.kind === 'repeat') {
            return <RepeatCard key={item.uid} repeat={item} position={position} errors={errors} hrZones={hrZones} ops={ops} />
          }
          return (
            <StepCard
              key={item.uid}
              step={item}
              position={position}
              errors={errors.byUid[item.uid]}
              hrZones={hrZones}
              onChange={(patch) => ops.updateStep(item.uid, patch)}
              onMove={(d) => ops.move(item.uid, d)}
              onDuplicate={() => ops.duplicate(item.uid)}
              onRemove={() => ops.remove(item.uid)}
            />
          )
        })}
      </div>
      {errors.items && <p className="field-error builder-items-error">{errors.items}</p>}
      <div className="builder-add-row">
        <button type="button" className="button button-secondary" onClick={ops.addStep} disabled={full}>
          <Plus size={16} strokeWidth={1.5} />
          Add step
        </button>
        <button type="button" className="button button-secondary" onClick={ops.addRepeat} disabled={full}>
          <Repeat size={16} strokeWidth={1.5} />
          Add repeat
        </button>
      </div>
    </>
  )
}
