import { garminPushDisabledReason } from '../../garminLogin'
import type { RequestStatus } from '../../hooks/requestStatus'
import { useGarminStatus } from '../../hooks/useGarminStatus'
import { useWorkoutPush } from '../../hooks/useWorkoutPush'
import type { LibraryWorkout } from '../../types'
import { GarminMfaCard } from '../week/GarminMfaCard'
import { GarminConfigBanner } from './GarminConfigBanner'
import { PushHistory } from './PushHistory'
import { PushResultBanner } from './PushResultBanner'
import { ScheduleControls } from './ScheduleControls'

interface SchedulePanelProps {
  workout: LibraryWorkout
  dirty: boolean
  status: RequestStatus
  onPushed: () => Promise<void>
}

/** Editor section: push the saved workout to a Garmin date and list past pushes. */
export function SchedulePanel({ workout, dirty, status, onPushed }: SchedulePanelProps) {
  const garminStatus = useGarminStatus('workouts')
  const push = useWorkoutPush({ status, onPushed: () => void onPushed() })
  // The server pushes the saved version, so unsaved edits would silently be lost.
  const disabledReason = garminPushDisabledReason(garminStatus) ?? (dirty ? 'Save your changes before pushing' : null)

  return (
    <section className="section">
      <h2 className="section-title">Schedule on Garmin</h2>
      <GarminConfigBanner garminStatus={garminStatus} />
      {push.lastPush && <PushResultBanner name={workout.name} push={push.lastPush.push} />}
      {push.needsMfa && (
        <GarminMfaCard
          code={push.mfaCode}
          busy={status.busy}
          onCodeChange={push.setMfaCode}
          onSubmit={push.submitMfa}
          onCancel={push.cancelMfa}
        />
      )}
      <div className="card">
        <ScheduleControls
          idPrefix="editor-schedule"
          busy={status.busy}
          disabledReason={disabledReason}
          onPush={(date) => push.executePush(workout.id, date)}
        />
        <h3 className="card-title push-history-title">Previous pushes</h3>
        <PushHistory pushes={workout.pushes} />
      </div>
    </section>
  )
}
