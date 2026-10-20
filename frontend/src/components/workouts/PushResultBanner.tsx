import { formatDateShort } from '../../format'
import type { LibraryWorkoutPush } from '../../types'

/** Confirmation after a successful library-workout push. */
export function PushResultBanner({ name, push }: { name: string; push: LibraryWorkoutPush }) {
  return (
    <div className="banner banner-success" role="status">
      Scheduled “{name}” on <span className="mono">{formatDateShort(push.date)}</span> (Garmin workout{' '}
      <span className="mono">{push.garmin_workout_id}</span>).
    </div>
  )
}
