import { ChevronDown, ChevronUp, Copy, Trash2 } from 'lucide-react'

interface ItemActionsProps {
  label: string // e.g. "step 2" — used for accessible button names
  canMoveUp: boolean
  canMoveDown: boolean
  canRemove: boolean
  onMove: (direction: -1 | 1) => void
  onDuplicate: () => void
  onRemove: () => void
}

/** Move up / move down / duplicate / delete buttons for a step or repeat. */
export function ItemActions({ label, canMoveUp, canMoveDown, canRemove, onMove, onDuplicate, onRemove }: ItemActionsProps) {
  return (
    <div className="item-actions">
      <button type="button" className="icon-button icon-button-compact" onClick={() => onMove(-1)} disabled={!canMoveUp} aria-label={`Move ${label} up`} title="Move up">
        <ChevronUp size={16} strokeWidth={1.5} />
      </button>
      <button type="button" className="icon-button icon-button-compact" onClick={() => onMove(1)} disabled={!canMoveDown} aria-label={`Move ${label} down`} title="Move down">
        <ChevronDown size={16} strokeWidth={1.5} />
      </button>
      <button type="button" className="icon-button icon-button-compact" onClick={onDuplicate} aria-label={`Duplicate ${label}`} title="Duplicate">
        <Copy size={16} strokeWidth={1.5} />
      </button>
      <button type="button" className="icon-button icon-button-compact icon-button-danger" onClick={onRemove} disabled={!canRemove} aria-label={`Delete ${label}`} title={canRemove ? 'Delete' : 'A repeat needs at least one step'}>
        <Trash2 size={16} strokeWidth={1.5} />
      </button>
    </div>
  )
}
