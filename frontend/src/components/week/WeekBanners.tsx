import { Link } from 'react-router'
import type { GarminStatus, WeekPlan } from '../../types'

interface WeekBannersProps {
  error: string | null
  garminStatus: GarminStatus | null
  stalenessText: string | null
  plan: WeekPlan | null
}

function ErrorBanner({ error }: { error: string }) {
  return (
    <div className="banner banner-danger" role="alert">
      {error}
      {error.includes('Profile not found') && (
        <>
          {' '}
          <Link to="/profile">Create your profile</Link>
        </>
      )}
      {error.includes('No imported data') && (
        <>
          {' '}
          <Link to="/data">Import data</Link>
        </>
      )}
    </div>
  )
}

function ValidationBanner({ errors }: { errors: string[] }) {
  return (
    <div className="banner banner-danger" role="alert">
      Validation errors
      <ul>
        {errors.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
    </div>
  )
}

/** Error, Garmin-config, data-staleness, fallback, and validation banners. */
export function WeekBanners({ error, garminStatus, stalenessText, plan }: WeekBannersProps) {
  return (
    <>
      {error && <ErrorBanner error={error} />}
      {garminStatus && !garminStatus.configured && (
        <div className="banner banner-warning" role="alert">
          Garmin credentials not configured. Push to Garmin and auto-sync are
          disabled until GARMIN_EMAIL and GARMIN_PASSWORD are set on the backend.
        </div>
      )}
      {stalenessText && (
        <div className="banner banner-info" role="status">
          {stalenessText}
        </div>
      )}
      {plan?.source === 'fallback' && (
        <div className="banner banner-warning">LLM unavailable — built from template.</div>
      )}
      {plan && plan.validation_errors.length > 0 && <ValidationBanner errors={plan.validation_errors} />}
    </>
  )
}
