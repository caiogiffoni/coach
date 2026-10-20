import { useState } from 'react'
import { NotebookPen, Repeat } from 'lucide-react'
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

/** Only top-level steps can be selected for grouping or wrapped into a repeat. */
export interface TopLevelStepControls {
  selected: boolean
  onToggleSelected: () => void
  onRepeat: () => void
}

interface StepCardProps {
  step: StepDraft
  position: ItemPosition
  errors: ItemErrors | undefined
  hrZones: HrZone[] | null
  topLevel?: TopLevelStepControls
  onChange: (patch: Partial<StepDraft>) => void
  onMove: (direction: -1 | 1) => void
  onDuplicate: () => void
  onRemove: () => void
}

function StepTypeSelect({ step, label, onChange }: { step: StepDraft; label: string; onChange: StepCardProps['onChange'] }) {
  return (
    <select
      className="select builder-step-type"
      aria-label={`Type of ${label}`}
      value={step.stepType}
      onChange={(e) => onChange({ stepType: e.target.value as BuilderStepType })}
    >
      {(Object.keys(STEP_TYPE_LABELS) as BuilderStepType[]).map((t) => (
        <option key={t} value={t}>
          {STEP_TYPE_LABELS[t]}
        </option>
      ))}
    </select>
  )
}

function StepErrors({ errors }: { errors: ItemErrors | undefined }) {
  const messages = [errors?.end, errors?.target, errors?.notes].filter((m): m is string => Boolean(m))
  if (messages.length === 0) return null
  return (
    <div className="builder-step-errors">
      {messages.map((m) => (
        <span key={m} className="field-error">
          {m}
        </span>
      ))}
    </div>
  )
}

/** One builder step as a dense row: type (colored edge), end, target, actions; notes on demand. */
export function StepCard({ step, position, errors, hrZones, topLevel, onChange, ...actions }: StepCardProps) {
  const [notesOpen, setNotesOpen] = useState(false)
  const showNotes = notesOpen || step.notes !== '' || Boolean(errors?.notes)
  const { label } = position
  return (
    <div className="builder-step" data-step-type={step.stepType} data-selected={topLevel?.selected || undefined}>
      <div className="builder-step-row">
        {topLevel && (
          <input type="checkbox" aria-label={`Select ${label} for grouping`} checked={topLevel.selected} onChange={topLevel.onToggleSelected} />
        )}
        <StepTypeSelect step={step} label={label} onChange={onChange} />
        <div className="builder-step-fields">
          <StepEndFields step={step} label={label} onChange={onChange} />
          <StepTargetFields step={step} label={label} hrZones={hrZones} onChange={onChange} />
        </div>
        <ItemActions {...position} {...actions}>
          <button type="button" className="icon-button icon-button-compact" aria-pressed={showNotes} onClick={() => setNotesOpen((o) => !o)} disabled={step.notes !== ''} aria-label={`Show notes for ${label}`} title={step.notes !== '' ? 'Clear the note to hide it' : 'Notes'}>
            <NotebookPen size={16} strokeWidth={1.5} />
          </button>
          {topLevel && (
            <button type="button" className="icon-button icon-button-compact" onClick={topLevel.onRepeat} aria-label={`Repeat ${label}`} title="Repeat this step">
              <Repeat size={16} strokeWidth={1.5} />
            </button>
          )}
        </ItemActions>
      </div>
      <StepErrors errors={errors} />
      {showNotes && (
        <input
          id={`${step.uid}-notes`}
          className="input builder-notes"
          maxLength={LIMITS.notesMax}
          aria-label={`Notes for ${label}`}
          placeholder="Notes (optional)"
          value={step.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
        />
      )}
    </div>
  )
}
