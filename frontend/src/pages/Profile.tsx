import { AthleteFields } from '../components/profile/AthleteFields'
import { GoalFields } from '../components/profile/GoalFields'
import { ZonesCard } from '../components/profile/ZonesCard'
import { WeekdayCheckboxes } from '../components/WeekdayCheckboxes'
import { useProfileForm } from '../hooks/useProfileForm'

export function Profile() {
  const p = useProfileForm()

  if (p.loading) {
    return <p className="muted">Loading…</p>
  }

  return (
    <>
      <div className="page-header">
        <h1>Profile</h1>
        <button type="button" className="button button-secondary" onClick={p.onSeed} disabled={p.busy}>
          Seed from Garmin data
        </button>
      </div>

      {p.error && (
        <div className="banner banner-danger" role="alert">
          {p.error}
        </div>
      )}
      {p.saved && !p.error && <div className="banner banner-info">Profile saved.</div>}

      <section className="section">
        <form className="card" onSubmit={p.onSubmit}>
          <AthleteFields form={p.form} fieldErrors={p.fieldErrors} setField={p.setField} />
          <GoalFields form={p.form} fieldErrors={p.fieldErrors} setField={p.setField} />
          <div className="field" style={{ marginTop: 4 }}>
            <span className="field-label">Preferred run days</span>
            <WeekdayCheckboxes selected={p.form.preferred_days} onToggle={p.toggleDay} />
          </div>
          <div className="form-actions">
            <button type="submit" className="button button-primary" disabled={p.busy}>
              Save profile
            </button>
          </div>
        </form>
      </section>

      {p.exists && p.zones && <ZonesCard zones={p.zones} />}
    </>
  )
}
