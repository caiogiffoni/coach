import { ChevronLeft, ChevronRight } from 'lucide-react'
import { formatWeekRange } from '../../format'
import type { WeekPlan } from '../../types'

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-muted',
  approved: 'badge-success',
  pushed: 'badge-success',
}

interface WeekControlsProps {
  weekStart: string
  plan: WeekPlan | null
  onShiftWeek: (offset: number) => void
  onPickWeek: (value: string) => void
}

/** Previous/next week buttons, date picker, range label, and plan status badge. */
export function WeekControls({ weekStart, plan, onShiftWeek, onPickWeek }: WeekControlsProps) {
  return (
    <div className="week-controls">
      <button type="button" className="icon-button" onClick={() => onShiftWeek(-1)} aria-label="Previous week">
        <ChevronLeft size={20} strokeWidth={1.5} />
      </button>
      <input
        type="date"
        className="input"
        style={{ width: 'auto' }}
        value={weekStart}
        onChange={(e) => onPickWeek(e.target.value)}
        aria-label="Week (any date; snapped to Monday)"
      />
      <span className="week-range" aria-hidden="true">
        {formatWeekRange(weekStart)}
      </span>
      <button type="button" className="icon-button" onClick={() => onShiftWeek(1)} aria-label="Next week">
        <ChevronRight size={20} strokeWidth={1.5} />
      </button>
      {plan && (
        <span className={`badge ${STATUS_BADGE[plan.status] ?? 'badge-muted'}`}>{plan.status}</span>
      )}
    </div>
  )
}
