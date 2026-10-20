import { Plus, Repeat } from 'lucide-react'
import type { HrZone } from '../../types'
import type { ItemDraft } from '../../workoutBuilder'
import type { DraftErrors } from '../../workoutValidation'
import { LIMITS } from '../../workoutValidation'
import { canUngroupRepeat, checkGroupSelection } from '../../workoutGrouping'
import type { WorkoutItemOps } from '../../hooks/useWorkoutItemOps'
import { useStepSelection } from '../../hooks/useStepSelection'
import type { StepSelection } from '../../hooks/useStepSelection'
import { GroupToolbar } from './GroupToolbar'
import { RepeatCard } from './RepeatCard'
import { StepCard } from './StepCard'

interface BuilderItemListProps {
  items: ItemDraft[]
  errors: DraftErrors
  hrZones: HrZone[] | null
  ops: WorkoutItemOps
}

interface BuilderItemProps extends BuilderItemListProps {
  index: number
  selection: StepSelection
}

function BuilderItem({ items, index, errors, hrZones, ops, selection }: BuilderItemProps) {
  const item = items[index]
  const position = {
    label: `${item.kind === 'repeat' ? 'repeat' : 'step'} ${index + 1}`,
    canMoveUp: index > 0,
    canMoveDown: index < items.length - 1,
    canRemove: true,
  }
  if (item.kind === 'repeat') {
    const canUngroup = canUngroupRepeat(items, index)
    return <RepeatCard repeat={item} position={position} canUngroup={canUngroup} errors={errors} hrZones={hrZones} ops={ops} />
  }
  return (
    <StepCard
      step={item}
      position={position}
      errors={errors.byUid[item.uid]}
      hrZones={hrZones}
      topLevel={{
        selected: selection.selected.has(item.uid),
        onToggleSelected: () => selection.toggle(item.uid),
        onRepeat: () => ops.repeatStep(item.uid),
      }}
      onChange={(patch) => ops.updateStep(item.uid, patch)}
      onMove={(d) => ops.move(item.uid, d)}
      onDuplicate={() => ops.duplicate(item.uid)}
      onRemove={() => ops.remove(item.uid)}
    />
  )
}

/** Ordered steps and repeat blocks, the grouping toolbar, and "Add step" / "Add repeat". */
export function BuilderItemList({ items, errors, hrZones, ops }: BuilderItemListProps) {
  const selection = useStepSelection(items)
  const full = items.length >= LIMITS.itemsMax

  function groupSelected(iterations: number) {
    ops.groupSteps(selection.selected, iterations)
    selection.clear()
  }

  return (
    <>
      {/* Always rendered so ticking the first step doesn't shift the list under the cursor. */}
      <GroupToolbar
        count={selection.selected.size}
        check={checkGroupSelection(items, selection.selected)}
        onGroup={groupSelected}
        onClear={selection.clear}
      />
      <div className="builder-list">
        {items.map((item, i) => (
          <BuilderItem key={item.uid} items={items} index={i} errors={errors} hrZones={hrZones} ops={ops} selection={selection} />
        ))}
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
