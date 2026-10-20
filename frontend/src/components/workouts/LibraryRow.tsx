import { CalendarPlus, Copy, Pencil, Trash2 } from 'lucide-react'
import { Link } from 'react-router'
import { formatDistanceM, formatDuration, formatTimestamp } from '../../format'
import type { LibraryWorkoutSummary } from '../../types'
import { ScheduleControls } from './ScheduleControls'

export type RowPanel = 'delete' | 'schedule' | null

interface LibraryRowProps {
  workout: LibraryWorkoutSummary
  panel: RowPanel
  busy: boolean
  pushDisabledReason: string | null
  onPanel: (panel: RowPanel) => void
  onDuplicate: () => void
  onDelete: () => void
  onPush: (date: string) => void
}

function RowActions({ workout, busy, onPanel, onDuplicate }: Pick<LibraryRowProps, 'workout' | 'busy' | 'onPanel' | 'onDuplicate'>) {
  return (
    <div className="library-row-actions">
      <Link to={`/workouts/${workout.id}`} className="button button-secondary button-compact">
        <Pencil size={16} strokeWidth={1.5} />
        Open
      </Link>
      <button type="button" className="button button-secondary button-compact" onClick={onDuplicate} disabled={busy}>
        <Copy size={16} strokeWidth={1.5} />
        Duplicate
      </button>
      <button type="button" className="button button-secondary button-compact" onClick={() => onPanel('schedule')} disabled={busy}>
        <CalendarPlus size={16} strokeWidth={1.5} />
        Schedule
      </button>
      <button type="button" className="button button-danger button-compact" onClick={() => onPanel('delete')} disabled={busy}>
        <Trash2 size={16} strokeWidth={1.5} />
        Delete
      </button>
    </div>
  )
}

function DeleteConfirm({ name, busy, onDelete, onCancel }: { name: string; busy: boolean; onDelete: () => void; onCancel: () => void }) {
  return (
    <div className="inline-panel" role="alertdialog" aria-label="Confirm delete">
      <span>Delete “{name}”? This can’t be undone.</span>
      <button type="button" className="button button-danger button-compact" onClick={onDelete} disabled={busy}>
        Delete
      </button>
      <button type="button" className="button button-secondary button-compact" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
    </div>
  )
}

/** One saved workout: summary, actions, and inline delete-confirm / schedule panels. */
export function LibraryRow({ workout, panel, busy, pushDisabledReason, onPanel, onDuplicate, onDelete, onPush }: LibraryRowProps) {
  return (
    <li className="library-row">
      <div className="library-row-main">
        <div className="library-row-info">
          <Link to={`/workouts/${workout.id}`} className="library-row-name">
            {workout.name}
          </Link>
          {workout.description && <p className="library-row-desc">{workout.description}</p>}
          <div className="library-row-meta mono">
            <span>{workout.step_count} steps</span>
            <span>{formatDuration(workout.estimated_duration_sec) || '—'}</span>
            <span>{formatDistanceM(workout.estimated_distance_m) || '—'}</span>
            <span>Updated {formatTimestamp(workout.updated_at)}</span>
          </div>
        </div>
        {panel === null && <RowActions workout={workout} busy={busy} onPanel={onPanel} onDuplicate={onDuplicate} />}
      </div>
      {panel === 'delete' && <DeleteConfirm name={workout.name} busy={busy} onDelete={onDelete} onCancel={() => onPanel(null)} />}
      {panel === 'schedule' && (
        <div className="inline-panel">
          <ScheduleControls
            idPrefix={`workout-${workout.id}`}
            busy={busy}
            disabledReason={pushDisabledReason}
            onPush={onPush}
            onCancel={() => onPanel(null)}
          />
        </div>
      )}
    </li>
  )
}
