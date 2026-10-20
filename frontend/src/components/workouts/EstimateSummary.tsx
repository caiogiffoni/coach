import { formatDistanceM, formatDuration } from '../../format'

interface EstimateSummaryProps {
  durationSec: number | null
  distanceM: number | null
  stepCount: number | null
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value mono">{value || '—'}</span>
    </div>
  )
}

/** Live estimated duration / distance / expanded step count. */
export function EstimateSummary({ durationSec, distanceM, stepCount }: EstimateSummaryProps) {
  const partial = durationSec === null || distanceM === null
  return (
    <div>
      <div className="stat-strip">
        <Stat label="Est. duration" value={formatDuration(durationSec)} />
        <Stat label="Est. distance" value={formatDistanceM(distanceM)} />
        <Stat label="Steps" value={stepCount === null ? '' : String(stepCount)} />
      </div>
      {partial && (
        <p className="field-hint">
          Estimates need a pace target on distance/time steps and no lap-button steps.
        </p>
      )}
    </div>
  )
}
