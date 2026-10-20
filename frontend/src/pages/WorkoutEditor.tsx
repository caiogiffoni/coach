import { ArrowLeft, Save } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { BuilderItemList } from '../components/workouts/BuilderItemList'
import { EstimateSummary } from '../components/workouts/EstimateSummary'
import { SchedulePanel } from '../components/workouts/SchedulePanel'
import { WorkoutMetaFields } from '../components/workouts/WorkoutMetaFields'
import { useHrZones } from '../hooks/useHrZones'
import { useWorkoutEditor } from '../hooks/useWorkoutEditor'

function EditorHeader({ isNew, dirty, busy, onSave }: { isNew: boolean; dirty: boolean; busy: boolean; onSave: () => void }) {
  return (
    <div className="page-header page-header-wrap">
      <div className="row">
        <Link to="/workouts" className="icon-button" aria-label="Back to workouts" title="Back to workouts">
          <ArrowLeft size={20} strokeWidth={1.5} />
        </Link>
        <h1>{isNew ? 'New workout' : 'Edit workout'}</h1>
      </div>
      <div className="row">
        {dirty && !isNew && <span className="badge badge-warning">Unsaved changes</span>}
        <button type="button" className="button button-primary" onClick={onSave} disabled={busy || !dirty}>
          <Save size={16} strokeWidth={1.5} />
          Save
        </button>
      </div>
    </div>
  )
}

/** Garmin-style workout builder for `/workouts/new` and `/workouts/:id`. */
export function WorkoutEditor() {
  const { id } = useParams()
  // A fresh editor per workout so no draft leaks between URLs.
  return <WorkoutEditorView key={id ?? 'new'} id={id} />
}

function WorkoutEditorView({ id }: { id: string | undefined }) {
  const editor = useWorkoutEditor(id)
  const hrZones = useHrZones()
  const { status } = editor

  if (editor.loading) return <p className="muted">Loading…</p>

  return (
    <>
      <EditorHeader isNew={editor.isNew} dirty={editor.dirty} busy={status.busy} onSave={editor.save} />
      {status.error && (
        <div className="banner banner-danger" role="alert">
          {status.error}
        </div>
      )}
      {editor.saved && !status.error && <div className="banner banner-info">Workout saved.</div>}

      <section className="section card">
        <WorkoutMetaFields draft={editor.draft} errors={editor.errors} onChange={editor.updateMeta} />
        <EstimateSummary
          durationSec={editor.estimate.durationSec}
          distanceM={editor.estimate.distanceM}
          stepCount={editor.stepCount}
        />
      </section>

      <section className="section">
        <h2 className="section-title">Steps</h2>
        <BuilderItemList items={editor.draft.items} errors={editor.errors} hrZones={hrZones} ops={editor.ops} />
      </section>

      {editor.workout && (
        <SchedulePanel workout={editor.workout} dirty={editor.dirty} status={status} onPushed={editor.refresh} />
      )}
    </>
  )
}
