import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, profile } from '../api'
import {
  formatPace,
  parseHms,
  parsePace,
  secToHms,
  secToMinSec,
  WEEKDAY_NAMES,
} from '../format'
import type { GoalMode, ProfileUpdate, RaceDistance, ZonesResponse } from '../types'

const RACE_DISTANCES: RaceDistance[] = ['5K', '10K', 'HM', 'MARATHON']

interface FormState {
  max_hr: string
  resting_hr: string
  threshold_pace: string // m:ss/km
  threshold_hr: string
  recent_race_distance_km: string
  recent_race_time: string // h:mm:ss
  current_weekly_volume_km: string
  injury_history: string // comma-separated
  goal_mode: GoalMode
  goal_race_distance: RaceDistance | ''
  goal_race_date: string
  preferred_days: number[]
}

const EMPTY_FORM: FormState = {
  max_hr: '',
  resting_hr: '',
  threshold_pace: '',
  threshold_hr: '',
  recent_race_distance_km: '',
  recent_race_time: '',
  current_weekly_volume_km: '',
  injury_history: '',
  goal_mode: 'health',
  goal_race_distance: '',
  goal_race_date: '',
  preferred_days: [],
}

function numOrNull(s: string): number | null {
  const t = s.trim()
  if (t === '') return null
  const n = Number(t)
  return Number.isNaN(n) ? null : n
}

