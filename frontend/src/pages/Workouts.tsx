import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Link } from 'react-router'
import { GarminMfaCard } from '../components/week/GarminMfaCard'
import { GarminConfigBanner } from '../components/workouts/GarminConfigBanner'
import { LibraryRow } from '../components/workouts/LibraryRow'
import type { RowPanel } from '../components/workouts/LibraryRow'
import { PushResultBanner } from '../components/workouts/PushResultBanner'
import { garminPushDisabledReason } from '../garminLogin'
import { useGarminStatus } from '../hooks/useGarminStatus'
import { useRequestStatus } from '../hooks/useRequestStatus'
import { useWorkoutLibrary } from '../hooks/useWorkoutLibrary'
import { useWorkoutPush } from '../hooks/useWorkoutPush'

/** Workout library: saved builder workouts with open/duplicate/delete/schedule. */
export function Workouts() {
  const status = useRequestStatus()
  const [openPanel, setOpenPanel] = useState<{ id: number; panel: RowPanel } | null>(null)
  const library = useWorkoutLibrary(status)
  const push = useWorkoutPush({ status, onPushed: () => setOpenPanel(null) })
  const garminStatus = useGarminStatus('workouts')
  const pushed = push.lastPush && library.workouts.find((w) => w.id === push.lastPush?.workoutId)

  async function deleteWorkout(id: number) {
    await library.remove(id)
    setOpenPanel(null)
  }

  return (
    <>
      <div className="page-header">
        <h1>Workouts</h1>
        <Link to="/workouts/new" className="button button-primary">
          <Plus size={16} strokeWidth={1.5} />
          New workout
        </Link>
      </div>

      {status.error && (
        <div className="banner banner-danger" role="alert">
          {status.error}
        </div>
      )}
      <GarminConfigBanner garminStatus={garminStatus} />
      {push.lastPush && pushed && <PushResultBanner name={pushed.name} push={push.lastPush.push} />}
      {push.needsMfa && (
        <GarminMfaCard
          code={push.mfaCode}
          busy={status.busy}
          onCodeChange={push.setMfaCode}
          onSubmit={push.submitMfa}
          onCancel={push.cancelMfa}
        />
      )}

      {library.loading && <p className="muted">Loading…</p>}
      {!library.loading && library.workouts.length === 0 && (
        <div className="empty-state">
          <p>No saved workouts yet.</p>
          <Link to="/workouts/new" className="button button-primary">
            New workout
          </Link>
        </div>
      )}
      {library.workouts.length > 0 && (
        <ul className="library-list">
          {library.workouts.map((w) => (
            <LibraryRow
              key={w.id}
              workout={w}
              panel={openPanel?.id === w.id ? openPanel.panel : null}
              busy={status.busy}
              pushDisabledReason={garminPushDisabledReason(garminStatus)}
              onPanel={(panel) => setOpenPanel(panel === null ? null : { id: w.id, panel })}
              onDuplicate={() => library.duplicate(w.id)}
              onDelete={() => deleteWorkout(w.id)}
              onPush={(date) => push.executePush(w.id, date)}
            />
          ))}
        </ul>
      )}
    </>
  )
}
