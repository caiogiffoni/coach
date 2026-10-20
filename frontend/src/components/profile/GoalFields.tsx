import { RACE_DISTANCES } from '../../profileForm'
import type { FieldErrors, FormState, SetFormField } from '../../profileForm'
import type { GoalMode, RaceDistance } from '../../types'

interface GoalFieldsProps {
  form: FormState
  fieldErrors: FieldErrors
  setField: SetFormField
}

function GoalModeRadio({ mode, label, form, setField }: { mode: GoalMode; label: string } & Omit<GoalFieldsProps, 'fieldErrors'>) {
  return (
    <label className="checkbox-label">
      <input
        type="radio"
        name="goal_mode"
        checked={form.goal_mode === mode}
        onChange={() => setField('goal_mode', mode)}
      />
      {label}
    </label>
  )
}

function RaceGoalFields({ form, fieldErrors, setField }: GoalFieldsProps) {
  return (
    <div className="form-grid">
      <div className="field">
        <label className="field-label" htmlFor="goal_race_distance">
          Race distance
        </label>
        <select
          id="goal_race_distance"
          className="select"
          value={form.goal_race_distance}
          onChange={(e) => setField('goal_race_distance', e.target.value as RaceDistance | '')}
        >
          <option value="">Select…</option>
          {RACE_DISTANCES.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        {fieldErrors.goal_race_distance && <p className="field-error">{fieldErrors.goal_race_distance}</p>}
      </div>
      <div className="field">
        <label className="field-label" htmlFor="goal_race_date">Race date</label>
        <input
          id="goal_race_date"
          className="input"
          type="date"
          value={form.goal_race_date}
          onChange={(e) => setField('goal_race_date', e.target.value)}
        />
        {fieldErrors.goal_race_date && <p className="field-error">{fieldErrors.goal_race_date}</p>}
      </div>
    </div>
  )
}

/** Goal mode (health/race) and, in race mode, target distance and date. */
export function GoalFields(props: GoalFieldsProps) {
  return (
    <>
      <h2 className="card-title" style={{ marginTop: 16 }}>Goal</h2>
      <div className="field">
        <span className="field-label">Mode</span>
        <div className="checkbox-row">
          <GoalModeRadio mode="health" label="Health" form={props.form} setField={props.setField} />
          <GoalModeRadio mode="race" label="Race" form={props.form} setField={props.setField} />
        </div>
      </div>
      {props.form.goal_mode === 'race' && <RaceGoalFields {...props} />}
    </>
  )
}
