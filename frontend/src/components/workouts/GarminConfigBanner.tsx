import type { GarminStatus } from '../../types'

/** Warns that Garmin pushes are disabled until credentials are set. */
export function GarminConfigBanner({ garminStatus }: { garminStatus: GarminStatus | null }) {
  if (!garminStatus || garminStatus.configured) return null
  return (
    <div className="banner banner-warning" role="alert">
      Garmin credentials not configured. Push to Garmin is disabled until GARMIN_EMAIL and GARMIN_PASSWORD are set on the
      backend.
    </div>
  )
}