export function Profile() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [exists, setExists] = useState(false)
  const [zones, setZones] = useState<ZonesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  async function load() {
    setLoading(true)
    try {
      const p = await profile.get()
      setExists(true)
      setForm({
        max_hr: p.max_hr?.toString() ?? '',
        resting_hr: p.resting_hr?.toString() ?? '',
        threshold_pace: secToMinSec(p.threshold_pace_sec_per_km),
        threshold_hr: p.threshold_hr?.toString() ?? '',
        recent_race_distance_km: p.recent_race_distance_km?.toString() ?? '',
        recent_race_time: secToHms(p.recent_race_time_sec),
        current_weekly_volume_km: p.current_weekly_volume_km?.toString() ?? '',
        injury_history: p.injury_history.join(', '),
        goal_mode: p.goal_mode,
        goal_race_distance: p.goal_race_distance ?? '',
        goal_race_date: p.goal_race_date ?? '',
        preferred_days: p.preferred_days,
      })
      setZones(await profile.zones())
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setExists(false)
        setZones(null)
      } else {
        setError(err instanceof ApiError ? err.message : 'Failed to load profile')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggleDay(day: number) {
    set(
      'preferred_days',
      form.preferred_days.includes(day)
        ? form.preferred_days.filter((d) => d !== day)
        : [...form.preferred_days, day].sort(),
    )
  }

  function validate(): ProfileUpdate | null {
    const errors: Record<string, string> = {}

    let thresholdPace: number | null = null
    if (form.threshold_pace.trim() !== '') {
      thresholdPace = parsePace(form.threshold_pace)
      if (thresholdPace === null) errors.threshold_pace = 'Use m:ss, e.g. 4:30'
    }

    let raceTime: number | null = null
    if (form.recent_race_time.trim() !== '') {
      raceTime = parseHms(form.recent_race_time)
      if (raceTime === null) errors.recent_race_time = 'Use h:mm:ss, e.g. 1:45:30'
    }

    if (form.goal_mode === 'race') {
      if (!form.goal_race_distance) errors.goal_race_distance = 'Required in race mode'
      if (!form.goal_race_date) errors.goal_race_date = 'Required in race mode'
    }

    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return null

    return {
      max_hr: numOrNull(form.max_hr),
      resting_hr: numOrNull(form.resting_hr),
      threshold_pace_sec_per_km: thresholdPace,
      threshold_hr: numOrNull(form.threshold_hr),
      recent_race_distance_km: numOrNull(form.recent_race_distance_km),
      recent_race_time_sec: raceTime,
      current_weekly_volume_km: numOrNull(form.current_weekly_volume_km),
      injury_history: form.injury_history
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      goal_mode: form.goal_mode,
      goal_race_distance:
        form.goal_mode === 'race' && form.goal_race_distance !== ''
          ? form.goal_race_distance
          : null,
      goal_race_date: form.goal_mode === 'race' ? form.goal_race_date || null : null,
      preferred_days: form.preferred_days,
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const body = validate()
    if (!body) return
    setBusy(true)
    try {
      await profile.update(body)
      setExists(true)
      setSaved(true)
      setZones(await profile.zones())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function onSeed() {
    setError(null)
    setBusy(true)
    try {
      await profile.seed()
      await load()
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Seed failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="muted">Loading…</p>
  }

  return (
    <>
      <div className="page-header">
        <h1>Profile</h1>
        <button
          type="button"
          className="button button-secondary"
          onClick={onSeed}
          disabled={busy}
        >
          Seed from Garmin data
        </button>
      </div>

      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
        </div>
      )}
      {saved && !error && <div className="banner banner-info">Profile saved.</div>}

      <section className="section">
        <form className="card" onSubmit={onSubmit}>
          <h2 className="card-title">Athlete</h2>
          <div className="form-grid">
            <div className="field">
              <label className="field-label" htmlFor="max_hr">Max HR (bpm)</label>
              <input
                id="max_hr"
                className="input"
                type="number"
                min="0"
                value={form.max_hr}
                onChange={(e) => set('max_hr', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="resting_hr">Resting HR (bpm)</label>
              <input
                id="resting_hr"
                className="input"
                type="number"
                min="0"
                value={form.resting_hr}
                onChange={(e) => set('resting_hr', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="threshold_hr">Threshold HR (bpm)</label>
              <input
                id="threshold_hr"
                className="input"
                type="number"
                min="0"
                value={form.threshold_hr}
                onChange={(e) => set('threshold_hr', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="threshold_pace">
                Threshold pace (m:ss/km)
              </label>
              <input
                id="threshold_pace"
                className="input mono"
                type="text"
                placeholder="4:30"
                value={form.threshold_pace}
                onChange={(e) => set('threshold_pace', e.target.value)}
              />
              {fieldErrors.threshold_pace && (
                <p className="field-error">{fieldErrors.threshold_pace}</p>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recent_race_distance_km">
                Recent race distance (km)
              </label>
              <input
                id="recent_race_distance_km"
                className="input"
                type="number"
                min="0"
                step="any"
                value={form.recent_race_distance_km}
                onChange={(e) => set('recent_race_distance_km', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="recent_race_time">
                Recent race time (h:mm:ss)
              </label>
              <input
                id="recent_race_time"
                className="input mono"
                type="text"
                placeholder="1:45:30"
                value={form.recent_race_time}
                onChange={(e) => set('recent_race_time', e.target.value)}
              />
              {fieldErrors.recent_race_time && (
                <p className="field-error">{fieldErrors.recent_race_time}</p>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="current_weekly_volume_km">
                Current weekly volume (km)
              </label>
              <input
                id="current_weekly_volume_km"
                className="input"
                type="number"
                min="0"
                step="any"
                value={form.current_weekly_volume_km}
                onChange={(e) => set('current_weekly_volume_km', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="injury_history">
                Injury history (comma-separated)
              </label>
              <input
                id="injury_history"
                className="input"
                type="text"
                placeholder="achilles, it band"
                value={form.injury_history}
                onChange={(e) => set('injury_history', e.target.value)}
              />
            </div>
          </div>

          <h2 className="card-title" style={{ marginTop: 16 }}>Goal</h2>
          <div className="field">
            <span className="field-label">Mode</span>
            <div className="checkbox-row">
              <label className="checkbox-label">
                <input
                  type="radio"
                  name="goal_mode"
                  checked={form.goal_mode === 'health'}
                  onChange={() => set('goal_mode', 'health')}
                />
                Health
              </label>
              <label className="checkbox-label">
                <input
                  type="radio"
                  name="goal_mode"
                  checked={form.goal_mode === 'race'}
                  onChange={() => set('goal_mode', 'race')}
                />
                Race
              </label>
            </div>
          </div>
          {form.goal_mode === 'race' && (
            <div className="form-grid">
              <div className="field">
                <label className="field-label" htmlFor="goal_race_distance">
                  Race distance
                </label>
                <select
                  id="goal_race_distance"
                  className="select"
                  value={form.goal_race_distance}
                  onChange={(e) =>
                    set('goal_race_distance', e.target.value as RaceDistance | '')
                  }
                >
                  <option value="">Select…</option>
                  {RACE_DISTANCES.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
                {fieldErrors.goal_race_distance && (
                  <p className="field-error">{fieldErrors.goal_race_distance}</p>
                )}
              </div>
              <div className="field">
                <label className="field-label" htmlFor="goal_race_date">Race date</label>
                <input
                  id="goal_race_date"
                  className="input"
                  type="date"
                  value={form.goal_race_date}
                  onChange={(e) => set('goal_race_date', e.target.value)}
                />
                {fieldErrors.goal_race_date && (
                  <p className="field-error">{fieldErrors.goal_race_date}</p>
                )}
              </div>
            </div>
          )}

          <div className="field" style={{ marginTop: 4 }}>
            <span className="field-label">Preferred run days</span>
            <div className="checkbox-row">
              {WEEKDAY_NAMES.map((name, i) => (
                <label className="checkbox-label" key={name}>
                  <input
                    type="checkbox"
                    checked={form.preferred_days.includes(i)}
                    onChange={() => toggleDay(i)}
                  />
                  {name}
                </label>
              ))}
            </div>
          </div>

          <div className="form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              Save profile
            </button>
          </div>
        </form>
      </section>

      {exists && zones && (
        <section className="section">
          <h2 className="section-title">Training zones</h2>
          <div className="card">
            {zones.hr_zones && (
              <>
                <h3 className="card-title">
                  Heart rate{' '}
                  <span className="muted" style={{ fontWeight: 400 }}>
                    ({zones.hr_source})
                  </span>
                </h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th className="num">Min (bpm)</th>
                      <th className="num">Max (bpm)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.hr_zones.map((z) => (
                      <tr key={z.zone}>
                        <td>
                          <span className={`badge badge-${z.zone.toLowerCase()}`}>
                            {z.zone}
                          </span>
                        </td>
                        <td className="num">{z.min_bpm}</td>
                        <td className="num">{z.max_bpm}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {zones.pace_zones && (
              <>
                <h3 className="card-title" style={{ marginTop: 16 }}>
                  Pace{' '}
                  <span className="muted" style={{ fontWeight: 400 }}>
                    (threshold {formatPace(zones.threshold_pace_sec_per_km)},{' '}
                    {zones.threshold_pace_source === 'profile'
                      ? 'from profile'
                      : 'estimated from race'}
                    )
                  </span>
                </h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th className="num">From</th>
                      <th className="num">To</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.pace_zones.map((z) => (
                      <tr key={z.name}>
                        <td>{z.name}</td>
                        <td className="num">{formatPace(z.min_sec_per_km)}</td>
                        <td className="num">{formatPace(z.max_sec_per_km)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            <p className="muted mono" style={{ marginTop: 16, fontSize: 13 }}>
              {zones.weekly_ceiling_km !== null &&
                `Weekly ceiling ${zones.weekly_ceiling_km.toFixed(1)} km`}
              {zones.weekly_ceiling_km !== null &&
                zones.intensity_budget_km !== null &&
                ' · '}
              {zones.intensity_budget_km !== null &&
                `Intensity budget ${zones.intensity_budget_km.toFixed(1)} km`}
            </p>
          </div>
        </section>
      )}
    </>
  )
}
