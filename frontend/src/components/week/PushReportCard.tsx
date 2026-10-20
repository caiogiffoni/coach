import type { PushReport } from '../../types'

/** Pushed, skipped, and failed dates from the last Garmin push. */
export function PushReportCard({ report }: { report: PushReport }) {
  const empty =
    report.pushed_dates.length === 0 && report.skipped_dates.length === 0 && report.errors.length === 0
  return (
    <section className="section">
      <div className="card">
        <h2 className="card-title">Push report</h2>
        {report.pushed_dates.length > 0 && (
          <div className="field">
            <span className="field-label">Pushed</span>
            <p className="mono">{report.pushed_dates.join(', ')}</p>
          </div>
        )}
        {report.skipped_dates.length > 0 && (
          <div className="field">
            <span className="field-label">Skipped</span>
            <ul>
              {report.skipped_dates.map((s, i) => (
                <li key={i}>
                  <span className="mono">{s.date}</span> — {s.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
        {report.errors.length > 0 && (
          <div className="field">
            <span className="field-label">Errors</span>
            <ul>
              {report.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        )}
        {empty && <p className="muted">No workouts to push.</p>}
      </div>
    </section>
  )
}
