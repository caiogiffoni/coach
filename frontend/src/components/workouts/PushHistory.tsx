import { formatDateShort, formatTimestamp } from '../../format'
import type { LibraryWorkoutPush } from '../../types'

/** Previous Garmin pushes of this workout, newest first. */
export function PushHistory({ pushes }: { pushes: LibraryWorkoutPush[] }) {
  if (pushes.length === 0) return <p className="muted">Not pushed to Garmin yet.</p>
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Scheduled for</th>
            <th>Garmin workout</th>
            <th>Pushed at</th>
          </tr>
        </thead>
        <tbody>
          {pushes.map((p) => (
            <tr key={`${p.garmin_workout_id}-${p.pushed_at}`}>
              <td className="mono">{formatDateShort(p.date)}</td>
              <td className="mono">{p.garmin_workout_id}</td>
              <td className="mono">{formatTimestamp(p.pushed_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
