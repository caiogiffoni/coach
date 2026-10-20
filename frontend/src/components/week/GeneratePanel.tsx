import { RotateCcw } from 'lucide-react'
import { WeekdayCheckboxes } from '../WeekdayCheckboxes'

interface GeneratePanelProps {
  hasPlan: boolean
  busy: boolean
  notes: string
  days: number[]
  onNotesChange: (notes: string) => void
  onToggleDay: (day: number) => void
  onGenerate: () => void
  onSync: () => void
}

/** Notes + run-day picker card that triggers week generation and manual sync. */
export function GeneratePanel(props: GeneratePanelProps) {
  const { hasPlan, busy, notes, days, onNotesChange, onToggleDay, onGenerate, onSync } = props
  return (
    <section className="section">
      <div className="card">
        <div className="card-header-row">
          <h2 className="card-title">Generate week</h2>
          <button
            type="button"
            className="button button-secondary button-compact"
            onClick={onSync}
            disabled={busy}
            title="Pull recent data from Garmin Connect"
          >
            <RotateCcw size={14} strokeWidth={1.5} />
            Sync now
          </button>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="notes">
            Notes to the coach
          </label>
          <textarea
            id="notes"
            className="textarea"
            placeholder="e.g. legs heavy after Sunday's long run; travel on Thursday"
            value={notes}
            onChange={(e) => onNotesChange(e.target.value)}
          />
        </div>
        <div className="field">
          <span className="field-label">Run days</span>
          <WeekdayCheckboxes selected={days} onToggle={onToggleDay} />
          <p className="field-hint">Defaults come from your profile's preferred days.</p>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="button button-primary"
            onClick={onGenerate}
            disabled={busy || days.length === 0}
          >
            {hasPlan ? 'Regenerate week' : 'Generate week'}
          </button>
        </div>
      </div>
    </section>
  )
}
