import type { FieldErrors, FormState, SetFormField } from '../../profileForm'
import { ProfileInput } from './ProfileInput'

interface AthleteFieldsProps {
  form: FormState
  fieldErrors: FieldErrors
  setField: SetFormField
}

/** Physiology, recent race, volume, and injury inputs. */
export function AthleteFields({ form, fieldErrors, setField }: AthleteFieldsProps) {
  return (
    <>
      <h2 className="card-title">Athlete</h2>
      <div className="form-grid">
        <ProfileInput id="max_hr" label="Max HR (bpm)" value={form.max_hr} onChange={(v) => setField('max_hr', v)} />
        <ProfileInput
          id="resting_hr"
          label="Resting HR (bpm)"
          value={form.resting_hr}
          onChange={(v) => setField('resting_hr', v)}
        />
        <ProfileInput
          id="threshold_hr"
          label="Threshold HR (bpm)"
          value={form.threshold_hr}
          onChange={(v) => setField('threshold_hr', v)}
        />
        <ProfileInput
          id="threshold_pace"
          label="Threshold pace (m:ss/km)"
          kind="mono"
          placeholder="4:30"
          value={form.threshold_pace}
          onChange={(v) => setField('threshold_pace', v)}
          error={fieldErrors.threshold_pace}
        />
        <ProfileInput
          id="recent_race_distance_km"
          label="Recent race distance (km)"
          kind="decimal"
          value={form.recent_race_distance_km}
          onChange={(v) => setField('recent_race_distance_km', v)}
        />
        <ProfileInput
          id="recent_race_time"
          label="Recent race time (h:mm:ss)"
          kind="mono"
          placeholder="1:45:30"
          value={form.recent_race_time}
          onChange={(v) => setField('recent_race_time', v)}
          error={fieldErrors.recent_race_time}
        />
        <ProfileInput
          id="current_weekly_volume_km"
          label="Current weekly volume (km)"
          kind="decimal"
          value={form.current_weekly_volume_km}
          onChange={(v) => setField('current_weekly_volume_km', v)}
        />
        <ProfileInput
          id="injury_history"
          label="Injury history (comma-separated)"
          kind="text"
          placeholder="achilles, it band"
          value={form.injury_history}
          onChange={(v) => setField('injury_history', v)}
        />
      </div>
    </>
  )
}
