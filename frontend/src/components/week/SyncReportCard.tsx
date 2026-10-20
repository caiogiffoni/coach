import type { SyncReport } from '../../types'

function SyncCount({ label, count }: { label: string; count: number }) {
  return (
    <div>
      <span className="field-label">{label}</span>
      <p className="mono">{count}</p>
    </div>
  )
}

/** Counts of rows pulled by the last Garmin sync. */
export function SyncReportCard({ report }: { report: SyncReport }) {
  return (
    <section className="section">
      <div className="card">
        <h2 className="card-title">Sync report</h2>
        <div className="sync-grid">
          <SyncCount label="Activities" count={report.activities} />
          <SyncCount label="Wellness" count={report.daily_wellness} />
          <SyncCount label="HRV" count={report.hrv} />
          <SyncCount label="Readiness" count={report.training_readiness} />
          <SyncCount label="Load" count={report.training_load} />
        </div>
        {report.skipped_datasets.length > 0 && (
          <div className="field">
            <span className="field-label">Skipped datasets</span>
            <p className="mono">{report.skipped_datasets.join(', ')}</p>
          </div>
        )}
        {report.newest_date && (
          <div className="field">
            <span className="field-label">Newest date</span>
            <p className="mono">{report.newest_date}</p>
          </div>
        )}
      </div>
    </section>
  )
}
