import { useState } from 'react'
import { Group, X } from 'lucide-react'
import type { GroupCheck } from '../../workoutGrouping'
import { DEFAULT_GROUP_ITERATIONS, parseGroupIterations } from '../../workoutGrouping'
import { LIMITS } from '../../workoutValidation'

interface GroupToolbarProps {
  count: number
  check: GroupCheck
  onGroup: (iterations: number) => void
  onClear: () => void
}

/** "N selected · Repeat [2]× · Group · Clear" — wraps the selected steps into one repeat. */
export function GroupToolbar({ count, check, onGroup, onClear }: GroupToolbarProps) {
  const [iterationsText, setIterationsText] = useState(String(DEFAULT_GROUP_ITERATIONS))
  const iterations = parseGroupIterations(iterationsText)
  const hint = count === 0
    ? 'Tick consecutive steps to repeat them as a block'
    : !check.ok
      ? check.reason
      : iterations === null
        ? `Repeat ${LIMITS.iterationsMin}–${LIMITS.iterationsMax} times`
        : null

  return (
    <div className="inline-panel builder-group-toolbar" role="toolbar" aria-label="Group selected steps">
      <span className="mono">{count}</span> selected
      <label className="builder-repeat-count builder-group-iterations">
        Repeat
        <input
          className="input input-compact mono"
          inputMode="numeric"
          aria-label="Repeat count for the group"
          value={iterationsText}
          onChange={(e) => setIterationsText(e.target.value)}
        />
        ×
      </label>
      <button
        type="button"
        className="button button-primary button-compact"
        disabled={!check.ok || iterations === null}
        onClick={() => iterations !== null && onGroup(iterations)}
      >
        <Group size={16} strokeWidth={1.5} />
        Group
      </button>
      <button type="button" className="button button-secondary button-compact" disabled={count === 0} onClick={onClear}>
        <X size={16} strokeWidth={1.5} />
        Clear
      </button>
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  )
}
