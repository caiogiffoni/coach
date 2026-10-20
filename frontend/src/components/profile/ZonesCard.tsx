import { formatPace } from '../../format'
import type { HrZone, PaceZone, ZonesResponse } from '../../types'

function HrZonesTable({ zones, source }: { zones: HrZone[]; source: ZonesResponse['hr_source'] }) {
  return (
    <>
      <h3 className="card-title">
        Heart rate{' '}
        <span className="muted" style={{ fontWeight: 400 }}>
          ({source})
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
          {zones.map((z) => (
            <tr key={z.zone}>
              <td>
                <span className={`badge badge-${z.zone.toLowerCase()}`}>{z.zone}</span>
              </td>
              <td className="num">{z.min_bpm}</td>
              <td className="num">{z.max_bpm}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function PaceZonesTable({ zones, info }: { zones: PaceZone[]; info: ZonesResponse }) {
  return (
    <>
      <h3 className="card-title" style={{ marginTop: 16 }}>
        Pace{' '}
        <span className="muted" style={{ fontWeight: 400 }}>
          (threshold {formatPace(info.threshold_pace_sec_per_km)},{' '}
          {info.threshold_pace_source === 'profile' ? 'from profile' : 'estimated from race'})
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
          {zones.map((z) => (
            <tr key={z.name}>
              <td>{z.name}</td>
              <td className="num">{formatPace(z.min_sec_per_km)}</td>
              <td className="num">{formatPace(z.max_sec_per_km)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function budgetSummary(zones: ZonesResponse): string {
  const parts: string[] = []
  if (zones.weekly_ceiling_km !== null) parts.push(`Weekly ceiling ${zones.weekly_ceiling_km.toFixed(1)} km`)
  if (zones.intensity_budget_km !== null) parts.push(`Intensity budget ${zones.intensity_budget_km.toFixed(1)} km`)
  return parts.join(' · ')
}

/** HR and pace zone tables plus the weekly volume/intensity budget. */
export function ZonesCard({ zones }: { zones: ZonesResponse }) {
  return (
    <section className="section">
      <h2 className="section-title">Training zones</h2>
      <div className="card">
        {zones.hr_zones && <HrZonesTable zones={zones.hr_zones} source={zones.hr_source} />}
        {zones.pace_zones && <PaceZonesTable zones={zones.pace_zones} info={zones} />}
        <p className="muted mono" style={{ marginTop: 16, fontSize: 13 }}>
          {budgetSummary(zones)}
        </p>
      </div>
    </section>
  )
}
