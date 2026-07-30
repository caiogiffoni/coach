import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, ingestion } from '../api'
import type { ImportReport } from '../types'

const DATASET_LABELS: [keyof ImportReport, string][] = [
  ['activities', 'Activities'],
  ['daily_wellness', 'Daily wellness'],
  ['sleep', 'Sleep'],
  ['hrv', 'HRV'],
  ['vo2max', 'VO2max'],
  ['race_predictions', 'Race predictions'],
  ['training_load', 'Training load'],
  ['training_readiness', 'Training readiness'],
  ['training_history', 'Training history'],
  ['personal_records', 'Personal records'],
  ['biometric_profile', 'Biometric profile'],
]

export function Data() {
  const [path, setPath] = useState('')
  const [report, setReport] = useState<ImportReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setReport(null)
    setBusy(true)
    try {
      setReport(await ingestion.import(path.trim()))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  const total = report
    ? DATASET_LABELS.reduce((sum, [key]) => sum + report[key], 0)
    : 0

  return (
    <>
      <div className="page-header">
        <h1>Data</h1>
      </div>

      <section className="section">
        <form className="card" onSubmit={onSubmit}>
          <h2 className="card-title">Import Garmin export</h2>
          <div className="field">
            <label className="field-label" htmlFor="path">
              Path on the server
            </label>
            <input
              id="path"
              className="input mono"
              type="text"
              required
              placeholder="/path/to/garmin GDPR export dir or .zip (e.g. ../temp/garmin_info)"
              value={path}
              onChange={(e) => setPath(e.target.value)}
            />
            <p className="field-hint">
              Expects the GDPR export directory or zip on the server machine,
              not an upload from this browser.
            </p>
          </div>
          {error && (
            <div className="banner banner-danger" role="alert">
              {error}
            </div>
          )}
          <div className="form-actions">
            <button
              type="submit"
              className="button button-primary"
              disabled={busy || path.trim() === ''}
            >
              Import
            </button>
          </div>
        </form>
      </section>

      {report && (
        <section className="section">
          <div className="card">
            <h2 className="card-title">Import report</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th className="num">Rows</th>
                </tr>
              </thead>
              <tbody>
                {DATASET_LABELS.map(([key, label]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    <td className="num">{report[key]}</td>
                  </tr>
                ))}
                <tr>
                  <td>
                    <strong>Total</strong>
                  </td>
                  <td className="num">
                    <strong>{total}</strong>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
